"""Prompt composition helpers.

Domain supplements are rendered at runtime from the structured rule library
(seed rules in prompts/seed_rules.json plus evolved rules in the run's rule
memory); no domain supplement text lives in code anymore.
"""
from rule_library import render_supplement

# Only these stages receive domain rules; tool-level prompts stay rule-free,
# matching the old hand-written registries.
RULE_STAGES = ("RISK_ANALYSIS", "DOUBT_DECISION")


def get_specific_prompt_supplement(prompt_name: str, dataset: str) -> str:
    if prompt_name not in RULE_STAGES:
        return ""
    return render_supplement(dataset)


def compose_prompt(base_prompt: str, supplement: str) -> str:
    if not supplement or not supplement.strip():
        return base_prompt
    return base_prompt.rstrip() + "\n\n" + supplement.strip() + "\n"
