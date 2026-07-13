"""
Token usage tracker for EVOLVE pipeline.

A process-wide singleton accumulates prompt/completion token counts from every
LangChain ChatOpenAI invoke. BaseAgent wires the callback into each model
instance so all agents (simulate/analysis/fusion/executor/auditor) report here.

Usage in run_evolution.py:
    from token_tracker import tracker, TokenCallback

    pre = tracker.snapshot()           # before sample processing
    ...pipeline(args,item)...
    post = tracker.snapshot()
    delta = {k: post[k]-pre[k] for k in pre}
"""
from __future__ import annotations
import threading
from typing import Any, Dict, Optional
try:
    from langchain_core.callbacks import BaseCallbackHandler
except Exception:  # pragma: no cover - langchain always available at runtime
    class BaseCallbackHandler:  # type: ignore
        pass


class _TokenTracker:
    def __init__(self):
        self._lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_calls = 0
        self.failed_extractions = 0

    def add(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:
            self.input_tokens += int(input_tokens or 0)
            self.output_tokens += int(output_tokens or 0)
            if (input_tokens or output_tokens):
                self.total_calls += 1

    def record_failure(self) -> None:
        with self._lock:
            self.failed_extractions += 1

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_calls": self.total_calls,
                "failed": self.failed_extractions,
            }

    def reset(self) -> None:
        with self._lock:
            self.input_tokens = 0
            self.output_tokens = 0
            self.total_calls = 0
            self.failed_extractions = 0


tracker = _TokenTracker()


def _extract_usage(response: Any) -> Optional[Dict[str, int]]:
    """Try multiple shapes LangChain/OpenAI responses may expose."""
    # Shape A: response.llm_output['token_usage']  (batch invoke / legacy)
    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        tu = llm_output.get("token_usage") or {}
        if isinstance(tu, dict) and ("prompt_tokens" in tu or "completion_tokens" in tu or "total_tokens" in tu):
            return {
                "prompt_tokens": tu.get("prompt_tokens", 0),
                "completion_tokens": tu.get("completion_tokens", 0),
            }

    # Shape B: generations[i][j].message.usage_metadata
    gens = getattr(response, "generations", None)
    if isinstance(gens, list) and gens:
        first_gen_list = gens[0]
        if isinstance(first_gen_list, list) and first_gen_list:
            gen0 = first_gen_list[0]
            msg = getattr(gen0, "message", None)
            um = getattr(msg, "usage_metadata", None) if msg is not None else None
            if isinstance(um, dict):
                inp = um.get("input_tokens") or um.get("prompt_tokens")
                outp = um.get("output_tokens") or um.get("completion_tokens")
                if isinstance(inp,(int,float)) and isinstance(outp,(int,float)):
                    return {"prompt_tokens":int(inp), "completion_tokens":int(outp)}
            am = getattr(msg, "additional_kwargs", None) if msg is not None else None
            if isinstance(am, dict):
                tok = am.get("token_usage")
                if isinstance(tok, dict) and ("prompt_tokens" in tok or "completion_tokens" in tok):
                    return {"prompt_tokens":tok.get("prompt_tokens",0), "completion_tokens":tok.get("completion_tokens",0)}

    # Shape C: AIMessage directly passed as response
    um2 = getattr(response, "usage_metadata", None)
    if isinstance(um2, dict):
        inp=um2.get("input_tokens"); outp=um2.get("output_tokens")
        if isinstance(inp,(int,float)) and isinstance(outp,(int,float)):
            return {"prompt_tokens":int(inp), "completion_tokens":int(outp)}

    return None


class TokenCallback(BaseCallbackHandler):
    """Aggregate token usage across LLM invokes."""

    def on_llm_end(self, response, *, run_id=None, parent_run_id=None, **kwargs):  # noqa: D401
        try:
            data = _extract_usage(response)
            if data:
                tracker.add(data["prompt_tokens"], data["completion_tokens"])
            else:
                tracker.record_failure()
        except Exception:
            tracker.record_failure()

    def on_llm_error(self, error, **kwargs):  # noqa: D401
        pass
