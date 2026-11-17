"""Run a generated security tool for real, in a restricted child process.

A tool is a pure function `def <tool_name>(query: str, action: str) -> bool` (True = risk
detected). Each call starts a fresh Python process running tool_runner_child.py, without site
packages, with an empty environment (no API keys), a temporary working directory, a timeout
and resource limits. Inside, the tool gets reduced builtins, only the modules in
ALLOWED_MODULES, and an audit hook that rejects file, process, network and import operations.
The hash seed is fixed so set/dict iteration order, and hence the verdict, is reproducible.

This is defense in depth for model-written code, not a hard sandbox: memory is not capped on
macOS, and code can still reach already-loaded modules through object introspection. Wrap the
process in Docker or sandbox-exec if tools may come from untrusted sources.
"""
import json
import os
import subprocess
import sys
import tempfile
from typing import Iterable, Optional, Tuple

CHILD_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_runner_child.py")
with open(CHILD_SCRIPT, "r", encoding="utf-8") as _f:
    # Passed with -c so sys.path[0] is the empty working directory, not agents/.
    CHILD_SOURCE = _f.read()

# Standard-library modules a tool may import or list in `require`; anything else is an error.
ALLOWED_MODULES = frozenset({
    "re", "json", "string", "math", "unicodedata", "urllib.parse", "collections", "itertools",
    "functools", "difflib", "ipaddress", "html", "datetime", "time", "typing", "logging",
})
DEFAULT_TIMEOUT = 5.0
MEMORY_LIMIT_MB = 1024  # applied where the OS supports RLIMIT_AS (Linux, not macOS)
MAX_ERROR_CHARS = 500


def run_tool(
    tool_code: str,
    tool_name: str,
    query: str,
    action: str,
    require: Optional[Iterable[str]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Tuple[Optional[bool], str]:
    """Return (result, "") if the tool ran, or (None, error message) if it could not."""
    if not isinstance(tool_code, str) or not tool_code.strip():
        return None, "empty tool_code"
    if isinstance(require, str):
        require = [require]
    modules = sorted({str(m).strip() for m in (require or []) if str(m).strip()})
    not_allowed = [m for m in modules if m not in ALLOWED_MODULES]
    if not_allowed:
        return None, f"required modules not allowed: {', '.join(not_allowed)}"

    payload = {
        "code": tool_code,
        "name": str(tool_name or ""),
        "query": str(query or ""),
        "action": str(action or ""),
        "require": modules,
        "allowed_modules": sorted(ALLOWED_MODULES),
        "cpu_seconds": int(timeout) + 1,
        "memory_bytes": MEMORY_LIMIT_MB * 1024 * 1024,
    }
    try:
        with tempfile.TemporaryDirectory(prefix="evolve_tool_") as workdir:
            # No shell; inputs travel as JSON on stdin, never interpolated into code.
            # -s -S: no site-packages; -B: no .pyc writes; the only env var is the hash seed.
            proc = subprocess.run(
                [sys.executable, "-s", "-S", "-B", "-X", "utf8", "-c", CHILD_SOURCE],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env={"PYTHONHASHSEED": "0"},
                cwd=workdir,
                start_new_session=True,
            )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:g}s"
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"could not start tool process: {e}"

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    try:
        verdict = json.loads(lines[-1])
    except (IndexError, ValueError):
        verdict = None
    if not isinstance(verdict, dict):
        detail = proc.stderr.strip()[-MAX_ERROR_CHARS:]
        return None, f"tool process exited with code {proc.returncode}: {detail}"
    if verdict.get("ok") is True and isinstance(verdict.get("result"), bool):
        return verdict["result"], ""
    return None, str(verdict.get("error") or "unknown error")[:MAX_ERROR_CHARS]
