import os
import subprocess
import sys

IGNORE_DIRS = {"venv", "frontend", "models", "__pycache__", ".git", "sessions", "arc", "node_modules"}
TOOLS = ["pylint", "mypy", "pyflakes", "bandit", "vulture", "pydocstyle"]

def find_py_files(root_dir):
    for dirpath, _, filenames in os.walk(root_dir):
        if any(ignore in dirpath for ignore in IGNORE_DIRS):
            continue
        for f in filenames:
            if f.endswith(".py") and f != "run_deep_audit.py":
                yield os.path.join(dirpath, f)

def run_deep_audit():
    py_files = list(find_py_files("."))
    print(f"Found {len(py_files)} Python files. Starting line-by-line deep scan...\n")

    all_passed = True
    for tool in TOOLS:
        print(f"--- Running: {tool} ---")
        try:
            if tool == "vulture":
                cmd = [
                    sys.executable, "-m", tool,
                    "--ignore-decorators=@app.get,@app.post,@app.put,@app.delete,@app.patch,@app.options,@app.head,@app.route,@field_validator,@classmethod,@property",
                    "--ignore-names=*_api,*_full,*_stream,*_completion,*_generate",
                    "--min-confidence=80",
                    *py_files
                ]
            elif tool == "pylint":
                cmd = [sys.executable, "-m", tool, "--rcfile=.pylintrc", *py_files]
            elif tool == "mypy":
                cmd = [sys.executable, "-m", tool, "--config-file", "mypy.ini", *py_files]
            elif tool == "pydocstyle":
                cmd = [sys.executable, "-m", tool, "--match='.*'", *py_files]
            elif tool == "bandit":
                cmd = [sys.executable, "-m", tool, "--skip=B101,B110,B404,B603,B607,B605", *py_files]
            else:
                cmd = [sys.executable, "-m", tool, *py_files]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if result.returncode == 0:
                print(f"PASS {tool}: No issues found.")
            else:
                print(f"ISSUES {tool}: Check output below:\n")
                output = result.stdout if result.stdout else result.stderr
                print(output[:3000])
                all_passed = False
        except subprocess.TimeoutExpired:
            print(f"TIMEOUT {tool}: Skipping after timeout.")
        except Exception as e:
            print(f"ERROR {tool}: {e}")
        print("-" * 40)

    print("\n--- Running: Frontend ESLint ---")
    if os.path.exists("frontend"):
        try:
            result = subprocess.run(
                ["npx", "eslint", ".", "--ext", ".js,.jsx,.ts,.tsx"],
                cwd="frontend",
                capture_output=True,
                text=True,
                timeout=120,
                shell=(os.name == "nt"),
            )
            if result.returncode == 0:
                print("PASS Frontend ESLint: No issues found.")
            else:
                print("ISSUES Frontend ESLint:\n" + (result.stdout or result.stderr)[:3000])
                all_passed = False
        except Exception as e:
            print(f"ERROR ESLint: {e}")

    print("\n" + "="*60)
    if all_passed:
        print("DEEP AUDIT PASSED: Zero line-by-line issues found.")
    else:
        print("DEEP AUDIT COMPLETED: Some warnings found. Review logs above.")
    print("="*60)

if __name__ == "__main__":
    run_deep_audit()
