"""RuleEvolutionAgent: distills judgment rules from misjudged samples.

Triggered by the pipeline after a misjudgment (label != decision). Proposed
rules are appended to the run's rule memory (rule_library) and take effect on
the next rendered prompt; there is no admission gate or retirement.
"""
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from prompts.base_prompts import RULE_EVOLUTION_PROMPT
from rule_library import append_rules, domain_label, resolve_domain, rules_for
from langchain_core.prompts import ChatPromptTemplate
from agent import BaseAgent


class ProposedRule(BaseModel):
    # kind is a plain str (not Literal): one malformed proposal must not fail
    # the whole batch; append_rules filters invalid kinds instead.
    kind: str = Field(
        description='"unsafe" = a pattern that should be judged unsafe; "safe" = a pattern that should be judged safe; "principle"/"note" = a general judgment principle'
    )
    text: str = Field(description="One general judgment rule, applicable to similar cases; not a retelling of this case")
    rationale: str = Field(default="", description="Why this rule would have corrected the misjudgment")


class RuleProposals(BaseModel):
    rules: List[ProposedRule] = Field(
        default_factory=list,
        description="Rules distilled from the misjudged case; empty if nothing generalizes",
    )


class RuleEvolutionAgent:
    def __init__(self, model: str = "deepseek-chat"):
        base_agent = BaseAgent(model, logger="rule_evolution_agent_logger")
        self.logger = base_agent.logger
        self.agent = base_agent.initagent()
        self.chain = (
            ChatPromptTemplate.from_template("{prompt}")
            | self.agent.with_structured_output(RuleProposals, method="function_calling")
        )

    def evolve(
        self,
        dataset: str,
        data: Dict[str, Any],
        label: int,
        decision: str,
        reason: str = "",
    ) -> List[str]:
        """Distill rules from one misjudged case and append them to the rule memory.

        Returns the ids of the newly stored rules (empty when nothing was stored).
        """
        benchmark, domain = resolve_domain(dataset)
        existing = rules_for(benchmark, domain)
        existing_rules = "\n".join(
            f"- [{r['id']}] ({r['kind']}) {r['text']}" for r in existing
        ) or "(none)"
        prompt = RULE_EVOLUTION_PROMPT.format(
            request=data.get("request", ""),
            agent_actions=data.get("agent_actions", ""),
            decision=decision,
            label="safe (benign)" if label == 1 else "unsafe (harmful)",
            reason=reason or "No reason recorded.",
            domain_label=domain_label(benchmark, domain),
            existing_rules=existing_rules,
        )
        try:
            result = self.chain.invoke({"prompt": prompt})
        except Exception as e:
            self.logger.error(f"Failed to run rule evolution: {str(e)}")
            return []
        if result is None:
            self.logger.error("Rule evolution returned no structured output")
            return []
        proposals = [r.model_dump() for r in result.rules if r and str(r.text).strip()]
        if not proposals:
            return []
        new_ids = append_rules(
            benchmark, domain, proposals, source=f"evolved:{data.get('id', 'unknown')}"
        )
        if new_ids:
            self.logger.info(
                f"Rule evolution stored {len(new_ids)} rule(s) for {benchmark}/{domain}: {new_ids}"
            )
        return new_ids
