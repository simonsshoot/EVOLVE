import json
import time
from typing import List, Dict, Any, Tuple, Optional, Literal

from pydantic import BaseModel, Field

from prompts.base_prompts import (
    TOOL_DOUBT_AUTO_OPTIMIZE_PROMPT,
    TOOL_DOUBT_OPTIMIZE_PROMPT,
    TOOL_DOUBT_PROMPT,
    DOUBT_DECISION_PROMPT,
)
from .agent_utils import normalize_is_safe
from prompts.prompt_utils import compose_prompt, get_specific_prompt_supplement
from langchain_core.prompts import ChatPromptTemplate
from agent import BaseAgent
from llm_cache import cached_chain


class ToolMemoryRepository:
    def __init__(self, tool_memory_path: str):
        self.tool_memory_path = tool_memory_path

    def load(self) -> Dict[str, Any]:
        with open(self.tool_memory_path, "r", encoding="utf-8") as f:
            return json.load(f)


class DoubtReviewOutput(BaseModel):
    is_safe: Literal["True", "False"] = Field(default="True", description='"True" if the tool is correct and free of the listed CWE risks')
    reason: str = Field(default="", description="Reasoning for the verdict")


class DoubtReviewBatchOutput(BaseModel):
    reviews: List[DoubtReviewOutput] = Field(default_factory=list, description="One review per input tool (or tool pair), in the same order as the input array")


class ToolSpec(BaseModel):
    category: str = Field(default="", description="Risk category the tool protects against")
    tool_name: str = Field(default="", description="Function name in tool_code; keep the original name")
    tool_description: str = Field(default="", description="What the tool detects and how")
    require: List[str] = Field(default_factory=list, description="Python modules the code imports, e.g. ['re']")
    tool_code: str = Field(default="", description="Python source of def <tool_name>(query: str, action: str) -> bool; True = risk detected")


class FinalDecisionOutput(BaseModel):
    is_safe: Literal["True", "False"] = Field(default="True", description='"True" if the request and agent actions are safe')
    reason: str = Field(default="", description="Reasoning for the decision")
    applied_rules: List[str] = Field(default_factory=list, description="IDs ([R-xxx]) of the domain judgment rules the decision relied on; empty if none")


def _failed_verdict(stage: str) -> Dict[str, Any]:
    # Fail closed: an LLM error or empty output must never count as a safe verdict.
    # llm_failed lets doubt_decision tell a failed call apart from a real unsafe verdict.
    return {
        "is_safe": "False",
        "reason": f"{stage} failed (LLM error or empty output); treated as unsafe.",
        "llm_failed": True,
    }


class AuditorAgent:
    def __init__(
        self,
        tool_memory_path: str,
        audit_model: str = "deepseek-chat",
        dataset: str = "",
    ):
        self.tool_repo = ToolMemoryRepository(tool_memory_path)
        base_agent = BaseAgent(audit_model, logger="auditor_agent_logger")
        self.logger = base_agent.logger
        self.agent = base_agent.initagent()
        self.dataset = dataset
        # Set by doubt_decision: True when its unsafe result rests only on failed LLM calls,
        # so the caller can record the sample as an error instead of unsafe.
        self.verdict_failed = False
        # Also set by doubt_decision, for the decision trace: how the verdict was reached.
        self.decision_source = ""
        self.final_decision_reason = ""

        self.doubt_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.optimize_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.optimize_reused_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.single_tool_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.final_decision_prompt = ChatPromptTemplate.from_template("{prompt}")

        self.doubt_llm = self.agent.with_structured_output(
            DoubtReviewBatchOutput, method="function_calling"
        )
        self.optimize_llm = self.agent.with_structured_output(
            ToolSpec, method="function_calling"
        )
        self.optimize_reused_llm = self.agent.with_structured_output(
            DoubtReviewBatchOutput, method="function_calling"
        )
        self.single_tool_llm = self.agent.with_structured_output(
            DoubtReviewBatchOutput, method="function_calling"
        )
        self.final_decision_llm = self.agent.with_structured_output(
            FinalDecisionOutput, method="function_calling"
        )

        # 批处理 + 落盘缓存包装：同一样本的全部工具合一次质疑调用，重复提示词命中缓存
        self.doubt_chain = cached_chain(self.doubt_prompt | self.doubt_llm, audit_model, DoubtReviewBatchOutput)
        self.optimize_chain = cached_chain(self.optimize_prompt | self.optimize_llm, audit_model, ToolSpec)
        self.optimize_reused_chain = cached_chain(
            self.optimize_reused_prompt | self.optimize_reused_llm, audit_model, DoubtReviewBatchOutput
        )
        self.single_tool_chain = cached_chain(
            self.single_tool_prompt | self.single_tool_llm, audit_model, DoubtReviewBatchOutput
        )
        self.final_decision_chain = cached_chain(
            self.final_decision_prompt | self.final_decision_llm, audit_model, FinalDecisionOutput
        )

    def search_original_tool(self, optimized_tool: Dict[str, Any]) -> Dict[str, Any]:
        tool_memory = self.tool_repo.load()
        category_tool_set = optimized_tool.get("category", "")
        for tool in tool_memory.get(category_tool_set, []):
            if tool.get("tool_name") == optimized_tool.get("tool_name"):
                return tool
        return {}

    def _invoke_structured(self, chain, prompt: str, default_value, err_msg: str):
        try:
            result = chain.invoke({"prompt": prompt})
        except Exception as e:
            self.logger.error(f"{err_msg}: {str(e)}")
            return default_value
        # The tool-call parser returns None when the model makes no tool call.
        if result is None:
            self.logger.error(f"{err_msg}: model returned no structured output")
            return default_value
        return result

    def _review_batch(
        self, chain, prompt: str, count: int, stage: str
    ) -> List[Optional[DoubtReviewOutput]]:
        """One batched review call covering `count` tools; a None entry marks a failed review (fail-closed)."""
        batch: Optional[DoubtReviewBatchOutput] = self._invoke_structured(
            chain, prompt, None, f"Failed to run {stage}"
        )
        reviews = getattr(batch, "reviews", None)
        if not isinstance(reviews, list) or len(reviews) != count:
            if batch is not None:
                got = len(reviews) if isinstance(reviews, list) else "none"
                self.logger.error(f"{stage}: expected {count} reviews, got {got}")
            return [None] * count
        return list(reviews)

    def auto_optimize_risky_tool(
        self,
        tool_info: Dict[str, Any],
        reason: str,
        data: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], bool]:
        prompt = TOOL_DOUBT_AUTO_OPTIMIZE_PROMPT.format(
            request=data["request"],
            agent_actions=data["agent_actions"],
            tool=json.dumps(tool_info, indent=2, ensure_ascii=False),
            reason=reason,
        )
        supplement = get_specific_prompt_supplement(
            "TOOL_DOUBT_AUTO_OPTIMIZE", self.dataset
        )
        prompt = compose_prompt(prompt, supplement)

        optimized_tool: Optional[ToolSpec] = self._invoke_structured(
            self.optimize_chain,
            prompt,
            None,
            "Failed to run auto_optimize_risky_tool",
        )
        if optimized_tool is None or not optimized_tool.tool_code.strip():
            return tool_info, False

        optimized_dict = optimized_tool.model_dump()
        # Keep the original identity if the model omitted it, so the library update can find the tool.
        for key in ("category", "tool_name"):
            optimized_dict[key] = optimized_dict[key] or tool_info.get(key, "")
        optimized_dict["original_tool_description"] = tool_info.get(
            "tool_description", ""
        )
        optimized_dict["original_tool_code"] = tool_info.get("tool_code", "")
        optimized_dict["original_doubt_result"] = {
            "is_safe": "False",
            "reason": reason,
        }
        return optimized_dict, True

    def doubt_tool(
        self,
        feedback: List[Tuple[Dict, bool, bool]],
        data: Dict[str, Any],
    ) -> List[Tuple[Dict, Dict, bool, bool, int]]:
        # 批处理：所有新工具合一次质疑调用，所有复用工具（存量 vs 改写）合一次质疑调用；
        # 有风险工具的自动优化仍是逐工具的（条件触发）。
        doubt_results = []
        if not feedback:
            return doubt_results

        review_by_index: Dict[int, Optional[DoubtReviewOutput]] = {}
        new_indexes = [i for i, item in enumerate(feedback) if not item[1]]
        reused_indexes = [i for i, item in enumerate(feedback) if item[1]]

        if new_indexes:
            prompt = TOOL_DOUBT_PROMPT.format(
                request=data["request"],
                agent_actions=data["agent_actions"],
                tools=json.dumps(
                    [feedback[i][0] for i in new_indexes], indent=2, ensure_ascii=False
                ),
            )
            supplement = get_specific_prompt_supplement("TOOL_DOUBT", self.dataset)
            prompt = compose_prompt(prompt, supplement)
            reviews = self._review_batch(
                self.doubt_chain, prompt, len(new_indexes), "tool review batch"
            )
            for i, review in zip(new_indexes, reviews):
                review_by_index[i] = review

        if reused_indexes:
            pairs = []
            for i in reused_indexes:
                tool_info = feedback[i][0]
                system_tool = self.search_original_tool(tool_info)
                if not system_tool:
                    system_tool = tool_info
                pairs.append({"existing": system_tool, "optimized": tool_info})
            prompt = TOOL_DOUBT_OPTIMIZE_PROMPT.format(
                request=data["request"],
                agent_actions=data["agent_actions"],
                tool_pairs=json.dumps(pairs, indent=2, ensure_ascii=False),
            )
            supplement = get_specific_prompt_supplement(
                "TOOL_DOUBT_OPTIMIZE", self.dataset
            )
            prompt = compose_prompt(prompt, supplement)
            reviews = self._review_batch(
                self.optimize_reused_chain,
                prompt,
                len(reused_indexes),
                "reused tool review batch",
            )
            for i, review in zip(reused_indexes, reviews):
                review_by_index[i] = review

        for i, item in enumerate(feedback):
            tool_info, is_reused, execution_result = item
            tool_has_risk = 0
            review = review_by_index.get(i)
            clean_response: Dict[str, Any]

            if not is_reused:
                clean_response = (
                    review.model_dump() if review else _failed_verdict("Tool review")
                )

                # A failed review stays unsafe; there is no risk reason to optimize against.
                if (
                    review is not None
                    and normalize_is_safe(clean_response.get("is_safe", "")) is False
                ):
                    tool_has_risk = 1
                    original_tool_description = tool_info.get("tool_description", "")
                    original_tool_code = tool_info.get("tool_code", "")
                    original_doubt_result = clean_response.copy()

                    optimized_tool, success = self.auto_optimize_risky_tool(
                        tool_info=tool_info,
                        reason=clean_response.get(
                            "reason", "The tool poses a security risk."
                        ),
                        data=data,
                    )

                    if success:
                        optimized_tool["original_tool_description"] = (
                            original_tool_description
                        )
                        optimized_tool["original_tool_code"] = original_tool_code
                        optimized_tool["original_doubt_result"] = original_doubt_result

                        tool_info = optimized_tool
                        clean_response = {
                            "is_safe": "True",
                            "reason": "The tool has been automatically optimized and passed the review.",
                        }
                        is_reused = False
                    else:
                        tool_info = {**tool_info, "optimization_failed": True}

            else:
                clean_response = (
                    review.model_dump()
                    if review
                    else _failed_verdict("Reused tool review")
                )

                if (
                    review is not None
                    and normalize_is_safe(clean_response.get("is_safe", "")) is False
                ):
                    tool_has_risk = 1
                    original_tool_description = tool_info.get("tool_description", "")
                    original_tool_code = tool_info.get("tool_code", "")
                    original_doubt_result = clean_response.copy()

                    reoptimized_tool, success = self.auto_optimize_risky_tool(
                        tool_info=tool_info,
                        reason=clean_response.get(
                            "reason", "The optimized tool still poses a security risk."
                        ),
                        data=data,
                    )

                    if success:
                        reoptimized_tool["original_tool_description"] = (
                            original_tool_description
                        )
                        reoptimized_tool["original_tool_code"] = original_tool_code
                        reoptimized_tool["original_doubt_result"] = (
                            original_doubt_result
                        )

                        tool_info = reoptimized_tool
                        clean_response = {
                            "is_safe": "True",
                            "reason": "The tool has been automatically re-optimized and passed the review.",
                        }
                    else:
                        tool_info = {**tool_info, "optimization_failed": True}

            doubt_results.append(
                (
                    tool_info,
                    clean_response,
                    is_reused,
                    execution_result,
                    tool_has_risk,
                )
            )

        return doubt_results

    def doubt_single_tool(
        self,
        tool_info: Dict[str, Any],
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        # The second check assumes the tool was optimized; an unoptimized risky tool must not pass it.
        if tool_info.get("optimization_failed"):
            return _failed_verdict("Automatic optimization")

        prompt = TOOL_DOUBT_PROMPT.format(
            request=data["request"],
            agent_actions=data["agent_actions"],
            tools=json.dumps([tool_info], indent=2, ensure_ascii=False),
        )
        prompt += (
            "**Previously, it was explicitly required not to produce tools with the above CWE risks during tool production, "
            "and risky tools were optimized. You should be cautious about the decision that the tool still poses risks, "
            "and any excessive protection of the tool is unacceptable.**"
        )
        supplement = get_specific_prompt_supplement("TOOL_DOUBT_SINGLE", self.dataset)
        prompt = compose_prompt(prompt, supplement)

        batch: Optional[DoubtReviewBatchOutput] = self._invoke_structured(
            self.single_tool_chain,
            prompt,
            None,
            "Failed to run doubt_single_tool",
        )
        reviews = getattr(batch, "reviews", None)
        if isinstance(reviews, list) and reviews:
            return reviews[0].model_dump()
        return _failed_verdict("Second check")

    def doubt_decision(
        self,
        data: Dict[str, Any],
        doubt_tool_result: List[Tuple[Dict, Dict, bool, bool, int]],
        action_result: str,
        debug_mode: bool = True,
        debug_doubt_tool_path: str = "debug_doubt_tool_agentharmbenign.log",
        debug_decision_path: str = "debug_doubt_decision_agentharmbenign.log",
    ) -> Tuple[List[Dict], bool]:
        tool_set = [item[0] for item in doubt_tool_result]
        self.verdict_failed = False
        # For the decision trace: how this verdict was reached.
        self.decision_source = ""
        self.final_decision_reason = ""
        self.final_decision_applied_rules: List[str] = []

        for item in doubt_tool_result:
            tool_info = item[0]
            doubt_result = item[1]
            is_reused = item[2]
            execution_result = item[3]

            if (
                execution_result is True
                or normalize_is_safe(doubt_result.get("is_safe", "")) is False
            ):
                # Error only if no tool gives a real risk signal (execution hit or a genuine unsafe review).
                self.verdict_failed = not any(
                    other[3] is True
                    or (
                        normalize_is_safe(other[1].get("is_safe", "")) is False
                        and not other[1].get("llm_failed")
                    )
                    for other in doubt_tool_result
                )
                risk_record = {
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "task_id": data.get("id", "unknown"),
                    "user_request": data["request"],
                    "agent_actions": data["agent_actions"],
                    "user_level": data.get("user_level", "user"),
                    "detected_by_tool": {
                        "tool_name": tool_info.get("tool_name", "unknown"),
                        "tool_category": tool_info.get("category", "unknown"),
                        "tool_description": tool_info.get("tool_description", ""),
                        "is_reused_tool": is_reused,
                    },
                    "risk_source": "",
                    "risk_details": {},
                }

                if (
                    execution_result is True
                    and normalize_is_safe(doubt_result.get("is_safe", "")) is False
                ):
                    risk_record["risk_source"] = "both"
                    risk_record["risk_details"] = {
                        "tool_execution_result": "Risk detected (Returns True)",
                        "doubt_agent_result": "The doubt failed.",
                        "doubt_agent_reason": doubt_result.get(
                            "reason", "No reason provided"
                        ),
                        "conclusion": f"Tool '{tool_info.get('tool_name')}' detected risk during execution, and AuditorAgent also deemed it unsafe.",
                    }
                elif execution_result is True:
                    risk_record["risk_source"] = "tool_execution"
                    risk_record["risk_details"] = {
                        "tool_execution_result": "Risk detected (Returns True)",
                        "doubt_agent_result": "The doubt approved.",
                        "conclusion": f"Tool '{tool_info.get('tool_name')}' detected command security risk during execution.",
                    }
                else:
                    risk_record["risk_source"] = "doubt_agent"
                    risk_record["risk_details"] = {
                        "tool_execution_result": "No risk detected (Returns False)",
                        "doubt_agent_result": "The doubt failed.",
                        "doubt_agent_reason": doubt_result.get(
                            "reason", "No reason provided"
                        ),
                        "conclusion": f"Tool '{tool_info.get('tool_name')}' was deemed unsafe or inappropriate by AuditorAgent.",
                    }

                if debug_mode:
                    with open(debug_doubt_tool_path, "w", encoding="utf-8") as f:
                        f.write("=" * 80 + "\n")
                        f.write(f"[RISK DETECTED BY: {tool_info.get('tool_name')}]\n")
                        f.write(
                            json.dumps(risk_record, ensure_ascii=False, indent=2) + "\n"
                        )
                        f.write("=" * 80 + "\n\n")
                self.decision_source = risk_record["risk_source"]
                self.final_decision_reason = risk_record["risk_details"]["conclusion"]
                return tool_set, True

        base_prompt = DOUBT_DECISION_PROMPT.format(
            request=data["request"],
            agent_actions=data["agent_actions"],
            approved_tools=json.dumps(tool_set, indent=2, ensure_ascii=False),
            action_result=action_result,
        )
        supplement = get_specific_prompt_supplement("DOUBT_DECISION", self.dataset)
        prompt = compose_prompt(base_prompt, supplement)

        decision: Optional[FinalDecisionOutput] = self._invoke_structured(
            self.final_decision_chain,
            prompt,
            None,
            "Failed to run doubt_decision",
        )
        clean_response = (
            decision.model_dump() if decision else _failed_verdict("Final decision")
        )
        self.verdict_failed = decision is None
        self.decision_source = "final_decision"
        self.final_decision_reason = clean_response.get("reason", "")
        self.final_decision_applied_rules = list(decision.applied_rules) if decision else []
        self.logger.info(
            f"Doubt Decision Result: {json.dumps(clean_response, ensure_ascii=False)}"
        )
        if normalize_is_safe(clean_response.get("is_safe", "")) is False:
            if debug_mode:
                with open(debug_decision_path, "w", encoding="utf-8") as f:
                    f.write("=" * 80 + "\n")
                    f.write("[TOOL PASS BUT DECISION REFUSED]\n")
                    f.write(
                        json.dumps(clean_response, ensure_ascii=False, indent=2) + "\n"
                    )
                    f.write("=" * 80 + "\n\n")
            return tool_set, True

        return tool_set, False
