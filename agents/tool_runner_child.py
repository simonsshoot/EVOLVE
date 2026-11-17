"""Child process for tool_runner: runs one security tool and prints its verdict as one JSON line.

tool_runner passes this file's source with `python -s -S -B -c` and the payload on stdin.
Keep imports to the standard library; this file must not import project code.
"""
import json
import os
import sys

SAFE_BUILTINS = (
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes", "callable", "chr",
    "classmethod", "complex", "dict", "divmod", "enumerate", "filter", "float", "format",
    "frozenset", "getattr", "hasattr", "hash", "hex", "int", "isinstance", "issubclass",
    "iter", "len", "list", "map", "max", "min", "next", "NotImplemented", "object", "oct",
    "ord", "pow", "print", "property", "range", "repr", "reversed", "round", "set", "slice",
    "sorted", "staticmethod", "str", "sum", "super", "tuple", "type", "zip", "__build_class__",
)
# Modules that allowed modules import lazily (datetime.strptime, str.encode("idna")).
# They are loaded before the guard and may be imported, but not listed in `require`.
IMPLICIT_MODULES = ("_strptime", "encodings.idna", "encodings.punycode")
TOOL_MODULE = "security_tool"
FunctionType = type(lambda: None)


class _Discard:
    # Tools may print; their output is dropped so stdout carries only the verdict.
    def write(self, text):
        return len(text)

    def flush(self):
        pass


def _limit_resources(cpu_seconds, memory_bytes):
    try:
        import resource
    except ImportError:  # not available on Windows
        return
    # CPU budget, no writes to regular files, no new processes; memory cap where supported
    # (setting RLIMIT_AS raises ValueError on macOS).
    limits = (
        ("RLIMIT_CPU", cpu_seconds),
        ("RLIMIT_FSIZE", 0),
        ("RLIMIT_NPROC", 0),
        ("RLIMIT_AS", memory_bytes),
    )
    for name, value in limits:
        try:
            resource.setrlimit(getattr(resource, name), (value, value))
        except (AttributeError, ValueError, OSError):
            pass


def _install_guard(blocked):
    # Deny every audited operation (files, processes, network, imports, frame and gc access)
    # except compiling and running the tool's own code.
    def hook(event, args):
        if event in ("compile", "exec"):
            return
        blocked.append(event)
        raise RuntimeError(f"operation not allowed in tool sandbox: {event}")

    sys.addaudithook(hook)


def _safe_builtins(allowed):
    import builtins

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        # `from urllib import parse` is fine when every imported name is an allowed submodule.
        submodules_ok = bool(fromlist) and all(f"{name}.{item}" in allowed for item in fromlist)
        if level != 0 or not (name in allowed or submodules_ok):
            raise ImportError(f"import of {name!r} is not allowed")
        # Every allowed module is imported before the guard, so this never loads new code.
        return sys.modules[name] if fromlist else sys.modules[name.partition(".")[0]]

    safe = {name: getattr(builtins, name) for name in SAFE_BUILTINS}
    safe.update(
        (name, value)
        for name, value in vars(builtins).items()
        if isinstance(value, type) and issubclass(value, BaseException)
    )
    safe["__import__"] = guarded_import
    return safe


def _find_function(tool_globals, name):
    candidates = [name]
    # Library entries renamed to <name>_v2 often still define <name>.
    base, sep, version = name.rpartition("_v")
    if sep and version.isdigit():
        candidates.append(base)
    for candidate in candidates:
        if callable(tool_globals.get(candidate)):
            return tool_globals[candidate]
    defined = [
        v for v in tool_globals.values()
        if isinstance(v, FunctionType) and v.__module__ == TOOL_MODULE
    ]
    return defined[0] if len(defined) == 1 else None


def _run(payload, blocked):
    allowed = set(payload["allowed_modules"]) | set(IMPLICIT_MODULES)
    tool_globals = {"__builtins__": _safe_builtins(allowed), "__name__": TOOL_MODULE}
    # Tools may use modules listed in `require` without importing them (as container.py allows).
    for name in payload["require"]:
        top = name.partition(".")[0]
        tool_globals[top] = sys.modules[top]

    # Compile before the guard: reporting a SyntaxError tries to open the source file.
    code = compile(payload["code"], "<tool>", "exec")
    _install_guard(blocked)
    exec(code, tool_globals)

    fn = _find_function(tool_globals, payload["name"])
    if fn is None:
        return {"ok": False, "error": f"function {payload['name']!r} not defined"}
    result = fn(payload["query"], payload["action"])
    if not isinstance(result, bool):
        return {"ok": False, "error": f"returned {type(result).__name__}, expected bool"}
    return {"ok": True, "result": result}


def main():
    payload = json.loads(sys.stdin.read())  # stdin is now at EOF, so a stray read cannot block
    _limit_resources(payload["cpu_seconds"], payload["memory_bytes"])
    for name in sorted(payload["allowed_modules"]) + list(IMPLICIT_MODULES):
        __import__(name)
    if "logging" in sys.modules:
        sys.modules["logging"]._srcfile = None  # skip caller lookup, which needs sys._getframe

    out = sys.stdout
    sys.stdout = _Discard()
    blocked = []
    try:
        verdict = _run(payload, blocked)
    except BaseException as e:
        verdict = {"ok": False, "error": f"{type(e).__name__}: {e}"[:500]}
    if blocked:
        # Reported even if the tool caught the RuntimeError and returned normally.
        verdict = {"ok": False, "error": f"blocked operation: {blocked[0]}"}

    out.write(json.dumps(verdict) + "\n")
    out.flush()
    os._exit(0)  # skip interpreter shutdown, which would trip the audit hook


if __name__ == "__main__":
    main()
