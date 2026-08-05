import sys
import os
import argparse
import threading
import webbrowser
import logging
import time
import subprocess


COMMON_PORTS = [8070, 8080, 8000, 8001, 8081, 8888, 9000, 3000]
_logger = logging.getLogger(__name__)


def _port_busy(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def resolve_port(preferred: int) -> int:
    """Return `preferred` if free, else the first free common port."""
    if not _port_busy(preferred):
        return preferred
    _logger.warning(f"Port {preferred} is already in use")
    for alt in COMMON_PORTS:
        if alt == preferred:
            continue
        if not _port_busy(alt):
            _logger.warning(f"Using free port {alt} instead")
            return alt
    _logger.warning(f"No free common port found; will try {preferred} (may fail)")
    return preferred


def kill_port(port):
    if sys.platform != "win32":
        return
    try:
        out = subprocess.check_output(["netstat", "-ano", "-p", "tcp"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    pids = set()
    for line in out.splitlines():
        if "LISTENING" not in line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        addr = parts[1]
        try:
            _, p = addr.rsplit(":", 1)
            if int(p) == port:
                pids.add(parts[-1])
        except ValueError:
            continue
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, text=True)
            _logger.info(f"Freed port {port} (killed PID {pid})")
        except Exception:
            pass


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)
os.environ["PYTHONIOENCODING"] = "utf-8"


def auto_detect_config():
    from config import CONFIG, HAS_GPU, MODELS_DIR, optimal_threads
    if not os.path.isdir(MODELS_DIR):
        os.makedirs(MODELS_DIR, exist_ok=True)
    if CONFIG.threads < 1:
        CONFIG.threads = optimal_threads()
    if CONFIG.auto_tune:
        try:
            import hardware
            hardware.auto_tune()
        except Exception as e:
            logger.warning(f"Auto-tune failed: {e}")
    else:
        CONFIG.sync_threads()
    if not CONFIG.db.enabled:
        try:
            import database as db
            db.enable_if_available()
        except Exception as e:
            logger.warning(f"Database auto-detect failed: {e}")
    configured = [m for m in CONFIG.models if os.path.exists(m.path)]
    discovered = [m for m in CONFIG.available_models if os.path.exists(m.path)]
    models_found = configured or discovered
    if not models_found:
        logger.warning("No GGUF model files found in models/ directory!")
        logger.warning(f"Expected path: {MODELS_DIR}/")
        logger.warning("Place .gguf files in the models/ folder (see config.py for expected names)")
    logger.info(f"Auto-config: GPU={'ON' if HAS_GPU else 'OFF'}  Threads={CONFIG.threads}  Models={len(models_found)}")


def print_banner(port, nextjs=False):
    from config import CONFIG, HAS_GPU
    gpu_status = f'ENABLED ({CONFIG.gpu_name})' if HAS_GPU else 'DISABLED'
    banner = f"""
  ====================================================
    RHASAN INDIE'S AGENTIC LLM  -  LOCAL MULTI-AGENT SYSTEM
  ====================================================
    GPU      : {gpu_status}
    Threads  : {CONFIG.threads}
    Models   : {len(CONFIG.available_models)} found
    Database : {'PostgreSQL + pgvector' if CONFIG.db.enabled else 'In-memory only'}
    OpenAI   : {'Enabled (cloud fallback)' if CONFIG.openai.enabled else 'Disabled'}

    Endpoints:
      Web UI  -> http://localhost:{port}
      Chat    -> http://localhost:{port}/v1/chat/completions
      Models  -> http://localhost:{port}/v1/models
      Memory  -> http://localhost:{port}/v1/memory/search
      Embed   -> http://localhost:{port}/v1/embeddings
      Health  -> http://localhost:{port}/v1/health
      MCP     -> http://localhost:{port}/mcp
"""
    if nextjs:
        banner += "      Next.js -> http://localhost:3001\n"
    banner += "  ====================================================\n"
    print(banner)


def start_server(host, port, quiet=False):
    from api import app
    from web_ui import create_web_app
    app = create_web_app(app)
    import uvicorn
    log_level = "error" if quiet else "info"
    import importlib.util
    has_httptools = importlib.util.find_spec("httptools") is not None
    if has_httptools:
        uvicorn.run(app, host=host, port=port, log_level=log_level, http="httptools")
    else:
        uvicorn.run(app, host=host, port=port, log_level=log_level)


def run_cli():
    from cli import main as cli_main
    cli_main()


def run_full(host, port, no_open, nextjs=False):
    print_banner(port, nextjs=nextjs)
    if not no_open:
        urls = [f"http://localhost:{port}"]
        if nextjs:
            urls.append("http://localhost:3001")
        for u in urls:
            threading.Timer(2.5, lambda url=u: webbrowser.open(url)).start()
    svr = threading.Thread(target=start_server, args=(host, port, True), daemon=True)
    svr.start()
    time.sleep(1.5)
    print("  [Server running in background. Type /help in CLI or open browser.]\n")
    run_cli()


def validate_config():
    from config import CONFIG
    warnings = []

    if not CONFIG.available_models and not CONFIG.cloud_provider:
        warnings.append("No local models found and no cloud provider configured")

    if CONFIG.threads < 1:
        warnings.append(f"Threads set to {CONFIG.threads}, will auto-tune")

    if CONFIG.gen_timeout_s < 10:
        warnings.append(f"Generation timeout very low ({CONFIG.gen_timeout_s}s), may cause premature kills")

    if CONFIG.parallel_max > len(CONFIG.available_models):
        warnings.append(f"parallel_max ({CONFIG.parallel_max}) exceeds available models ({len(CONFIG.available_models)})")

    if CONFIG.db.enabled:
        if not CONFIG.db.host or not CONFIG.db.user:
            warnings.append("DB enabled but host/user not configured")

    if warnings:
        print("\n  === Configuration Warnings ===")
        for w in warnings:
            print(f"  ⚠ {w}")
        print()


def first_run_wizard():
    from config import CONFIG, MODELS_DIR
    print("\n  === First Run Setup ===\n")
    models_dir = os.path.abspath(MODELS_DIR)
    print(f"  Models directory: {models_dir}")
    found = [f for f in os.listdir(MODELS_DIR) if f.endswith('.gguf')] if os.path.isdir(MODELS_DIR) else []
    if found:
        print(f"  Found {len(found)} model(s): {', '.join(found)}")
    else:
        print("  WARNING: No .gguf model files found!")
        print(f"  Place your GGUF models in: {models_dir}")
    print()
    ans = input("  Enable PostgreSQL memory? (y/N): ").strip().lower()
    if ans == 'y':
        CONFIG.db.enabled = True
        pw = input("  DB password (default: postgres): ").strip()
        if pw:
            CONFIG.db.password = pw
    ans = input("  Enable OpenAI fallback? (y/N): ").strip().lower()
    if ans == 'y':
        key = input("  API key: ").strip()
        if key:
            CONFIG.openai.api_key = key
            CONFIG.openai.enabled = True
    print("  Setup complete!\n")


def main():
    parser = argparse.ArgumentParser(
        description="Rhasan Indie's Agentic LLM - Multi-Agent with GPU, RAG, and Cloud Fallback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python run.py                    # Full mode: web + CLI\n"
            "  python run.py web                # Web UI only\n"
            "  python run.py cli                # Terminal CLI only\n"
            "  python run.py api                # API server only\n"
            "  python run.py --setup            # First-run config wizard\n"
            "  python run.py --port 8070        # Custom port\n"
            "  python run.py --db --db-password mypass  # With PostgreSQL\n"
            "  python run.py --openai-key sk-...        # With OpenAI\n"
        ),
    )
    parser.add_argument("mode", nargs="?", default="full",
                        choices=["full", "web", "cli", "api"],
                        help="Mode: full (web+CLI, default), web, cli, api")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")  # nosec B104
    parser.add_argument("--port", type=int, default=8070, help="Port number")
    parser.add_argument("--threads", type=int, default=0, help="CPU threads (0=auto-half)")
    parser.add_argument("--openai-key", help="OpenAI API key for cloud fallback")
    parser.add_argument("--openai-url", help="OpenAI-compatible base URL")
    parser.add_argument("--openai-model", help="OpenAI model name (default: gpt-4o-mini)")
    parser.add_argument("--api-token", help="Require Bearer token on /v1/* endpoints (comma-separated = rotation set; primary first)")
    parser.add_argument("--parallel", action="store_true", help="Enable parallel multi-model generation")
    parser.add_argument("--no-parallel", action="store_true", help="Disable parallel multi-model generation")
    parser.add_argument("--parallel-max", type=int, default=0, help="Max models to run in parallel (0=default 2)")
    parser.add_argument("--no-parallel-load", action="store_true", help="Disable concurrent model loading (load one model at a time)")
    parser.add_argument("--load-workers", type=int, default=0, help="Max models to load at once (0=default 2)")
    parser.add_argument("--cli-commands", default="", help="Comma-separated CLI slash-command whitelist (empty=all)")
    parser.add_argument("--auto-stream", action="store_true", help="Enable auto-agentic streaming (default: enabled)")
    parser.add_argument("--no-auto-stream", action="store_true", help="Disable auto-agentic streaming")
    parser.add_argument("--auto-stream-thinking", action="store_true", help="Stream thinking steps (default: enabled)")
    parser.add_argument("--no-auto-stream-thinking", action="store_true", help="Disable thinking streaming")
    parser.add_argument("--auto-stream-min-tokens", type=int, default=0, help="Minimum tokens before streaming starts")
    parser.add_argument("--auto-stream-max-tokens", type=int, default=0, help="Maximum tokens to stream")
    parser.add_argument("--prune-hours", type=int, default=0, help="Auto-prune interval in hours (0=default 6)")
    parser.add_argument("--prune-days", type=int, default=0, help="Auto-prune max age in days (0=default 30)")
    parser.add_argument("--sandbox", action="store_true", help="Sandbox mode: no DB writes, isolated conversations")
    parser.add_argument("--cloud", help="Cloud preset: openai|claude|groq|openrouter|gemini (set key with --openai-key)")
    parser.add_argument("--vram", type=int, default=0, help="VRAM budget in MB for model loading (0=auto-detect)")
    parser.add_argument("--gen-timeout", type=float, default=0, help="Generation timeout in seconds (0=default 240)")
    parser.add_argument("--no-auto-tune", action="store_true", help="Disable hardware auto-tune")
    parser.add_argument("--no-auto-load", action="store_true", help="Disable selection-room preloading")
    parser.add_argument("--add-model", help="Register an extra .gguf model at runtime (path to file)")
    parser.add_argument("--add-model-name", default="", help="Name for --add-model (default: filename)")
    parser.add_argument("--add-model-role", default="Executor", help="Role for --add-model (default: Executor)")
    parser.add_argument("--db", action="store_true", help="Enable PostgreSQL memory")
    parser.add_argument("--web-search", action="store_true", help="Enable DuckDuckGo web search for live queries")
    parser.add_argument("--db-password", default="postgres", help="Database password")
    parser.add_argument("--db-name", help="Database name (default: rhasan_indie_agentic_llm)")
    parser.add_argument("--db-user", help="Database user (default: postgres)")
    parser.add_argument("--db-host", help="Database host (default: localhost)")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")
    parser.add_argument("--force-port", action="store_true", help="Kill whatever is on the port instead of switching to a free one")
    parser.add_argument("--setup", action="store_true", help="Run first-time setup wizard")
    parser.add_argument("--quiet", action="store_true", help="Minimal logging")
    parser.add_argument("--nextjs", action="store_true", help="Start Next.js dev server on port 3001 alongside API")
    parser.add_argument("--image-gen", action="store_true",
                        help="Enable local image generation via diffusers (CPU, one at a time)")
    parser.add_argument("--vision", action="store_true",
                        help="Enable local image understanding via moondream2 (CPU, one at a time)")
    parser.add_argument("--vision-model", metavar="NAME",
                        help="Vision model id (default vikhyat/moondream2)")
    parser.add_argument("--automl", action="store_true",
                        help="Enable local AutoML (auto-sklearn) data-science agent (Linux-only, opt-in)")
    parser.add_argument("--automl-model-dir", metavar="DIR",
                        help="Directory to save trained AutoML models (default generated/automl_models)")
    parser.add_argument("--healing", action="store_true",
                        help="Enable the self-healing diagnostic agent (diagnoses + fixes Python code)")
    parser.add_argument("--allow-unsafe-healing", action="store_true",
                        help="PERMIT the healing agent to execute caller-supplied Python (RCE risk; local opt-in only)")

    args = parser.parse_args()
    from config import CONFIG

    if args.setup:
        first_run_wizard()
        ans = input("  Start the system now? (Y/n): ").strip().lower()
        if ans == 'n':
            print("  You can run 'python run.py' anytime.\n")
            return

    config_map = {
        "threads": "threads",
        "openai-key": "openai.api_key",
        "openai-url": "openai.base_url",
        "openai-model": "openai.chat_model",
        "db-password": "db.password",
        "db-name": "db.database",
        "db-user": "db.user",
        "db-host": "db.host",
    }
    for cli_arg, config_path in config_map.items():
        val = getattr(args, cli_arg.replace("-", "_"), None)
        if val:
            parts = config_path.split(".")
            obj = CONFIG
            for p in parts[:-1]:
                obj = getattr(obj, p)
            setattr(obj, parts[-1], val)

    if args.openai_key:
        CONFIG.openai.enabled = True
    if args.db:
        CONFIG.db.enabled = True
    if args.api_token:
        CONFIG.set_api_token(args.api_token)
    if args.parallel_max:
        CONFIG.parallel_max = max(1, args.parallel_max)
    if args.parallel:
        CONFIG.parallel_enabled = True
    if args.no_parallel:
        CONFIG.parallel_enabled = False
    if args.no_parallel_load:
        CONFIG.parallel_load = False
    if args.load_workers:
        CONFIG.load_workers = max(1, args.load_workers)
    if args.cli_commands:
        CONFIG.cli_command_whitelist = tuple(
            c.strip().lower() for c in args.cli_commands.split(",") if c.strip())
    if args.auto_stream:
        CONFIG.auto_stream_enabled = True
    if args.no_auto_stream:
        CONFIG.auto_stream_enabled = False
    if args.auto_stream_thinking:
        CONFIG.auto_stream_thinking = True
    if args.no_auto_stream_thinking:
        CONFIG.auto_stream_thinking = False
    if args.auto_stream_min_tokens:
        CONFIG.auto_stream_min_tokens = max(10, args.auto_stream_min_tokens)
    if args.auto_stream_max_tokens:
        CONFIG.auto_stream_max_tokens = min(8192, args.auto_stream_max_tokens)
    if args.gen_timeout:
        CONFIG.gen_timeout_s = max(5.0, args.gen_timeout)
    if args.prune_hours:
        CONFIG.prune_interval_hours = max(1, args.prune_hours)
    if args.prune_days:
        CONFIG.prune_max_age_days = max(1, args.prune_days)
    if args.sandbox:
        CONFIG.sandbox = True
    if args.cloud:
        from config import CLOUD_PRESETS
        preset = CLOUD_PRESETS.get(args.cloud.lower())
        if preset:
            CONFIG.openai.base_url = preset["base_url"]
            CONFIG.openai.chat_model = preset["chat_model"]
            CONFIG.cloud_provider = args.cloud.lower()
        else:
            logger.warning(f"Unknown cloud preset '{args.cloud}' (openai|groq|openrouter|gemini)")
    if args.vram:
        CONFIG.vram_budget_mb = max(256, args.vram)
    if args.image_gen:
        CONFIG.image_gen["enabled"] = True
        logger.info("Local image generation enabled (CPU, resource-safe)")
    if args.vision:
        CONFIG.vision["enabled"] = True
        logger.info("Local vision enabled (moondream2, CPU, resource-safe)")
    if args.vision_model:
        CONFIG.vision["model"] = args.vision_model
    if args.automl:
        CONFIG.automl["enabled"] = True
        logger.info("AutoML enabled (auto-sklearn, Linux-only, CPU, resource-safe)")
    if args.automl_model_dir:
        CONFIG.automl["model_dir"] = args.automl_model_dir
    if args.healing:
        CONFIG.healing["enabled"] = True
        logger.info("Self-healing diagnostic agent enabled")
    if args.allow_unsafe_healing:
        CONFIG.healing["allow_unsafe"] = True
        logger.warning("Healing agent MAY EXECUTE caller-supplied Python (--allow-unsafe-healing)")
    if args.web_search:
        CONFIG.web_search_enabled = True
        logger.info("Web search enabled (DuckDuckGo)")
    if args.add_model:
        if not os.path.exists(args.add_model):
            logger.warning(f"--add-model file not found: {args.add_model}")
        else:
            from config import ModelConfig
            name = args.add_model_name or os.path.splitext(os.path.basename(args.add_model))[0].lower()
            name = name.replace(" ", "-").replace("_", "-")
            if any(m.path == os.path.abspath(args.add_model) for m in CONFIG.models):
                logger.info(f"Model already registered: {name}")
            else:
                mc = ModelConfig(path=args.add_model, name=name, role=args.add_model_role,
                                 n_gpu_layers=-1, n_ctx=4096, capabilities=["general"])
                CONFIG.models.append(mc)
                CONFIG.sync_threads()
                logger.info(f"Registered extra model: {name} ({args.add_model_role})")
    if args.no_auto_tune:
        CONFIG.auto_tune = False
    if args.no_auto_load:
        CONFIG.auto_load = False
    if args.threads:
        CONFIG.sync_threads()
    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    auto_detect_config()
    validate_config()

    nextjs_proc = None
    if args.nextjs:
        frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
        if os.path.isdir(frontend_dir) and os.path.isfile(os.path.join(frontend_dir, "package.json")):
            try:
                npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
                env = os.environ.copy()
                env["NEXT_PUBLIC_API_BASE"] = f"http://localhost:{args.port}"
                nextjs_proc = subprocess.Popen(
                    [npm_cmd, "run", "dev", "--", "-p", "3001"],
                    cwd=frontend_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                    env=env,
                )
                logger.info("Next.js dev server starting on http://localhost:3001")
                time.sleep(3)
            except Exception as e:
                logger.warning(f"Next.js dev server failed to start: {e}")
        else:
            logger.warning("Next.js frontend not found in ./frontend/")

    if args.force_port:
        kill_port(args.port)
        time.sleep(1)
    else:
        args.port = resolve_port(args.port)
        CONFIG.port = args.port

    if CONFIG.db.enabled:
        try:
            import database as db
            db.start_auto_prune()
        except Exception as e:
            logger.warning(f"Auto-prune start failed: {e}")

    if args.mode == "cli":
        run_cli()
        if nextjs_proc:
            try:
                nextjs_proc.terminate()
            except Exception:
                pass
        return

    if args.mode == "full":
        run_full(args.host, args.port, args.no_open, nextjs=args.nextjs)
        if nextjs_proc:
            try:
                nextjs_proc.terminate()
            except Exception:
                pass
        return

    print_banner(args.port, nextjs=args.nextjs)
    if args.mode == "web" and not args.no_open:
        urls = [f"http://localhost:{args.port}"]
        if args.nextjs:
            urls.append("http://localhost:3001")
        for u in urls:
            threading.Timer(2.0, lambda url=u: webbrowser.open(url)).start()

    try:
        start_server(args.host, args.port)
    finally:
        if nextjs_proc:
            try:
                nextjs_proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()


# --- Entry point wrappers for pipx/installed CLI ---

def main_web():
    """Entry point for `sovereign-llm-web` -> starts the web UI + API."""
    import sys
    sys.argv = [sys.argv[0], "web"] + sys.argv[1:]
    return main()


def main_cli():
    """Entry point for `sovereign-llm-cli` -> starts the terminal CLI."""
    import sys
    sys.argv = [sys.argv[0], "cli"] + sys.argv[1:]
    return main()


def main_api():
    """Entry point for `sovereign-llm-api` -> starts the API server only."""
    import sys
    sys.argv = [sys.argv[0], "api"] + sys.argv[1:]
    return main()
