"""Graph-augmented vector store (Yggdrasil-like memory engine).

Unifies the pgvector memory (``agent_memory``) and the Obsidian-style
knowledge graph (``wiki_links``) into three tables on PostgreSQL:

- ``nodes``  – every entity (document, conversation, memory, concept, tag)
              with an optional ``vector(384)`` embedding.
- ``edges``  – wiki-links, backlinks, parent/child branches and tag links.
- ``tags``   – first-class tag nodes, linked to content via ``tagged`` edges.

Queries are hybrid: vector similarity first, then graph traversal
(linked/backlinked nodes, degrees) and recursive-CTE pathfinding between two
nodes. All access goes through ``database``'s connection pool and embedder, so
every function degrades gracefully (returns empty/None) when PostgreSQL or the
embedding model is unavailable.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import database as db

logger = logging.getLogger(__name__)

_NODE_TYPES = ("document", "conversation", "memory", "concept", "tag")
_EMBED_DIM = 384
_SCHEMA_ENSURE_LOCK = None  # replaced by threading.Lock at import time

try:
    import threading

    _SCHEMA_ENSURE_LOCK = threading.Lock()
except Exception:  # pragma: no cover
    pass

_SCHEMA_DONE = threading.Event()

_NODES_INDEX_MIN_ROWS = 2000
_nodes_index_lock = threading.Lock()
_nodes_index_ts = 0.0


def _ensure_nodes_index(conn):
    """Adaptively create/drop the nodes IVFFlat index based on row count.

    pgvector IVFFlat (lists=100) returns zero matches on small tables, so the
    index is only present once the nodes table is large enough to benefit.
    Throttled so it runs at most once per 60s window.
    """
    global _nodes_index_ts
    now = time.time()
    with _nodes_index_lock:
        if now - _nodes_index_ts < 60.0:
            return
        _nodes_index_ts = now
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM nodes")
            count = int(cur.fetchone()[0] or 0)
            cur.execute("SELECT COUNT(*) FROM pg_class WHERE relname = 'idx_nodes_embedding'")
            exists = (cur.fetchone() or (0,))[0] > 0
            if count >= _NODES_INDEX_MIN_ROWS and not exists:
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_nodes_embedding
                    ON nodes USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                """)
                logger.info(f"Created nodes IVFFlat index ({count} rows)")
            elif count < _NODES_INDEX_MIN_ROWS and exists:
                cur.execute("DROP INDEX IF EXISTS idx_nodes_embedding")
                logger.info(f"Dropped nodes IVFFlat index (only {count} rows)")
            conn.commit()
    except Exception as e:
        logger.info(f"Nodes index maintenance deferred: {e}")


def _vec(value: Optional[Any]) -> Optional[str]:
    """Convert a raw embedding (list/vec) to a pgvector string literal."""
    if value is None:
        return None
    if hasattr(value, "tolist"):
        value = value.tolist()
    return str(list(value))


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

def ensure_schema(conn=None):
    """Create the nodes/edges/tags tables and their indexes if missing.

    Accepts an optional existing connection so the caller can reuse its own
    transaction (avoids grabbing a second pooled connection). When ``conn`` is
    None the module acquires one from the pool.
    """
    if _SCHEMA_DONE.is_set():
        return
    if _SCHEMA_ENSURE_LOCK is None:
        return
    with _SCHEMA_ENSURE_LOCK:
        if _SCHEMA_DONE.is_set():
            return
        owns = conn is None
        if owns:
            conn = db.get_connection()
        if not conn:
            return
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM pg_class WHERE relname = 'nodes'")
                if (cur.fetchone() or (0,))[0] == 0:
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS nodes (
                            id BIGSERIAL PRIMARY KEY,
                            node_type TEXT NOT NULL,
                            title TEXT NOT NULL,
                            content TEXT,
                            embedding vector({_EMBED_DIM}),
                            metadata JSONB DEFAULT '{{}}'::jsonb,
                            workspace_id TEXT DEFAULT 'default',
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        )
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes (node_type)
                    """)
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_nodes_title ON nodes (title)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_nodes_workspace ON nodes (workspace_id)")
                cur.execute("SELECT COUNT(*) FROM pg_class WHERE relname = 'edges'")
                if (cur.fetchone() or (0,))[0] == 0:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS edges (
                            id BIGSERIAL PRIMARY KEY,
                            source_id BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                            target_id BIGINT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                            edge_type TEXT NOT NULL,
                            weight FLOAT DEFAULT 1.0,
                            created_at TIMESTAMPTZ DEFAULT NOW(),
                            UNIQUE (source_id, target_id, edge_type)
                        )
                    """)
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges (source_id)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges (target_id)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_type ON edges (edge_type)")
                cur.execute("SELECT COUNT(*) FROM pg_class WHERE relname = 'tags'")
                if (cur.fetchone() or (0,))[0] == 0:
                    cur.execute(f"""
                        CREATE TABLE IF NOT EXISTS tags (
                            id BIGSERIAL PRIMARY KEY,
                            name TEXT UNIQUE NOT NULL,
                            embedding vector({_EMBED_DIM}),
                            metadata JSONB DEFAULT '{{}}'::jsonb
                        )
                    """)
            conn.commit()
            _ensure_nodes_index(conn)
            _SCHEMA_DONE.set()
            logger.info("Graph schema ready (nodes/edges/tags)")
        except Exception as e:
            logger.warning(f"Graph schema setup failed: {e}")
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            if owns:
                db.put_connection(conn)


# --------------------------------------------------------------------------
# Node CRUD
# --------------------------------------------------------------------------

def create_node(
    node_type: str,
    title: str,
    content: str = "",
    metadata: Optional[dict] = None,
    workspace_id: str = "default",
    embed: bool = True,
) -> Optional[int]:
    """Insert a node (auto-embedding its title+content) and return its id."""
    node_type = node_type if node_type in _NODE_TYPES else "concept"
    title = (title or "").strip()
    if not title:
        return None
    conn = db.get_connection()
    if not conn:
        return None
    embedder = db.get_embedder() if embed else None
    vec = None
    if embedder is not None:
        try:
            vec = _vec(embedder.encode(f"{title}\n{content[:1000]}", normalize_embeddings=True))
        except Exception as e:
            logger.warning(f"Node embed failed: {e}")
    meta = json.dumps(metadata or {})
    try:
        with conn.cursor() as cur:
            if vec:
                cur.execute(
                    "INSERT INTO nodes (node_type, title, content, embedding, metadata, workspace_id) "
                    "VALUES (%s, %s, %s, %s::vector, %s::jsonb, %s) RETURNING id",
                    (node_type, title, content, vec, meta, workspace_id),
                )
            else:
                cur.execute(
                    "INSERT INTO nodes (node_type, title, content, metadata, workspace_id) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s) RETURNING id",
                    (node_type, title, content, meta, workspace_id),
                )
            node_id = cur.fetchone()[0]
            conn.commit()
            return node_id
    except Exception as e:
        logger.warning(f"Create node failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        db.put_connection(conn)


def get_node(node_id: int) -> Optional[Dict[str, Any]]:
    conn = db.get_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, node_type, title, content, metadata, workspace_id, created_at "
                "FROM nodes WHERE id = %s",
                (node_id,),
            )
            r = cur.fetchone()
        if not r:
            return None
        meta = r[4] or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return {
            "id": r[0],
            "node_type": r[1],
            "title": r[2],
            "content": r[3],
            "metadata": meta,
            "workspace_id": r[5],
            "created_at": r[6].isoformat() if r[6] else None,
        }
    except Exception as e:
        logger.warning(f"Get node failed: {e}")
        return None
    finally:
        db.put_connection(conn)


def find_node_by_title(node_type: str, title: str,
                       workspace_id: str = "default") -> Optional[int]:
    conn = db.get_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM nodes WHERE node_type = %s AND title = %s AND workspace_id = %s "
                "ORDER BY id DESC LIMIT 1",
                (node_type, title, workspace_id),
            )
            r = cur.fetchone()
        return r[0] if r else None
    except Exception as e:
        logger.warning(f"Find node failed: {e}")
        return None
    finally:
        db.put_connection(conn)


def upsert_node(
    node_type: str,
    title: str,
    content: str = "",
    metadata: Optional[dict] = None,
    workspace_id: str = "default",
    embed: bool = True,
) -> Optional[int]:
    """Create the node, or update content/metadata if the (type,title,ws) row exists."""
    existing = find_node_by_title(node_type, title, workspace_id)
    if existing is not None:
        update_node(existing, content=content, metadata=metadata)
        return existing
    return create_node(node_type, title, content, metadata, workspace_id, embed=embed)


def update_node(node_id: int, content: Optional[str] = None,
                metadata: Optional[dict] = None) -> bool:
    conn = db.get_connection()
    if not conn:
        return False
    sets = []
    vals: List[Any] = []
    if content is not None:
        sets.append("content = %s")
        vals.append(content)
    if metadata is not None:
        sets.append("metadata = %s::jsonb")
        vals.append(json.dumps(metadata))
    if not sets:
        return True
    try:
        with conn.cursor() as cur:
            if content is not None:
                embedder = db.get_embedder()
                if embedder is not None:
                    try:
                        vec = _vec(embedder.encode(f"{content[:1000]}", normalize_embeddings=True))
                    except Exception:
                        vec = None
                    if vec:
                        sets.append("embedding = %s::vector")
                        vals.append(vec)
            cur.execute(f"UPDATE nodes SET {' , '.join(sets)} WHERE id = %s", vals + [node_id])  # nosec B608
            ok = cur.rowcount > 0
            conn.commit()
            return ok
    except Exception as e:
        logger.warning(f"Update node failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        db.put_connection(conn)


def delete_node(node_id: int) -> bool:
    conn = db.get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM nodes WHERE id = %s", (node_id,))
            ok = cur.rowcount > 0
            conn.commit()
            return ok
    except Exception as e:
        logger.warning(f"Delete node failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        db.put_connection(conn)


# --------------------------------------------------------------------------
# Edges
# --------------------------------------------------------------------------

def add_edge(source_id: int, target_id: int, edge_type: str,
             weight: float = 1.0) -> bool:
    if not source_id or not target_id or source_id == target_id:
        return False
    conn = db.get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO edges (source_id, target_id, edge_type, weight) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (source_id, target_id, edge_type) DO NOTHING",
                (source_id, target_id, edge_type, float(weight)),
            )
            conn.commit()
            return True
    except Exception as e:
        logger.warning(f"Add edge failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        db.put_connection(conn)


def delete_edges_from(source_id: int, edge_types: Tuple[str, ...] = ()) -> int:
    """Delete all (or matching-type) outgoing edges from a node. Returns the
    number of rows removed. Used by sync_wiki_links so removed wiki-links/tags
    do not leave stale edges behind."""
    conn = db.get_connection()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            if edge_types:
                ph = ",".join(["%s"] * len(edge_types))
                cur.execute(
                    f"DELETE FROM edges WHERE source_id = %s AND edge_type IN ({ph})",  # nosec B608
                    (source_id,) + tuple(edge_types),
                )
            else:
                cur.execute("DELETE FROM edges WHERE source_id = %s", (source_id,))
            deleted = cur.rowcount
            conn.commit()
            return int(deleted or 0)
    except Exception as e:
        logger.warning(f"Delete edges failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        db.put_connection(conn)


def linked_nodes(node_id: int, edge_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Nodes reachable from ``node_id`` (outgoing edges)."""
    conn = db.get_connection()
    if not conn:
        return []
    sql = (
        "SELECT n.id, n.node_type, n.title, n.content, e.edge_type, e.weight "
        "FROM edges e JOIN nodes n ON n.id = e.target_id "
        "WHERE e.source_id = %s"
    )
    params: Tuple[Any, ...] = (node_id,)
    if edge_type:
        sql += " AND e.edge_type = %s"
        params += (edge_type,)
    sql += " ORDER BY e.weight DESC, n.title LIMIT 50"
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "node_type": r[1], "title": r[2],
                "content": (r[3] or "")[:200], "edge_type": r[4], "weight": r[5],
            })
        return out
    except Exception as e:
        logger.warning(f"Linked nodes failed: {e}")
        return []
    finally:
        db.put_connection(conn)


def backlinks(node_id: int, edge_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Nodes that link TO ``node_id`` (incoming edges)."""
    conn = db.get_connection()
    if not conn:
        return []
    sql = (
        "SELECT n.id, n.node_type, n.title, n.content, e.edge_type, e.weight "
        "FROM edges e JOIN nodes n ON n.id = e.source_id "
        "WHERE e.target_id = %s"
    )
    params: Tuple[Any, ...] = (node_id,)
    if edge_type:
        sql += " AND e.edge_type = %s"
        params += (edge_type,)
    sql += " ORDER BY e.weight DESC, n.title LIMIT 50"
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "node_type": r[1], "title": r[2],
                "content": (r[3] or "")[:200], "edge_type": r[4], "weight": r[5],
            })
        return out
    except Exception as e:
        logger.warning(f"Backlinks failed: {e}")
        return []
    finally:
        db.put_connection(conn)


def node_degrees(node_id: int) -> Dict[str, int]:
    conn = db.get_connection()
    if not conn:
        return {"in_degree": 0, "out_degree": 0}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM edges WHERE source_id = %s", (node_id,))
            out_deg = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM edges WHERE target_id = %s", (node_id,))
            in_deg = cur.fetchone()[0] or 0
        return {"in_degree": in_deg, "out_degree": out_deg}
    except Exception as e:
        logger.warning(f"Degrees failed: {e}")
        return {"in_degree": 0, "out_degree": 0}
    finally:
        db.put_connection(conn)


def remove_edges(source_id: Optional[int] = None, target_id: Optional[int] = None) -> int:
    conn = db.get_connection()
    if not conn:
        return 0
    clauses = []
    params: List[Any] = []
    if source_id is not None:
        clauses.append("source_id = %s")
        params.append(source_id)
    if target_id is not None:
        clauses.append("target_id = %s")
        params.append(target_id)
    if not clauses:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM edges WHERE {' OR '.join(clauses)}", params)  # nosec B608
            removed = cur.rowcount
            conn.commit()
            return removed
    except Exception as e:
        logger.warning(f"Remove edges failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        db.put_connection(conn)


# --------------------------------------------------------------------------
# Tags
# --------------------------------------------------------------------------

def ensure_tag(tag: str, metadata: Optional[dict] = None) -> Optional[int]:
    """Get-or-create a first-class tag node."""
    tag = (tag or "").strip().lstrip("#")
    if not tag:
        return None
    conn = db.get_connection()
    if not conn:
        return None
    meta = json.dumps(metadata or {})
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tags (name, metadata) VALUES (%s, %s::jsonb) "
                "ON CONFLICT (name) DO NOTHING RETURNING id",
                (tag, meta),
            )
            row = cur.fetchone()
            if row:
                conn.commit()
                return row[0]
            cur.execute("SELECT id FROM tags WHERE name = %s", (tag,))
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception as e:
        logger.warning(f"Ensure tag failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return None
    finally:
        db.put_connection(conn)


def _ensure_tag_node(tag: str) -> Optional[int]:
    """Get-or-create a graph node of type 'tag'.

    Edges.source_id/target_id have a FK to nodes(id); the separate `tags`
    table uses its own sequence, so a tag id must never be used as an edge
    endpoint. We materialise each tag as a real node and link that instead.
    """
    existing = find_node_by_title("tag", tag, "default")
    if existing is not None:
        return existing
    return create_node("tag", tag, content=f"# {tag}", metadata={"source": "tags_table"})


def tag_node(node_id: int, tag: str) -> bool:
    """Link a tag to a content node via a 'tagged' edge (tag = real node)."""
    tag_node_id = _ensure_tag_node(tag)
    if tag_node_id is None:
        return False
    return add_edge(tag_node_id, node_id, "tagged")


# --------------------------------------------------------------------------
# Search
# --------------------------------------------------------------------------

def _encode_query(query: str) -> Optional[str]:
    if not db.get_pool():
        return None
    embedder = db.get_embedder()
    if embedder is None:
        return None
    try:
        return _vec(embedder.encode(query, normalize_embeddings=True))
    except Exception as e:
        logger.warning(f"Query embed failed: {e}")
        return None


def search_nodes(query: str, limit: int = 10, node_type: Optional[str] = None,
                 workspace_id: Optional[str] = None,
                 min_score: float = 0.0) -> List[Dict[str, Any]]:
    """Vector similarity search over the nodes table."""
    limit = max(1, min(limit, 50))
    vec = _encode_query(query)
    if vec is None:
        return []
    conn = db.get_connection()
    if not conn:
        return []
    try:
        sql = ("SELECT id, node_type, title, content, "
               "(embedding <=> %s::vector) AS dist, workspace_id, metadata "
               "FROM nodes WHERE embedding IS NOT NULL")
        params: List[Any] = [vec]
        if node_type:
            sql += " AND node_type = %s"
            params.append(node_type)
        if workspace_id:
            sql += " AND workspace_id = %s"
            params.append(workspace_id)
        sql += " ORDER BY dist LIMIT %s"
        params.append(limit)
        with conn.cursor() as cur:
            try:
                from database import _force_seq_scan
                _force_seq_scan(cur)
            except Exception:
                pass
            cur.execute(sql, params)
            rows = cur.fetchall()
        out = []
        for r in rows:
            dist = r[4]
            if dist is not None and dist > (1.0 - min_score):
                continue
            meta = r[6] or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            out.append({
                "id": r[0], "node_type": r[1], "title": r[2],
                "content": (r[3] or "")[:400], "workspace_id": r[5],
                "similarity": round(max(0.0, 1.0 - dist), 4) if dist is not None else 0.0,
                "metadata": meta,
            })
        return out
    except Exception as e:
        logger.warning(f"Search nodes failed: {e}")
        return []
    finally:
        db.put_connection(conn)


def hybrid_search(query: str, limit: int = 5, workspace_id: Optional[str] = None,
                  expand: int = 3, min_score: float = 0.0) -> List[Dict[str, Any]]:
    """Vector candidates first, then attach their graph neighbours + degrees."""
    nodes = search_nodes(query, limit=limit, workspace_id=workspace_id, min_score=min_score)
    if not nodes:
        return []
    for n in nodes:
        deg = node_degrees(n["id"])
        n["in_degree"] = deg["in_degree"]
        n["out_degree"] = deg["out_degree"]
        links = linked_nodes(n["id"])[:expand]
        backs = backlinks(n["id"])[:expand]
        n["linked"] = [{"id": l["id"], "title": l["title"], "edge_type": l["edge_type"]} for l in links]
        n["backlinked"] = [{"id": b["id"], "title": b["title"], "edge_type": b["edge_type"]} for b in backs]
    return nodes


def list_nodes(limit: int = 50, node_type: Optional[str] = None,
               workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = db.get_connection()
    if not conn:
        return []
    sql = "SELECT id, node_type, title, content, workspace_id, created_at FROM nodes"
    conds = []
    params: List[Any] = []
    if node_type:
        conds.append("node_type = %s")
        params.append(node_type)
    if workspace_id:
        conds.append("workspace_id = %s")
        params.append(workspace_id)
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(max(1, min(limit, 500)))
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        out = []
        for r in rows:
            deg = node_degrees(r[0])
            out.append({
                "id": r[0], "node_type": r[1], "title": r[2],
                "content": (r[3] or "")[:200], "workspace_id": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
                "in_degree": deg["in_degree"], "out_degree": deg["out_degree"],
            })
        return out
    except Exception as e:
        logger.warning(f"List nodes failed: {e}")
        return []
    finally:
        db.put_connection(conn)


def list_edges(limit: int = 200) -> List[Dict[str, Any]]:
    conn = db.get_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT e.id, e.source_id, e.target_id, e.edge_type, e.weight, "
                "s.title AS source_title, t.title AS target_title "
                "FROM edges e JOIN nodes s ON s.id = e.source_id "
                "JOIN nodes t ON t.id = e.target_id "
                "ORDER BY e.id DESC LIMIT %s",
                (max(1, min(limit, 1000)),),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "source_id": r[1], "target_id": r[2],
                "edge_type": r[3], "weight": r[4],
                "source": r[5], "target": r[6],
            })
        return out
    except Exception as e:
        logger.warning(f"List edges failed: {e}")
        return []
    finally:
        db.put_connection(conn)


# --------------------------------------------------------------------------
# Pathfinding (A*-style shortest path between two nodes)
# --------------------------------------------------------------------------

def shortest_path(start_id: int, end_id: int, max_depth: int = 10) -> Dict[str, Any]:
    """Shortest path (fewest edges) from start to end via a recursive CTE.

    Returns ``{"found": True, "path": [node dicts], "depth": n}`` or a
    ``found: False`` result. Depth is capped to keep the query cheap.
    """
    if start_id == end_id:
        node = get_node(start_id)
        return {"found": True, "path": [node] if node else [], "depth": 0}
    conn = db.get_connection()
    if not conn:
        return {"found": False, "path": [], "depth": None}
    max_depth = max(1, min(max_depth, 15))
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH RECURSIVE walk AS (
                    SELECT source_id, target_id, 1 AS depth,
                           ARRAY[source_id, target_id] AS route
                    FROM edges
                    WHERE source_id = %s AND edge_type IN ('wikilink','backlink','parent','child','tagged')
                    UNION ALL
                    SELECT e.source_id, e.target_id, w.depth + 1,
                           w.route || e.target_id
                    FROM walk w
                    JOIN edges e ON e.source_id = w.target_id
                    WHERE NOT (e.target_id = ANY(w.route))
                      AND w.depth < %s
                )
                SELECT route, depth FROM walk
                WHERE target_id = %s
                ORDER BY depth
                LIMIT 1
                """,
                (start_id, max_depth, end_id),
            )
            row = cur.fetchone()
        if not row:
            return {"found": False, "path": [], "depth": None}
        route = list(row[0])
        path = []
        for nid in route:
            node = get_node(nid)
            if node:
                path.append(node)
        return {"found": True, "path": path, "depth": row[1]}
    except Exception as e:
        logger.warning(f"Shortest path failed: {e}")
        return {"found": False, "path": [], "depth": None}
    finally:
        db.put_connection(conn)


def path_between_titles(workspace_id: str, title_a: str, title_b: str,
                        node_type: str = "concept", max_depth: int = 10) -> Dict[str, Any]:
    """Resolve two titles to nodes, then compute the shortest path between them."""
    a_id = find_node_by_title(node_type, title_a, workspace_id)
    b_id = find_node_by_title(node_type, title_b, workspace_id)
    if a_id is None or b_id is None:
        return {"found": False, "path": [], "depth": None,
                "start": title_a, "end": title_b, "error": "one or both titles not found"}
    result = shortest_path(a_id, b_id, max_depth=max_depth)
    result["start"] = title_a
    result["end"] = title_b
    return result


# --------------------------------------------------------------------------
# wiki_links sync (in-memory graph -> nodes/edges tables)
# --------------------------------------------------------------------------

def sync_wiki_links(workspace_id: str) -> Dict[str, Any]:
    """Persist the in-memory KnowledgeGraph for a workspace into nodes/edges.

    Each document becomes a ``document`` node; every wiki-link target becomes
    (or is matched to) a ``concept`` node linked by a ``wikilink`` edge; every
    ``#tag`` becomes a ``tagged`` edge from the document to a tag node.
    """
    try:
        from wiki_links import knowledge_graph
    except Exception as e:
        logger.warning(f"wiki_links unavailable: {e}")
        return {"nodes": 0, "edges": 0, "error": str(e)}

    docs = knowledge_graph._docs.get(workspace_id, {})  # noqa: SLF001 (same module family)
    if not docs:
        return {"nodes": 0, "edges": 0, "synced": True, "reason": "no docs"}

    ensure_schema()
    doc_nodes = 0
    edge_count = 0
    for filename, doc in docs.items():
        content = doc.get("content", "")
        doc_id = upsert_node("document", filename, content,
                             metadata={"workspace_id": workspace_id},
                             workspace_id=workspace_id, embed=True)
        if doc_id:
            doc_nodes += 1
        else:
            continue

        # Idempotency: drop this document's previous wikilink/tagged edges so
        # removed [[links]] / #tags are not left dangling after re-sync.
        delete_edges_from(doc_id, ("wikilink", "tagged"))

        for target in doc.get("links", set()):
            # Prefer linking to an existing document node (the real file) before
            # materializing a duplicate concept node for the target name.
            target_id = find_node_by_title("document", target, workspace_id)
            if target_id is None:
                target_id = find_node_by_title("concept", target, workspace_id)
            if target_id is None:
                target_id = create_node("concept", target, "",
                                        metadata={"workspace_id": workspace_id, "from": filename},
                                        workspace_id=workspace_id, embed=True)
            if target_id and doc_id:
                if add_edge(doc_id, target_id, "wikilink"):
                    edge_count += 1
        for tag in doc.get("tags", set()):
            if tag_node(doc_id, tag):
                edge_count += 1
    _conn = db.get_connection()
    if _conn:
        try:
            _ensure_nodes_index(_conn)
        finally:
            db.put_connection(_conn)
    logger.info(f"Graph sync workspace={workspace_id}: {doc_nodes} docs, {edge_count} edges")
    return {"nodes": doc_nodes, "edges": edge_count, "synced": True}


def migrate_memory_to_nodes() -> Dict[str, Any]:
    """One-time migration: copy agent_memory rows into nodes (node_type='memory')."""
    conn = db.get_connection()
    if not conn:
        return {"migrated": 0, "error": "db unavailable"}
    migrated = 0
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO nodes (node_type, title, content, metadata, workspace_id) "
                "SELECT 'memory', LEFT(split_part(am.thought, E'\\n', 1), 80), am.thought, "
                "COALESCE(am.metadata, '{}'::jsonb) "
                "|| jsonb_build_object('agent', am.agent_name, 'legacy_id', am.id), 'default' "
                "FROM agent_memory am "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM nodes n "
                "  WHERE n.node_type = 'memory' AND n.workspace_id = 'default' "
                "  AND COALESCE(n.metadata->>'legacy_id', '') = am.id::text"
                ")"
            )
            migrated = cur.rowcount
            conn.commit()
        logger.info(f"Migrated {migrated} agent_memory rows into graph nodes")
        return {"migrated": migrated}
    except Exception as e:
        logger.warning(f"Memory->nodes migration failed: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return {"migrated": 0, "error": str(e)}
    finally:
        db.put_connection(conn)


def graph_stats() -> Dict[str, Any]:
    conn = db.get_connection()
    if not conn:
        return {"enabled": False, "nodes": 0, "edges": 0, "tags": 0,
                "node_types": {}, "avg_out_degree": 0.0}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM nodes")
            nodes = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM edges")
            edges = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM tags")
            tags = cur.fetchone()[0] or 0
            cur.execute("SELECT node_type, COUNT(*) FROM nodes GROUP BY node_type")
            types = {r[0]: r[1] for r in cur.fetchall()}
            cur.execute("SELECT COALESCE(AVG(degree), 0) FROM (SELECT COUNT(*) AS degree FROM edges GROUP BY source_id) d")
            avg_deg = float(cur.fetchone()[0] or 0.0)
        return {
            "enabled": True, "nodes": nodes, "edges": edges, "tags": tags,
            "node_types": types, "avg_out_degree": round(avg_deg, 2),
        }
    except Exception as e:
        logger.warning(f"Graph stats failed: {e}")
        return {"enabled": True, "error": str(e)}
    finally:
        db.put_connection(conn)


def list_tags() -> List[Dict[str, Any]]:
    conn = db.get_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, metadata FROM tags ORDER BY name")
            rows = cur.fetchall()
        return [{"id": r[0], "name": r[1], "metadata": r[2] or {}} for r in rows]
    except Exception:
        return []
    finally:
        db.put_connection(conn)


def recent_nodes(limit: int = 20) -> List[Dict[str, Any]]:
    return list_nodes(limit=limit)
