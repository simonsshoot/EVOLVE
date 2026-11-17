"""On-disk cache for structured LLM calls, keyed by (model, schema, rendered prompt).

Reruns and repeated samples issue many identical calls (unchanged reused tools,
similar actions); serving them from disk cuts cost and latency. This is safe to
enable by default because every chain runs at temperature 0.

Only successful calls are cached: exceptions and None results (the model made no
tool call) are always retried live. Entries are plain JSON, written atomically.

Configure via pipeline args (--llm_cache_dir / --disable_llm_cache) or environment
variables EVOLVE_LLM_CACHE=0 and EVOLVE_LLM_CACHE_DIR.
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import BaseModel

from utils import atomic_write_json

# Module state so every agent picks up the same cache without constructor changes.
_STATE: Dict[str, Any] = {
    "enabled": os.environ.get("EVOLVE_LLM_CACHE", "1") not in ("0", "false", "False"),
    "cache_dir": os.environ.get("EVOLVE_LLM_CACHE_DIR", "llm_cache"),
}


def configure(cache_dir: Optional[str] = None, enabled: Optional[bool] = None) -> None:
    if cache_dir:
        _STATE["cache_dir"] = cache_dir
    if enabled is not None:
        _STATE["enabled"] = enabled


class CachedChain:
    """Wraps a `prompt | llm.with_structured_output(Schema)` chain with a disk cache."""

    def __init__(self, chain, model_name: str, schema):
        self.chain = chain
        self.model_name = str(model_name or "")
        self.schema = schema

    def _cache_key(self, payload: Dict[str, Any]) -> str:
        # steps[0] is the prompt template; rendering it gives the exact model input.
        prompt_text = self.chain.steps[0].invoke(payload).to_string()
        # The schema is part of the key so a schema edit invalidates old entries.
        schema_json = json.dumps(self.schema.model_json_schema(), sort_keys=True)
        raw = json.dumps(
            [self.model_name, self.schema.__name__, schema_json, prompt_text],
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> Path:
        # Two-level layout keeps one directory from holding tens of thousands of files.
        return Path(_STATE["cache_dir"]) / key[:2] / (key[2:] + ".json")

    def invoke(self, payload: Dict[str, Any]):
        if not _STATE["enabled"]:
            return self.chain.invoke(payload)
        try:
            key = self._cache_key(payload)
        except Exception:
            # Cannot render the prompt (unexpected payload shape): just call through.
            return self.chain.invoke(payload)

        path = self._cache_path(key)
        if path.exists():
            try:
                return self.schema.model_validate(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                pass  # corrupt entry: recompute and overwrite below

        result = self.chain.invoke(payload)
        # Never cache failed calls; a None from the tool-call parser is transient.
        if isinstance(result, BaseModel):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(str(path), result.model_dump())
            except Exception:
                pass  # the cache must never break the pipeline
        return result


def cached_chain(chain, model_name: str, schema) -> CachedChain:
    return CachedChain(chain, model_name, schema)
