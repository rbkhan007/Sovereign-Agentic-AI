import logging
import time
import json
import threading
import os as _os
from typing import List, Optional, Dict, Any
from threading import Lock, RLock

from config import CONFIG

logger = logging.getLogger(__name__)

_embedder = None
_embedder_lock = Lock()
_pgadmin_lock = Lock()
_pool = None
_pool_lock = RLock()
_query_cache: Dict[str, List[str]] = {}
_query_cache_time: Dict[str, float] = {}
_cache_lock = Lock()
_CACHE_TTL = 30.0
_MAX_CACHE = 100
_MAX_THOUGHT = 2000
_prune_thread = None
_prune_thread_lock = Lock()
_prune_stop = threading.Event()
_ivfflat_attempted = False
_last_reindex_ts = 0.0
_reindex_lock = Lock()
_seq_count_lock = Lock()


def get_embedder():
    global _embedder
    if _embedder is None:
        with _embedder_lock:
            if _embedder is None:
                try:
                    from sentence_transformers import SentenceTransformer
                    _device = "cpu"
                    try:
                        import torch
                        if torch.cuda.is_available():
                            _device = "cuda"
                    except ImportError:
                        pass
                    _embedder = SentenceTransformer("all-MiniLM-L6-v2", device=_device)
                    logger.info(f"Embedding model loaded on {_device}")
                except Exception as e:
                    logger.warning(f"Embedding model failed: {e}")
    return _embedder

_pool_down = False

_reconnect_thread = None
_reconnect_stop = threading.Event()
_reconnect_lock = Lock()

_INDEX_MIN_ROWS = 2000  # below this, force a seq scan: IVFFlat/HNSW index scans are unreliable on tiny tables
_SEQ_COUNT_TS = 0.0
_SEQ_COUNT_ROWS: int | None = None
_SEQ_COUNT_TTL = 30.0


def _memory_row_count(cur) -> int:
    """Return an estimate of the agent_memory row count, cached for a short TTL."""
    global _SEQ_COUNT_TS, _SEQ_COUNT_ROWS
    now = time.time()
    with _seq_count_lock:
        if _SEQ_COUNT_ROWS is not None and (now - _SEQ_COUNT_TS) < _SEQ_COUNT_TTL:
            return _SEQ_COUNT_ROWS
        try:
            cur.execute("SELECT COUNT(*) FROM agent_memory")
            rows = cur.fetchone()[0] or 0
            _SEQ_COUNT_ROWS = int(rows)
            _SEQ_COUNT_TS = now
            return _SEQ_COUNT_ROWS
        except Exception:
            return 0


def _force_seq_scan(cur):
    """Best-effort: make the current transaction's next query use a sequential scan
    so pgvector similarity search is exact on small tables instead of returning
    empty results from an index scan (IVFFlat probes=1 misses everything when few
    rows are spread across many lists)."""
    try:
        if _memory_row_count(cur) < _INDEX_MIN_ROWS:
            cur.execute("SET LOCAL enable_indexscan=off; SET LOCAL enable_bitmapscan=off")
    except Exception:
        pass


def _reconnect_loop():
    global _pool, _pool_down
    while not _reconnect_stop.is_set():
        _reconnect_stop.wait(timeout=30)
        if _reconnect_stop.is_set():
            break
        try:
            with _pool_lock:
                if _pool_down and CONFIG.db.enabled and _pool is None:
                    logger.info("DB reconnect: attempting pool recovery")
                    _pool_down = False
                    try:
                        from psycopg2 import pool
                        _pool = pool.ThreadedConnectionPool(
                            minconn=1, maxconn=CONFIG.db.maxconn,
                            dsn=CONFIG.db.uri_with_password,
                        )
                        _ensure_schema()
                        logger.info("DB reconnect: pool restored")
                    except Exception as e:
                        _pool_down = True
                        _pool = None
                        logger.warning(f"DB reconnect failed: {e}")
        except Exception as e:
            logger.warning(f"DB reconnect error: {e}")


def _start_reconnect_thread():
    global _reconnect_thread
    if _reconnect_thread and _reconnect_thread.is_alive():
        return
    _reconnect_stop.clear()
    _reconnect_thread = threading.Thread(target=_reconnect_loop, daemon=True, name="db-reconnect")
    _reconnect_thread.start()


def get_pool():
    global _pool, _pool_down
    with _pool_lock:
        if _pool is None and CONFIG.db.enabled:
            if _pool_down:
                # Postgres is down: short-circuit to avoid reconnect storms while
                # the background reconnect thread owns recovery (stalls every DB
                # call otherwise, including chat + /v1/health).
                return None
            _pool_down = False
            try:
                from psycopg2 import pool
                _pool = pool.ThreadedConnectionPool(
                    minconn=1, maxconn=CONFIG.db.maxconn,
                    dsn=CONFIG.db.uri_with_password,
                )
                _ensure_schema()
                logger.info(f"DB pool ready: {CONFIG.db.database}")
                _start_reconnect_thread()
            except Exception as e:
                _pool_down = True
                _pool = None
                _start_reconnect_thread()
                logger.warning(f"DB pool failed: {e}")
    return _pool


def enable_if_available(timeout: float = 3.0) -> bool:
    """Probe the configured PostgreSQL server at startup and run on it when reachable.

    Flips ``CONFIG.db.enabled`` on and builds the pool/schema so the app uses real
    stored data; returns False (staying in-memory) when Postgres is unreachable.

    If the target database does not exist, it is created automatically (requires
    superuser or CREATEDB privilege on the configured user).
    """
    if _pool is not None:
        return True
    if not CONFIG.db.enabled:
        try:
            import psycopg2
            import psycopg2.extensions
            # Try connecting to the target database first
            try:
                conn = psycopg2.connect(
                    host=CONFIG.db.host, port=CONFIG.db.port,
                    user=CONFIG.db.user, password=CONFIG.db.password,
                    dbname=CONFIG.db.database, connect_timeout=int(timeout),
                )
                conn.close()
            except psycopg2.OperationalError as e:
                # Database does not exist — attempt to create it
                if "does not exist" in str(e) or "database" in str(e).lower():
                    logger.info(f"Database '{CONFIG.db.database}' not found, attempting auto-creation...")
                    try:
                        with _pool_lock:
                            if _pool is not None:
                                return True
                            conn = psycopg2.connect(
                                host=CONFIG.db.host, port=CONFIG.db.port,
                                user=CONFIG.db.user, password=CONFIG.db.password,
                                dbname="postgres", connect_timeout=int(timeout),
                            )
                            conn.autocommit = True
                            with conn.cursor() as cur:
                                # Sanitize database name for SQL
                                db_name = CONFIG.db.database.replace("'", "''")
                                cur.execute(f'CREATE DATABASE "{db_name}"')
                            conn.close()
                            logger.info(f"Database '{CONFIG.db.database}' created successfully")
                            # Now connect to the new database
                            conn = psycopg2.connect(
                                host=CONFIG.db.host, port=CONFIG.db.port,
                                user=CONFIG.db.user, password=CONFIG.db.password,
                                dbname=CONFIG.db.database, connect_timeout=int(timeout),
                            )
                            conn.close()
                    except Exception as ce:
                        logger.warning(f"Auto-create database failed: {ce}")
                        logger.info(f"Database unavailable ({e}); staying in-memory")
                        return False
                else:
                    logger.info(f"Database unavailable ({e}); staying in-memory")
                    return False
            CONFIG.db.enabled = True
            logger.info(f"Database auto-detected: {CONFIG.db.database}@{CONFIG.db.host}:{CONFIG.db.port}")
            _register_pgadmin_connection()
        except Exception as e:
            logger.info(f"Database unavailable ({e}); staying in-memory")
            return False
    return get_pool() is not None


def _register_pgadmin_connection():
    """Register the database connection in pgAdmin 4 servers.json if pgAdmin is installed."""
    import json as _json
    pgadmin_paths = [
        _os.path.expanduser("~/.pgadmin/servers.json"),
        _os.path.expandvars(r"%APPDATA%\pgAdmin\servers.json"),
    ]
    server_entry = {
        "Name": f"Agentic LLM ({CONFIG.db.database})",
        "Group": "Agentic LLM",
        "Host": CONFIG.db.host,
        "Port": CONFIG.db.port,
        "MaintenanceDB": "postgres",
        "Username": CONFIG.db.user,
        "SSLMode": "prefer",
        "PassFile": "",
        "KerberosAuthentication": False,
        "ConnectionType": 0,
        "Database": CONFIG.db.database,
    }
    for path in pgadmin_paths:
        try:
            if not path or not _os.path.dirname(path):
                continue
            dirpath = _os.path.dirname(path)
            if not _os.path.isdir(dirpath):
                continue
            existing = {}
            if _os.path.exists(path):
                with open(path, "r") as f:
                    existing = _json.load(f)
            # Find next available server ID
            max_id = 0
            for k in existing:
                try:
                    max_id = max(max_id, int(k))
                except (ValueError, TypeError):
                    pass
            new_id = str(max_id + 1)
            # Check if this database is already registered
            already_registered = False
            for _k, v in existing.items():
                if isinstance(v, dict) and v.get("Database") == CONFIG.db.database:
                    already_registered = True
                    break
            if not already_registered:
                existing[new_id] = server_entry
                with _pgadmin_lock:
                    with open(path, "w") as f:
                        _json.dump(existing, f, indent=2)
                logger.info(f"pgAdmin 4 connection registered: {path} (id={new_id})")
            break
        except Exception as e:
            logger.debug(f"pgAdmin 4 registration skipped ({path}): {e}")


def _ensure_schema():
    global _ivfflat_attempted
    conn = _get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS agent_memory (
                    id BIGSERIAL PRIMARY KEY,
                    agent_name TEXT NOT NULL DEFAULT 'default',
                    thought TEXT NOT NULL,
                    embedding vector(384),
                    tokens INT DEFAULT 0,
                    metadata JSONB DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    system_prompt TEXT DEFAULT '',
                    default_model TEXT DEFAULT '',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS workspace_files (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    size INT DEFAULT 0,
                    chunk_count INT DEFAULT 0,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            conn.commit()
            _seed_default_workspace(conn)
        try:
            import graph_store
            graph_store.ensure_schema(conn)
        except Exception as e:
            logger.warning(f"Graph schema: {e}")
        with conn.cursor() as cur:
            cur.execute("""
                DO $$ BEGIN
                    ALTER TABLE agent_memory ADD COLUMN IF NOT EXISTS tokens INT DEFAULT 0;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            """)
            cur.execute("""
                DO $$ BEGIN
                    ALTER TABLE agent_memory ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
                EXCEPTION WHEN duplicate_column THEN NULL;
                END $$;
            """)
            conn.commit()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_memory_agent
                ON agent_memory (agent_name, created_at DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_memory_created
                ON agent_memory (created_at DESC);
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_workspace_files_ws
                ON workspace_files (workspace_id);
            """)
            conn.commit()
        if not _ivfflat_attempted:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM agent_memory")
                    count = cur.fetchone()[0]
                    _create_vector_index(conn, count)
            except Exception as e:
                logger.info(f"Vector index deferred: {e}")
            _ivfflat_attempted = True
    except Exception as e:
        logger.warning(f"Schema setup: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def _create_vector_index(conn, count):
    """Pick the right pgvector index for the current table size.
    <100 rows: no index (seq scan is faster)
    100-2000 rows: HNSW (better recall at small scale)
    >2000 rows: IVFFlat (lists = sqrt(rows), standard large-scale choice)
    Automatically drops + recreates when the table crosses a threshold.
    """
    cur = conn.cursor()
    try:
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = 'idx_agent_memory_ivfflat'")
        has_ivfflat = cur.fetchone() is not None
        cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = 'idx_agent_memory_hnsw'")
        has_hnsw = cur.fetchone() is not None

        if count < 100:
            if has_ivfflat:
                cur.execute("DROP INDEX IF EXISTS idx_agent_memory_ivfflat")
                logger.info("Vector index dropped (table < 100 rows, seq scan faster)")
            if has_hnsw:
                cur.execute("DROP INDEX IF EXISTS idx_agent_memory_hnsw")
            conn.commit()
        elif count <= 2000:
            if has_ivfflat:
                cur.execute("DROP INDEX IF EXISTS idx_agent_memory_ivfflat")
                logger.info("IVFFlat dropped, switching to HNSW (<2000 rows)")
            if not has_hnsw:
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_agent_memory_hnsw
                    ON agent_memory USING hnsw (embedding vector_cosine_ops);
                """)
                logger.info("HNSW index created")
            conn.commit()
        else:
            if has_hnsw:
                cur.execute("DROP INDEX IF EXISTS idx_agent_memory_hnsw")
                logger.info("HNSW dropped, switching to IVFFlat (>2000 rows)")
            if not has_ivfflat:
                lists = max(1, int(count ** 0.5))
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_agent_memory_ivfflat
                    ON agent_memory USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = {lists});
                """)
                logger.info(f"IVFFlat index created (lists={lists})")
            conn.commit()
    except Exception as e:
        conn.rollback()
        logger.info(f"Vector index maintenance deferred: {e}")
    finally:
        cur.close()


_REINDEX_THROTTLE_S = 60.0


def _maybe_reindex():
    """Periodically re-evaluate the vector index as the table grows.
    Runs at most once per throttle window (default 60s) after inserts so
    the index automatically switches when the row count crosses a threshold.
    """
    global _ivfflat_attempted, _last_reindex_ts
    now = time.time()
    with _reindex_lock:
        if now - _last_reindex_ts < _REINDEX_THROTTLE_S:
            return
        _last_reindex_ts = now
    conn = _get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM agent_memory")
            count = cur.fetchone()[0]
            _create_vector_index(conn, count)
            _ivfflat_attempted = True
            logger.info(f"Vector index checked ({count} rows)")
    except Exception:
        pass
    finally:
        _put_conn(conn)


def _get_conn():
    pool = get_pool()
    if not pool:
        return None
    try:
        for _ in range(CONFIG.db.maxconn):
            conn = pool.getconn()
            if conn is not None:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                    return conn
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
        return None
    except Exception as e:
        logger.warning(f"Get conn: {e}")
        return None


def _put_conn(conn):
    pool = get_pool()
    if pool and conn:
        try:
            try:
                pool.putconn(conn)
            except Exception as e:
                logger.warning(f"Return conn failed: {e}")
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Return conn failed: {e}")
            try:
                conn.close()
            except Exception:
                pass


def store_thought(agent: str, thought: str, metadata: Optional[dict] = None):
    if not thought or not thought.strip():
        return
    thought = thought.strip()[:_MAX_THOUGHT]
    conn = _get_conn()
    if not conn:
        return
    embedder = get_embedder()
    if not embedder:
        _put_conn(conn)
        return
    try:
        vec = embedder.encode(thought, normalize_embeddings=True).tolist()
        tok = len(thought.split())
        meta = json.dumps(metadata or {})
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO agent_memory (agent_name, thought, embedding, tokens, metadata) VALUES (%s, %s, %s::vector, %s, %s::jsonb)",
                (agent, thought, str(vec), tok, meta),
            )
            conn.commit()
            _invalidate_cache()
            _maybe_reindex()
    except Exception as e:
        logger.warning(f"Store failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def store_batch(entries: List[Dict[str, Any]]):
    if not entries:
        return
    conn = _get_conn()
    if not conn:
        return
    embedder = get_embedder()
    if not embedder:
        _put_conn(conn)
        return
    try:
        valid = []
        for e in entries:
            thought = e.get("thought", "")
            if not isinstance(thought, str):
                thought = str(thought)
            thought = thought.strip()[:_MAX_THOUGHT]
            if thought:
                valid.append((e, thought))
        if not valid:
            return
        vecs = embedder.encode([t for _, t in valid], normalize_embeddings=True).tolist()
        rows = []
        for (e, thought), vec in zip(valid, vecs):
            agent = e.get("agent", "default")
            meta = json.dumps(e.get("metadata", {}))
            tok = len(thought.split())
            rows.append((agent, thought, str(vec), tok, meta))
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            execute_values(
                cur,
                "INSERT INTO agent_memory (agent_name, thought, embedding, tokens, metadata) VALUES %s",
                rows,
                template="(%s, %s, %s::vector, %s, %s::jsonb)",
                page_size=500,
            )
            conn.commit()
            _invalidate_cache()
            _maybe_reindex()
    except Exception as e:
        logger.warning(f"Batch store failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)


def retrieve_similar(query: str, limit: int = 5, agent_filter: Optional[str] = None,
                     min_score: float = 0.0) -> List[str]:
    limit = max(1, min(limit, 50))
    now = time.time()
    cache_key = f"{query}:{limit}:{agent_filter}:{min_score}"
    with _cache_lock:
        if cache_key in _query_cache and now - _query_cache_time.get(cache_key, 0) < _CACHE_TTL:
            return list(_query_cache[cache_key])

    conn = _get_conn()
    if not conn:
        return []
    embedder = get_embedder()
    if not embedder:
        _put_conn(conn)
        return []
    try:
        vec = embedder.encode(query, normalize_embeddings=True).tolist()
        with conn.cursor() as cur:
            _force_seq_scan(cur)
            if agent_filter:
                cur.execute(
                    "SELECT thought, (embedding <=> %s::vector) AS dist FROM agent_memory WHERE agent_name = %s ORDER BY dist LIMIT %s",
                    (str(vec), agent_filter, limit),
                )
            else:
                cur.execute(
                    "SELECT thought, (embedding <=> %s::vector) AS dist FROM agent_memory ORDER BY dist LIMIT %s",
                    (str(vec), limit),
                )
            rows = cur.fetchall()
        results = [row[0] for row in rows if row[1] <= (1.0 - min_score)]
        with _cache_lock:
            while len(_query_cache) >= _MAX_CACHE and _query_cache:
                oldest = min(_query_cache_time, key=lambda k: _query_cache_time[k])
                _query_cache.pop(oldest, None)
                _query_cache_time.pop(oldest, None)
            _query_cache[cache_key] = results
            _query_cache_time[cache_key] = now
        return list(results)
    except Exception as e:
        logger.warning(f"Retrieve failed: {e}")
        return []
    finally:
        _put_conn(conn)


def count_memories(agent: Optional[str] = None) -> int:
    conn = _get_conn()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            if agent:
                cur.execute("SELECT COUNT(*) FROM agent_memory WHERE agent_name = %s", (agent,))
            else:
                cur.execute("SELECT COUNT(*) FROM agent_memory")
            return cur.fetchone()[0]
    except Exception as e:
        logger.warning(f"Count failed: {e}")
        return 0
    finally:
        _put_conn(conn)


def recent_memories(limit: int = 20, agent: Optional[str] = None) -> List[Dict[str, Any]]:
    """Newest memories as dicts (id, agent, thought, tokens, created_at, metadata)."""
    limit = max(1, min(limit, 100))
    conn = _get_conn()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            if agent:
                cur.execute(
                    "SELECT id, agent_name, thought, tokens, created_at, metadata "
                    "FROM agent_memory WHERE agent_name = %s ORDER BY created_at DESC LIMIT %s",
                    (agent, limit),
                )
            else:
                cur.execute(
                    "SELECT id, agent_name, thought, tokens, created_at, metadata "
                    "FROM agent_memory ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
            rows = cur.fetchall()
        out = []
        for r in rows:
            meta = r[5] or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            out.append({
                "id": r[0],
                "agent": r[1],
                "thought": r[2],
                "tokens": r[3] or 0,
                "created_at": r[4].isoformat() if r[4] else None,
                "metadata": meta,
            })
        return out
    except Exception as e:
        logger.warning(f"Recent failed: {e}")
        return []
    finally:
        _put_conn(conn)


def search_memories(query: str, limit: int = 5, agent: Optional[str] = None,
                    min_score: float = 0.0) -> List[Dict[str, Any]]:
    """Semantic pgvector search returning rich results with similarity scores."""
    limit = max(1, min(limit, 50))
    conn = _get_conn()
    if not conn:
        return []
    embedder = get_embedder()
    if not embedder:
        _put_conn(conn)
        return []
    try:
        vec = embedder.encode(query, normalize_embeddings=True).tolist()
        with conn.cursor() as cur:
            _force_seq_scan(cur)
            if agent:
                cur.execute(
                    "SELECT id, agent_name, thought, tokens, created_at, (embedding <=> %s::vector) AS dist "
                    "FROM agent_memory WHERE agent_name = %s ORDER BY dist LIMIT %s",
                    (str(vec), agent, limit),
                )
            else:
                cur.execute(
                    "SELECT id, agent_name, thought, tokens, created_at, (embedding <=> %s::vector) AS dist "
                    "FROM agent_memory ORDER BY dist LIMIT %s",
                    (str(vec), limit),
                )
            rows = cur.fetchall()
        out = []
        for r in rows:
            if r[5] is not None and r[5] > (1.0 - min_score):
                continue
            out.append({
                "id": r[0],
                "agent": r[1],
                "thought": r[2],
                "tokens": r[3] or 0,
                "created_at": r[4].isoformat() if r[4] else None,
                "similarity": max(0.0, 1.0 - r[5]) if r[5] is not None else 0.0,
                "distance": round(r[5], 4) if r[5] is not None else None,
            })
        return out
    except Exception as e:
        logger.warning(f"Search failed: {e}")
        return []
    finally:
        _put_conn(conn)


def clear_memories() -> int:
    """Delete every memory row. Returns the number deleted."""
    conn = _get_conn()
    if not conn:
        return 0
    deleted = 0
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agent_memory")
            deleted = cur.rowcount
            conn.commit()
            _invalidate_cache()
        if deleted:
            logger.info(f"Cleared {deleted} memories")
    except Exception as e:
        logger.warning(f"Clear failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)
    return deleted


def db_stats() -> Dict[str, Any]:
    """Health + usage snapshot for the UI: connection, counts, index, cache, prune."""
    info: Dict[str, Any] = {
        "enabled": CONFIG.db.enabled,
        "connected": False,
        "count": 0,
        "total_tokens": 0,
        "agents": {},
        "vector_dim": 384,
        "ivfflat": False,
        "hnsw": False,
        "table_bytes": 0,
        "cache_entries": 0,
        "pool": {"min": 1, "max": CONFIG.db.maxconn, "active": 0},
        "auto_prune": False,
        "prune_interval_hours": CONFIG.prune_interval_hours,
        "prune_max_age_days": CONFIG.prune_max_age_days,
    }
    with _cache_lock:
        info["cache_entries"] = len(_query_cache)
    with _pool_lock:
        info["auto_prune"] = _prune_thread is not None and _prune_thread.is_alive()
    conn = _get_conn()
    if not conn:
        return info
    info["connected"] = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*), COALESCE(SUM(tokens), 0) FROM agent_memory")
            row = cur.fetchone()
            info["count"] = row[0] or 0
            info["total_tokens"] = row[1] or 0
            cur.execute("SELECT agent_name, COUNT(*) FROM agent_memory GROUP BY agent_name ORDER BY 2 DESC, 1")
            info["agents"] = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute("SELECT COUNT(*) FROM pg_indexes WHERE indexname = 'idx_agent_memory_ivfflat'")
            info["ivfflat"] = (cur.fetchone()[0] or 0) > 0
            cur.execute("SELECT COUNT(*) FROM pg_indexes WHERE indexname = 'idx_agent_memory_hnsw'")
            info["hnsw"] = (cur.fetchone()[0] or 0) > 0
            cur.execute("SELECT pg_total_relation_size('agent_memory')")
            info["table_bytes"] = cur.fetchone()[0] or 0
            try:
                cur.execute(
                    "SELECT atttypmod, format_type(a.atttypid, a.atttypmod) "
                    "FROM pg_attribute a "
                    "WHERE a.attrelid = 'agent_memory'::regclass AND a.attname = 'embedding'"
                )
                r = cur.fetchone()
                if r and r[0]:
                    typ, typmod = r[1], r[0]
                    if typ and typ.lower().startswith("vector"):
                        # pgvector stores atttypmod = dim + 4
                        info["vector_dim"] = max(1, typmod - 4)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"DB stats failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)
    if _pool is not None:
        try:
            with _pool_lock:
                used = getattr(_pool, "_used", None)
                if isinstance(used, dict):
                    info["pool"]["active"] = len(used)
                elif isinstance(used, int):
                    info["pool"]["active"] = used
                else:
                    info["pool"]["active"] = 0
        except Exception as e:
            logger.warning(f"Pool stats failed: {e}")
    return info


def prune_memories(max_age_days: int = 30):
    conn = _get_conn()
    if not conn:
        return 0
    deleted = 0
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM agent_memory WHERE created_at < NOW() - make_interval(days => %s)", (max_age_days,))
            deleted = cur.rowcount
            conn.commit()
            if deleted:
                logger.info(f"Pruned {deleted} old memories")
            _invalidate_cache()
    except Exception as e:
        logger.warning(f"Prune failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _put_conn(conn)
    return deleted


def _invalidate_cache():
    with _cache_lock:
        _query_cache.clear()
        _query_cache_time.clear()


def start_auto_prune(interval_hours: Optional[int] = None, max_age_days: Optional[int] = None) -> Optional[threading.Thread]:
    global _prune_thread
    interval = interval_hours or CONFIG.prune_interval_hours
    max_age = max_age_days or CONFIG.prune_max_age_days
    with _prune_thread_lock:
        if _prune_thread is not None and _prune_thread.is_alive():
            return _prune_thread
        _prune_stop.clear()
        _prune_thread = threading.Thread(
            target=_prune_loop, args=(interval, max_age), daemon=True, name="auto-prune"
        )
        _prune_thread.start()
        logger.info(f"Auto-prune scheduled every {interval}h (max age {max_age}d)")
        return _prune_thread


def _prune_loop(interval_hours: int, max_age_days: int):
    while not _prune_stop.is_set():
        _prune_stop.wait(timeout=interval_hours * 3600)
        if _prune_stop.is_set():
            break
        try:
            if CONFIG.db.enabled:
                logger.info("Auto-prune: running")
                prune_memories(max_age_days)
        except Exception as e:
            logger.warning(f"Auto-prune failed: {e}")


def stop_auto_prune():
    _prune_stop.set()
    with _prune_thread_lock:
        if _prune_thread and _prune_thread.is_alive():
            _prune_thread.join(timeout=5)


def get_connection():
    return _get_conn()


def put_connection(conn):
    _put_conn(conn)


def close():
    global _pool, _pool_down, _reconnect_thread
    stop_auto_prune()
    _reconnect_stop.set()
    with _reconnect_lock:
        if _reconnect_thread and _reconnect_thread.is_alive():
            _reconnect_thread.join(timeout=5)
        _reconnect_thread = None
    with _pool_lock:
        if _pool:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None
    _pool_down = False
    _invalidate_cache()


# ---------- Workspaces (PostgreSQL tables; in-memory fallback when DB is off) ----------

_FALLBACK_WORKSPACES: Dict[str, Dict[str, Any]] = {}
_FALLBACK_FILES: Dict[str, Dict[str, Dict[str, Any]]] = {}
_FALLBACK_LOCK = Lock()

_DEFAULT_WS: Dict[str, Any] = {
    "id": "default",
    "name": "Default",
    "description": "Default workspace",
    "system_prompt": "",
    "default_model": "",
    "created_at": None,
}


def _ws_agent_name(workspace_id: str) -> str:
    return f"workspace:{workspace_id}"


def _seed_default_workspace(conn):
    """Make sure the built-in 'default' workspace exists (PG only)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspaces (id, name, description, system_prompt, default_model) "
                "VALUES ('default', 'Default', 'Default workspace', '', '') ON CONFLICT (id) DO NOTHING"
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"Seed default workspace: {e}")
        try:
            conn.rollback()
        except Exception:
            pass


def list_workspaces() -> List[Dict[str, Any]]:
    conn = _get_conn()
    if not conn:
        with _FALLBACK_LOCK:
            out = [dict(_DEFAULT_WS)]
            for ws in _FALLBACK_WORKSPACES.values():
                item = dict(ws)
                item["file_count"] = len(_FALLBACK_FILES.get(item["id"], {}))
                out.append(item)
            out.sort(key=lambda w: w.get("name") or "")
            return out
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT w.id, w.name, w.description, w.system_prompt, w.default_model, w.created_at, "
                "(SELECT COUNT(*) FROM workspace_files f WHERE f.workspace_id = w.id) AS file_count "
                "FROM workspaces w ORDER BY w.name"
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "name": r[1], "description": r[2] or "",
                "system_prompt": r[3] or "", "default_model": r[4] or "",
                "created_at": r[5].isoformat() if r[5] else None,
                "file_count": r[6] or 0,
            })
        return out
    except Exception as e:
        logger.warning(f"List workspaces: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return [dict(_DEFAULT_WS)]
    finally:
        _put_conn(conn)


def get_workspace(workspace_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    if not conn:
        with _FALLBACK_LOCK:
            if workspace_id == "default":
                return dict(_DEFAULT_WS)
            ws = _FALLBACK_WORKSPACES.get(workspace_id)
            return dict(ws) if ws else None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, description, system_prompt, default_model, created_at "
                "FROM workspaces WHERE id = %s", (workspace_id,)
            )
            r = cur.fetchone()
        if not r:
            return None
        return {
            "id": r[0], "name": r[1], "description": r[2] or "",
            "system_prompt": r[3] or "", "default_model": r[4] or "",
            "created_at": r[5].isoformat() if r[5] else None,
        }
    except Exception as e:
        logger.warning(f"Get workspace: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        _put_conn(conn)


def create_workspace(workspace_id: str, name: str, description: str = "",
                     system_prompt: str = "", default_model: str = "") -> Dict[str, Any]:
    workspace_id = workspace_id.strip() or "default"
    name = (name or workspace_id).strip()
    conn = _get_conn()
    if not conn:
        with _FALLBACK_LOCK:
            ws = {
                "id": workspace_id, "name": name, "description": description or "",
                "system_prompt": system_prompt or "", "default_model": default_model or "",
                "created_at": time.time(),
            }
            _FALLBACK_WORKSPACES[workspace_id] = ws
            _FALLBACK_FILES.setdefault(workspace_id, {})
            return dict(ws)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspaces (id, name, description, system_prompt, default_model) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING created_at",
                (workspace_id, name, description or "", system_prompt or "", default_model or ""),
            )
            created = cur.fetchone()[0]
            conn.commit()
            _invalidate_cache()
        return {
            "id": workspace_id, "name": name, "description": description or "",
            "system_prompt": system_prompt or "", "default_model": default_model or "",
            "created_at": created.isoformat() if created else None,
        }
    except Exception as e:
        logger.warning(f"Create workspace: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        _put_conn(conn)


def update_workspace(workspace_id: str, **fields) -> Optional[Dict[str, Any]]:
    allowed = {"name", "description", "system_prompt", "default_model"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_workspace(workspace_id)
    conn = _get_conn()
    if not conn:
        with _FALLBACK_LOCK:
            ws = _FALLBACK_WORKSPACES.get(workspace_id)
            if ws is None:
                return None
            ws.update({k: str(v) if v is not None else "" for k, v in updates.items()})
            ws["created_at"] = ws.get("created_at") or time.time()
            return dict(ws)
    try:
        sets = ", ".join(f"{k} = %s" for k in updates)
        vals = [str(v) if v is not None else "" for v in updates.values()]
        vals.append(workspace_id)
        with conn.cursor() as cur:
            cur.execute(f"UPDATE workspaces SET {sets} WHERE id = %s RETURNING id", vals)  # nosec B608
            updated = cur.fetchone() is not None
            conn.commit()
            if updated:
                _invalidate_cache()
        return get_workspace(workspace_id) if updated else None
    except Exception as e:
        logger.warning(f"Update workspace: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def delete_workspace(workspace_id: str) -> bool:
    if workspace_id == "default":
        return False
    conn = _get_conn()
    if not conn:
        with _FALLBACK_LOCK:
            removed = _FALLBACK_WORKSPACES.pop(workspace_id, None) is not None
            _FALLBACK_FILES.pop(workspace_id, None)
            return removed
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM workspace_files WHERE workspace_id = %s", (workspace_id,))
            cur.execute("DELETE FROM agent_memory WHERE agent_name = %s", (_ws_agent_name(workspace_id),))
            cur.execute("DELETE FROM workspaces WHERE id = %s", (workspace_id,))
            deleted = cur.rowcount
            conn.commit()
            if deleted:
                _invalidate_cache()
            return deleted > 0
    except Exception as e:
        logger.warning(f"Delete workspace: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def list_workspace_files(workspace_id: str) -> List[Dict[str, Any]]:
    conn = _get_conn()
    if not conn:
        with _FALLBACK_LOCK:
            files = _FALLBACK_FILES.get(workspace_id, {})
            out = []
            for f in files.values():
                item = dict(f)
                item["created_at"] = f.get("created_at")
                out.append(item)
            out.sort(key=lambda x: (x.get("created_at") or 0), reverse=True)
            return out
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, size, chunk_count, created_at FROM workspace_files "
                "WHERE workspace_id = %s ORDER BY created_at DESC", (workspace_id,)
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "name": r[1], "size": r[2] or 0, "chunk_count": r[3] or 0,
                "created_at": r[4].isoformat() if r[4] else None,
            })
        return out
    except Exception as e:
        logger.warning(f"List workspace files: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return []
    finally:
        _put_conn(conn)


def store_workspace_file(workspace_id: str, name: str, size: int, chunk_count: int) -> Dict[str, Any]:
    import uuid as _uuid
    file_id = f"file-{_uuid.uuid4().hex[:12]}"
    conn = _get_conn()
    if not conn:
        with _FALLBACK_LOCK:
            f = {"id": file_id, "name": name, "size": size, "chunk_count": chunk_count,
                 "created_at": time.time()}
            existing = _FALLBACK_FILES.get(workspace_id, {}).get(name, {})
            if existing.get("chunks"):
                f["chunks"] = existing["chunks"]
            _FALLBACK_FILES.setdefault(workspace_id, {})[name] = f
            return dict(f)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workspace_files (id, workspace_id, name, size, chunk_count) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING created_at",
                (file_id, workspace_id, name, size, chunk_count),
            )
            created = cur.fetchone()[0]
            conn.commit()
            _invalidate_cache()
        return {"id": file_id, "name": name, "size": size, "chunk_count": chunk_count,
                "created_at": created.isoformat() if created else None}
    except Exception as e:
        logger.warning(f"Store workspace file: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        _put_conn(conn)


def delete_workspace_file(workspace_id: str, name: str) -> bool:
    conn = _get_conn()
    if not conn:
        with _FALLBACK_LOCK:
            files = _FALLBACK_FILES.get(workspace_id, {})
            removed = files.pop(name, None) is not None
            return removed
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM workspace_files WHERE workspace_id = %s AND name = %s",
                (workspace_id, name),
            )
            deleted = cur.rowcount
            conn.commit()
            if deleted:
                _invalidate_cache()
            return deleted > 0
    except Exception as e:
        logger.warning(f"Delete workspace file: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        _put_conn(conn)


def chunk_text(text: str, size: int = 600, overlap: int = 120) -> List[str]:
    """Split a document into overlapping chunks on paragraph/line boundaries."""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks = []
    blocks = [b for b in text.split("\n\n") if b.strip()]
    if not blocks:
        blocks = text.split("\n")
    current = ""
    for b in blocks:
        if len(current) + len(b) + 2 <= size:
            current = (current + "\n\n" + b) if current else b
        else:
            if current:
                chunks.append(current)
            if len(b) > size:
                parts = [b[i:i + size] for i in range(0, len(b), max(1, size - overlap))]
                chunks.extend(parts)
                current = ""
            else:
                current = b
    if current:
        chunks.append(current)
    return chunks


def store_file_chunks(workspace_id: str, name: str, chunks: List[str]) -> int:
    """Embed + store document chunks as pgvector memories scoped to the workspace.

    Chunks are stored under agent 'workspace:<id>' with metadata marking the
    source file. Returns how many chunks were stored (0 when DB/embedder off).
    """
    if not chunks or not workspace_id:
        return 0
    if not get_pool():
        with _FALLBACK_LOCK:
            _FALLBACK_FILES.setdefault(workspace_id, {}).setdefault(name, {})["chunks"] = list(chunks)
        return 0
    embedder = get_embedder()
    if not embedder:
        with _FALLBACK_LOCK:
            _FALLBACK_FILES.setdefault(workspace_id, {}).setdefault(name, {})["chunks"] = list(chunks)
        return 0
    try:
        entries = []
        for i, chunk in enumerate(chunks):
            entries.append({
                "agent": _ws_agent_name(workspace_id),
                "thought": chunk,
                "metadata": {"kind": "file", "file": name, "chunk": i, "workspace_id": workspace_id},
            })
        store_batch(entries)
        return len(entries)
    except Exception as e:
        logger.warning(f"Store file chunks: {e}")
        return 0


def search_workspace_knowledge(workspace_id: str, query: str, limit: int = 5,
                               min_score: float = 0.0) -> List[Dict[str, Any]]:
    return search_memories(query, limit=limit, agent=_ws_agent_name(workspace_id), min_score=min_score)


def get_file_content(workspace_id: str, name: str) -> Optional[str]:
    """Reconstruct file content from stored chunks in agent_memory."""
    agent = _ws_agent_name(workspace_id)
    conn = _get_conn()
    if not conn:
        with _FALLBACK_LOCK:
            chunks = _FALLBACK_FILES.get(workspace_id, {}).get(name, {}).get("chunks")
        if chunks:
            return "\n".join(chunks)
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT metadata->>'chunk', thought FROM agent_memory "
                "WHERE agent_name = %s AND metadata->>'file' = %s "
                "ORDER BY (metadata->>'chunk')::int",
                (agent, name),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        return "\n".join(row[1] for row in rows)
    except Exception:
        return None
    finally:
        _put_conn(conn)


def reset_workspace_store():
    """Clear in-memory workspace fallback (test helper)."""
    with _FALLBACK_LOCK:
        _FALLBACK_WORKSPACES.clear()
        _FALLBACK_FILES.clear()
