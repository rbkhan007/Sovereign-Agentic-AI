# Security Policy

## Reporting a vulnerability

Security issues should be reported privately. Open a [GitHub Security Advisory](https://github.com/rbkhan007/Sovereign-Agentic-AI/security/advisories)
or email the maintainer directly. Please do **not** open a public issue for security
vulnerabilities.

## Scope

This is an experimental, local-first project. The main trust model is **data stays on your
machine** — there is no telemetry and no forced cloud. The most sensitive surfaces are:

- **Self-healing agent** (`healing_agent.py`): can execute arbitrary Python. It refuses to
  run caller-supplied code unless `--allow-unsafe-healing` is passed. Keep it off on any
  host reachable from untrusted networks.
- **Agentic Terminal API** (`POST /v1/terminal/exec|python`): sandboxed, but still powerful.
  Protect it with `--api-token` / `--admin-key` when exposing the server.
- **File uploads / workspace files**: paths are sanitized against traversal and served via
  `SafeStaticFiles` with `nosniff` + attachment disposition.
- **LoRA training**: adapter names and datasets are validated to prevent path traversal.

## Recommended hardening

- Run `python run.py --sandbox` to force sandbox mode (no DB writes, isolated conversations,
  file ops scoped to the project directory).
- Use `--api-token` (Bearer on `/v1/*` and `/mcp`) and `--admin-key` (control-plane
  mutations) when the API is reachable over a network.
- Use `--rate-limit` to protect against per-IP abuse.
- Never enable `--allow-unsafe-healing` on a machine exposed to untrusted users.

## Supported versions

Security fixes are applied to the latest release on `main`.

## Disclosure

We do not currently offer bounties; we ask for responsible disclosure and reasonable
coordination time before public announcement.
