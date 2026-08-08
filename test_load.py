"""test_load.py - Balance / load / stress test for the Local LLM platform.

Hammers the running API with concurrent requests across all endpoint families,
reports throughput, latency percentiles and error rates, and exits non-zero if
the error rate exceeds the threshold.

Usage:
    python run.py api --no-open &          # start the server first
    python test_load.py                    # quick check against :8070
    python test_load.py --port 8080 --concurrency 16 --requests 500
    python test_load.py --chat --chat-count 5   # include real model generation

Flags:
    --port PORT        Server port (default 8070)
    --url URL          Full base URL override (default http://127.0.0.1:PORT)
    --concurrency N    Worker threads (default 8)
    --requests N       Total cheap API requests (default 120)
    --chat             Also run real chat completions (loads models)
    --chat-count N     Number of chat requests (default 3)
    --timeout S        Per-request timeout in seconds (default 30)
    --error-limit P    Fail when error rate % exceeds P (default 5.0)
    --quiet            Less verbose output
"""
import argparse, json, os, random, sys, threading, time, urllib.request, urllib.error

CHEAP_ENDPOINTS = [
    ("health", "GET", "/v1/health", None),
    ("system", "GET", "/v1/system", None),
    ("models", "GET", "/v1/models", None),
    ("metrics", "GET", "/v1/metrics", None),
    ("router", "GET", "/v1/router/stats", None),
    ("hardware", "GET", "/v1/hardware", None),
    ("config", "GET", "/v1/config", None),
    ("conversations", "GET", "/v1/chat/conversations", None),
    ("memory", "GET", "/v1/memory/stats", None),
    ("models_stats", "GET", "/v1/models/stats", None),
]

_results_lock = threading.Lock()
_results: dict = {}


def _request(base, method, path, body=None, timeout=30):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    start = time.time()
    status = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            resp.read()
        status = resp.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception:
        pass
    return status, time.time() - start


def _record(name, ok, latency, status):
    with _results_lock:
        d = _results.setdefault(name, {"ok": 0, "err": 0, "lat": []})
        d["ok" if ok else "err"] += 1
        d["lat"].append(latency)
        if not ok:
            d.setdefault("statuses", []).append(status)


def _hit(base, endpoint, timeout):
    name, method, path, body = endpoint
    try:
        status, latency = _request(base, method, path, body, timeout)
        ok = 200 <= status < 300
        _record(name, ok, latency, status)
        return ok
    except Exception as e:
        _record(name, False, timeout, str(e))
        return False


def _percentile(vals, p):
    if not vals:
        return 0.0
    vals = sorted(vals)
    idx = min(len(vals) - 1, int(len(vals) * p))
    return round(vals[idx] * 1000, 1)


def _chat_hit(base, prompt, timeout):
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "use_planning": False,
        "parallel": False,
    }
    try:
        status, latency = _request(base, "POST", "/v1/chat/completions", body, timeout)
        ok = 200 <= status < 300
        _record("chat", ok, latency, status)
        return ok
    except Exception as e:
        _record("chat", False, timeout, str(e))
        return False


def main():
    ap = argparse.ArgumentParser(description="Load/balance test for the Local LLM platform")
    ap.add_argument("--port", type=int, default=8070)
    ap.add_argument("--url", default=None)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--requests", type=int, default=120)
    ap.add_argument("--chat", action="store_true")
    ap.add_argument("--chat-count", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--error-limit", type=float, default=5.0)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--health-check", action="store_true", help="Single health check then exit")
    args = ap.parse_args()

    base = args.url or f"http://127.0.0.1:{args.port}"
    name = "load test"

    try:
        status, latency = _request(base, "GET", "/v1/health", timeout=10)
    except Exception as e:
        print(f"[{name}] FAIL - no server at {base}: {e}")
        print(f"[{name}] Start it with: python run.py api --no-open")
        return 2
    if status != 200:
        print(f"[{name}] FAIL - /v1/health returned {status}")
        return 2
    print(f"[{name}] Server reachable at {base} (health OK in {latency*1000:.0f} ms)")

    if args.health_check:
        return 0

    import concurrent.futures as cf

    total = args.requests
    pool = cf.ThreadPoolExecutor(max_workers=args.concurrency)
    prompts = [
        "Reply with one word only: hello",
        "What is 2 + 2? Reply with a number only.",
        "Translate 'good morning' to French.",
        "Name one programming language.",
        "Reply 'ok'.",
    ]
    endpoints = CHEAP_ENDPOINTS
    work = [random.choice(endpoints) for _ in range(total)]  # nosec B311

    results = {"ok": 0, "err": 0}
    stats_lock = threading.Lock()

    def task(ep):
        ok = _hit(base, ep, args.timeout)
        with stats_lock:
            results["ok" if ok else "err"] += 1

    start = time.time()
    if not args.quiet:
        print(f"[{name}] Running {total} API requests with {args.concurrency} workers...")
    futs = [pool.submit(task, ep) for ep in work]
    done = 0
    for f in cf.as_completed(futs):
        f.result()
        done += 1
        if not args.quiet and done % 50 == 0:
            print(f"[{name}] ...{done}/{total}")
    elapsed = time.time() - start
    pool.shutdown(wait=True)

    if args.chat:
        if not args.quiet:
            print(f"[{name}] Running {args.chat_count} real chat generations (loads models, be patient)...")
        pool = cf.ThreadPoolExecutor(max_workers=min(2, args.chat_count))
        chat_futs = [
            pool.submit(_chat_hit, base, random.choice(prompts), args.timeout + 60)  # nosec B311
            for _ in range(args.chat_count)
        ]
        for f in cf.as_completed(chat_futs):
            f.result()
        pool.shutdown(wait=True)

    print(f"\n[{name}] ======== SUMMARY ========")
    total_reqs = sum(results.values())
    err_rate = (results["err"] / total_reqs * 100) if total_reqs else 0.0
    print(f"[{name}] Requests: {total_reqs}   OK: {results['ok']}   Errors: {results['err']}"
          f"   Error rate: {err_rate:.2f}%")
    if total_reqs:
        print(f"[{name}] Throughput: {total_reqs / elapsed:.1f} req/s   Total time: {elapsed:.1f}s")

    print(f"\n[{name}] -------- per endpoint --------")
    for ep_name in [e[0] for e in CHEAP_ENDPOINTS] + (["chat"] if args.chat else []):
        d = _results.get(ep_name)
        if not d:
            continue
        n = d["ok"] + d["err"]
        rate = d["err"] / n * 100 if n else 0
        lat = d["lat"]
        print(f"[{name}] {ep_name:16s} n={n:4d} err={rate:6.2f}% "
              f"min={_percentile(lat, 0.0):7.1f}ms avg={_percentile(lat, 0.5):7.1f}ms "
              f"p95={_percentile(lat, 0.95):7.1f}ms p99={_percentile(lat, 0.99):7.1f}ms")

    if args.chat and "chat" in _results:
        d = _results["chat"]
        print(f"[{name}] chat: {d['ok']}/{d['ok'] + d['err']} succeeded")

    # Overall verdict
    threshold_ok = err_rate <= args.error_limit
    print(f"\n[{name}] Verdict: {'PASS' if threshold_ok else 'FAIL'} "
          f"(error limit {args.error_limit}%)")
    return 0 if threshold_ok else 1


if __name__ == "__main__":
    sys.exit(main())
