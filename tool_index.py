"""In-memory index over the lifelong tool library.

Stage-1 retrieval for FusionAgent: recall the top-K most similar stored tools per
planned tool via embeddings (with a deterministic lexical fallback when no
embedding backend is available), instead of injecting whole library categories.

Also owns category normalization:
- library keys are folded to a canonical form (see agents.agent_utils.normalize_category);
- a persisted alias table (category_aliases.json next to the tool library) maps
  LLM-invented variants onto canonical categories, learned whenever a confirmed
  tool match crosses category boundaries.
"""

import hashlib
import json
import math
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.agent_utils import atomic_write_json, normalize_category

# (embed_fn, namespace) or (None, "lexical"); embed_fn maps texts -> vectors, or
# None when the backend is unavailable (tests, offline runs) -> lexical scoring.
Embedder = Tuple[Optional[Callable[[List[str]], Optional[List[List[float]]]]], str]


def default_alias_path(tool_memory_path: str) -> str:
    return os.path.join(
        os.path.dirname(os.path.abspath(tool_memory_path or ".")),
        "category_aliases.json",
    )


def default_embedding_cache_path(tool_memory_path: str) -> str:
    stem = os.path.splitext(os.path.abspath(tool_memory_path or "tools"))[0]
    return stem + ".embeddings.json"


def default_embedder(model_name: str) -> Embedder:
    """Build an OpenAI-compatible embedding backend from the environment.

    Returns (None, "lexical") when no model or API key is configured, so retrieval
    degrades to the deterministic lexical scorer instead of failing.
    """
    model_name = (model_name or "").strip()
    if not model_name:
        return None, "lexical"
    api_key = os.environ.get("EVOLVE_EMBEDDING_API_KEY") or os.environ.get(
        "OPENAI_API_KEY", ""
    )
    if not api_key:
        return None, "lexical"
    base_url = (
        os.environ.get("EVOLVE_EMBEDDING_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or "https://api.zhizengzeng.com/v1"
    )
    try:
        from langchain_openai import OpenAIEmbeddings

        backend = OpenAIEmbeddings(
            model=model_name, api_key=api_key, base_url=base_url
        )
    except Exception:
        return None, "lexical"

    def embed_fn(texts: List[str]) -> Optional[List[List[float]]]:
        try:
            return [list(map(float, v)) for v in backend.embed_documents(texts)]
        except Exception:
            return None

    return embed_fn, f"openai:{model_name}"


def resolve_key(library: Dict[str, Any], alias: "CategoryAlias", name: str) -> str:
    """Canonical library key for a (possibly variant) category label.

    Lookup order: alias-resolved normalized name, the raw label (old libraries keep
    readable keys), then any existing key with the same normalized form. Falls back
    to the normalized form for genuinely new categories.
    """
    key = alias.resolve(name)
    if key in library:
        return key
    if name in library:
        return name
    for existing in library:
        if normalize_category(existing) == key:
            return existing
    return key


class CategoryAlias:
    """Persisted variant -> canonical category map, shared by all library readers."""

    def __init__(self, path: str = ""):
        self.path = str(path) if path else ""
        self._mtime: Optional[float] = None
        self.aliases: Dict[str, str] = {}
        self._reload()

    def _reload(self) -> None:
        if not self.path:
            return
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            self.aliases = {}
            self._mtime = None
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.aliases = {
                    str(k): str(v) for k, v in data.items() if k and v
                }
                self._mtime = mtime
        except Exception:
            pass  # unreadable/partial file: keep the last good table

    def resolve(self, name: str) -> str:
        self._reload()
        normalized = normalize_category(name)
        return self.aliases.get(normalized, normalized)

    def learn(self, variant: str, canonical: str) -> bool:
        """Record variant -> canonical; returns True when the table changed."""
        self._reload()
        v = normalize_category(variant)
        c = self.aliases.get(normalize_category(canonical), normalize_category(canonical))
        if not v or not c or v == c or self.aliases.get(v) == c:
            return False
        self.aliases[v] = c
        if self.path:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
            atomic_write_json(self.path, self.aliases)
            try:
                self._mtime = os.path.getmtime(self.path)
            except OSError:
                pass
        return True


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _tokens(text: str) -> set:
    return set(t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if t)


def _lexical(query: str, doc: str) -> float:
    q, d = _tokens(query), _tokens(doc)
    if not q or not d:
        return 0.0
    return len(q & d) / len(q | d)


class ToolIndex:
    """Read-through index over the tool library JSON.

    The library file is parsed at most once per mtime change; tool texts are
    embedded at most once per (namespace, text) via an on-disk cache next to the
    library, so restarts and reruns do not re-embed the whole library.
    """

    def __init__(
        self,
        tool_memory_path: str,
        alias: Optional[CategoryAlias] = None,
        embedder: Optional[Embedder] = None,
        recall_k: int = 5,
        embedding_cache_path: str = "",
    ):
        self.path = str(tool_memory_path or "")
        self.alias = alias or CategoryAlias(default_alias_path(self.path))
        if embedder is None:
            embedder = (None, "lexical")
        self.embed_fn, self.embed_namespace = embedder
        self.recall_k = max(1, int(recall_k or 1))
        self.embedding_cache_path = (
            embedding_cache_path or default_embedding_cache_path(self.path)
        )
        self._mtime: Optional[float] = None
        self._loaded = False
        self._library: Dict[str, Any] = {}
        # per record: {"key", "readable", "tool", "text", "vector"}
        self._records: List[Dict[str, Any]] = []
        self._embed_cache: Dict[str, List[float]] = self._load_embed_cache()
        self._embed_cache_dirty = False

    # ── library loading ───────────────────────────────────────────────────
    def _load_library(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _refresh(self) -> None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            mtime = None
        if self._loaded and mtime == self._mtime:
            return
        self._loaded = True
        self._mtime = mtime
        self._library = self._load_library()
        records = []
        for key, tools in self._library.items():
            if not isinstance(tools, list):
                continue
            for tool in tools:
                if not isinstance(tool, dict) or not tool.get("tool_name"):
                    continue
                readable = tool.get("category") or key
                records.append(
                    {
                        "key": normalize_category(key),
                        "readable": readable,
                        "tool": tool,
                        "text": "%s | %s: %s"
                        % (readable, tool.get("tool_name", ""), tool.get("tool_description", "")),
                    }
                )
        vectors = self._embed_records(records)
        for record, vector in zip(records, vectors or [None] * len(records)):
            record["vector"] = vector
        self._records = records
        if self._embed_cache_dirty:
            self._save_embed_cache()
            self._embed_cache_dirty = False

    # ── embeddings ────────────────────────────────────────────────────────
    def _cache_key(self, text: str) -> str:
        return hashlib.sha256(
            (self.embed_namespace + "\x00" + (text or "")).encode("utf-8")
        ).hexdigest()

    def _load_embed_cache(self) -> Dict[str, List[float]]:
        try:
            with open(self.embedding_cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(k): list(map(float, v)) for k, v in data.items() if v}
        except Exception:
            pass
        return {}

    def _save_embed_cache(self) -> None:
        if not self.embedding_cache_path:
            return
        os.makedirs(
            os.path.dirname(os.path.abspath(self.embedding_cache_path)) or ".",
            exist_ok=True,
        )
        atomic_write_json(self.embedding_cache_path, self._embed_cache)

    def _embed_records(self, records: List[Dict[str, Any]]) -> Optional[List[List[float]]]:
        if self.embed_fn is None:
            return None
        misses = [r for r in records if self._cache_key(r["text"]) not in self._embed_cache]
        if misses:
            vectors = self.embed_fn([r["text"] for r in misses])
            if vectors is None or len(vectors) != len(misses):
                return None  # backend unavailable: whole refresh goes lexical
            for record, vector in zip(misses, vectors):
                self._embed_cache[self._cache_key(record["text"])] = vector
            self._embed_cache_dirty = True
        return [self._embed_cache.get(self._cache_key(r["text"])) for r in records]

    # ── lookup & recall ──────────────────────────────────────────────────
    def resolve_category(self, name: str) -> str:
        """Canonical library key for a category label (alias + fold aware)."""
        self._refresh()
        return resolve_key(self._library, self.alias, name)

    def _decorated(self, tool: Dict[str, Any], key: str) -> Dict[str, Any]:
        record = dict(tool)
        record.setdefault("category", key)
        return record

    def find_tool(self, category: str, tool_name: str) -> Optional[Tuple[Dict[str, Any], str]]:
        """Find a stored tool by name: its own (resolved) category first, then any
        category — recalled candidates may cross category boundaries.

        Returns (tool dict with a "category" field, canonical category key) or None.
        """
        self._refresh()
        if not tool_name:
            return None
        key = resolve_key(self._library, self.alias, category)
        for tool in self._library.get(key, []) or []:
            if isinstance(tool, dict) and tool.get("tool_name") == tool_name:
                return self._decorated(tool, key), key
        for other_key, tools in self._library.items():
            if other_key == key or not isinstance(tools, list):
                continue
            for tool in tools:
                if isinstance(tool, dict) and tool.get("tool_name") == tool_name:
                    return self._decorated(tool, other_key), other_key
        return None

    def recall(self, queries: List[str], k: int = 0) -> List[List[Dict[str, Any]]]:
        """Stage-1 retrieval: the top-k most similar stored tools per query.

        Embeddings are used when both query and record vectors are available;
        otherwise scoring falls back to the deterministic lexical overlap.
        """
        self._refresh()
        k = max(1, int(k or self.recall_k))
        if not self._records:
            return [[] for _ in queries]
        query_vectors = None
        if self.embed_fn is not None:
            query_vectors = self.embed_fn(list(queries))
        results: List[List[Dict[str, Any]]] = []
        for i, query in enumerate(queries):
            scored = []
            for record in self._records:
                if query_vectors is not None and record.get("vector") is not None:
                    score = _cosine(query_vectors[i], record["vector"])
                else:
                    score = _lexical(query, record["text"])
                scored.append((score, record["key"], record["tool"].get("tool_name", ""), record))
            scored.sort(key=lambda item: (-item[0], item[1], item[2]))
            results.append(
                [self._decorated(item[3]["tool"], item[3]["readable"]) for item in scored[:k]]
            )
        return results

    def learn_alias(self, variant: str, canonical: str) -> bool:
        return self.alias.learn(variant, canonical)
