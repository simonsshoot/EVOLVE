from prompts.agentharm_prompts import AGENTHARM_SUPPLEMENTS
from prompts.assebench_prompts import ASSEBENCH_SUPPLEMENTS
from prompts.rjudge_prompts import RJUDGE_SUPPLEMENTS


# benchmark -> domain -> prompt_name -> supplement text.
# "_default" covers the bare benchmark name and unknown domains.
_SUPPLEMENTS = {
    "agentharm": AGENTHARM_SUPPLEMENTS,
    "assebench": ASSEBENCH_SUPPLEMENTS,
    "rjudge": RJUDGE_SUPPLEMENTS,
}


def get_specific_prompt_supplement(prompt_name: str, dataset: str) -> str:
    benchmark, _, domain = dataset.partition("_")
    registry = _SUPPLEMENTS.get(benchmark)
    if registry is None:
        return ""
    if benchmark == "rjudge":
        # rjudge_Application_shuffled -> Application
        domain = domain.split("_")[0]
    entry = registry.get(domain) or registry.get("_default", {})
    return entry.get(prompt_name, "")


def compose_prompt(base_prompt: str, supplement: str) -> str:
    if not supplement or not supplement.strip():
        return base_prompt
    return base_prompt.rstrip() + "\n\n" + supplement.strip() + "\n"
