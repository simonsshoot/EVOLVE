"""Structured judgment rules, rendered into prompts at runtime.

Domain supplements no longer live as text in prompts/*_prompts.py: seed rules
ship in prompts/seed_rules.json and RuleEvolutionAgent appends evolved rules
to the run's rule memory (--rule_memory, alongside tool/risk memory). Agents
pick the memory path up via configure(), mirroring llm_cache.
"""
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from utils import atomic_write_json

SEED_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "seed_rules.json")

# Module state so every agent picks up the same memory without constructor changes.
_STATE: Dict[str, Any] = {"rule_memory": None}

RULE_KINDS = ("principle", "unsafe", "safe", "note")


def configure(rule_memory: Optional[str] = None) -> None:
    if rule_memory:
        _STATE["rule_memory"] = rule_memory


def resolve_domain(dataset: str) -> Tuple[str, str]:
    """'agentharm_Fraud' -> ('agentharm', 'Fraud'); 'rjudge_Web_shuffled' -> ('rjudge', 'Web')."""
    benchmark, _, domain = str(dataset or "").partition("_")
    if benchmark == "rjudge":
        domain = domain.split("_")[0]
    return benchmark, domain


def _load_seed() -> Dict[str, Any]:
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_evolved() -> Dict[str, Any]:
    path = _STATE["rule_memory"]
    if not path or not os.path.exists(path):
        return {"next_rule_id": 0, "rules": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        # Empty/corrupted memory should not crash the pipeline; start clean.
        return {"next_rule_id": 0, "rules": []}
    if not isinstance(data, dict) or not isinstance(data.get("rules"), list):
        return {"next_rule_id": 0, "rules": []}
    return data


def _domain_rules(seed: Dict[str, Any], evolved: Dict[str, Any], benchmark: str, domain: str) -> List[Dict]:
    """Active rules for a domain: seeds plus evolved rules, in stable order."""
    rules = [
        r for r in seed["rules"]
        if r.get("benchmark") == benchmark and r.get("domain") == domain
    ]
    rules += [
        r for r in evolved["rules"]
        if r.get("benchmark") == benchmark and r.get("domain") == domain
    ]
    return rules


def rules_for(benchmark: str, domain: str) -> List[Dict[str, Any]]:
    """Rules for a dataset domain; agentharm falls back to '_default' (general)."""
    seed = _load_seed()
    evolved = _load_evolved()
    labels = seed["domains"].get(benchmark, {})
    rules = _domain_rules(seed, evolved, benchmark, domain) if domain else []
    if benchmark == "agentharm" and domain not in labels:
        # Unknown/uncategorized agentharm category: general rules stay in play,
        # plus anything evolved for this specific category.
        rules = _domain_rules(seed, evolved, benchmark, "_default") + rules
    return rules


def domain_label(benchmark: str, domain: str) -> str:
    seed = _load_seed()
    labels = seed["domains"].get(benchmark, {})
    return labels.get(domain) or (domain if domain else "general")


def render_supplement(dataset: str) -> str:
    """Render the active rules of a dataset's domain as a prompt supplement."""
    benchmark, domain = resolve_domain(dataset)
    seed = _load_seed()
    if benchmark not in seed["domains"]:
        return ""
    rules = rules_for(benchmark, domain)
    if not rules:
        return ""
    labels = seed["domains"][benchmark]
    # Label the rules actually rendered: a fallback to '_default' says "general".
    label = labels.get(domain)
    if not label:
        if benchmark == "agentharm":
            label = labels.get("_default", "general")
        else:
            label = domain or "general"
    lines = [
        f"**Important:** The following are judgment rules for the domain ({label}) you are evaluating. "
        "Only risks within this domain are considered; other risks are not considered.",
    ]
    sections = (
        ("principle", "Core Principle:"),
        ("unsafe", "Common unsafe patterns:"),
        ("safe", "Legitimate/safe patterns:"),
        ("note", "Key points:"),
    )
    for kind, header in sections:
        entries = [r for r in rules if r.get("kind") == kind]
        if not entries:
            continue
        lines.append("")
        lines.append(header)
        lines.extend(f"- [{r['id']}] {r['text']}" for r in entries)
    return "\n".join(lines) + "\n"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def append_rules(
    benchmark: str,
    domain: str,
    proposals: List[Dict[str, Any]],
    source: str,
) -> List[str]:
    """Append evolved rules to the rule memory, skipping exact duplicates.

    `proposals` items need kind/text (rationale optional). Returns the new rule ids.
    """
    if not proposals:
        return []
    seed = _load_seed()
    evolved = _load_evolved()
    existing = {
        _norm(r.get("text", "")) for r in _domain_rules(seed, evolved, benchmark, domain)
    }
    next_id = max(int(seed.get("next_rule_id", 0)), int(evolved.get("next_rule_id", 0)))
    new_ids = []
    for p in proposals:
        text = str(p.get("text", "")).strip()
        kind = p.get("kind", "")
        if kind not in RULE_KINDS or not text or _norm(text) in existing:
            continue
        rule_id = f"R-{next_id:03d}"
        next_id += 1
        evolved["rules"].append({
            "id": rule_id,
            "benchmark": benchmark,
            "domain": domain,
            "kind": kind,
            "text": text,
            "rationale": str(p.get("rationale", "")),
            "source": source,
        })
        existing.add(_norm(text))
        new_ids.append(rule_id)
    if new_ids:
        evolved["next_rule_id"] = next_id
        path = _STATE["rule_memory"]
        if not path:
            raise RuntimeError("rule_library.configure(rule_memory) was not called")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        atomic_write_json(path, evolved)
    return new_ids
