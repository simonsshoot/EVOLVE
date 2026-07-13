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


class ToolMemoryRepository:
    def __init__(self, tool_memory_path: str):
        self.tool_memory_path = tool_memory_path

    def load(self) -> Dict[str, Any]:
        with open(self.tool_memory_path, "r", encoding="utf-8") as f:
            return json.load(f)


class DoubtReviewOutput(BaseModel):
    is_safe: Literal["True", "False"] = "True"
    reason: str = ""


class ToolSpec(BaseModel):
    category: str = ""
    tool_name: str = ""
    tool_description: str = ""
    require: List[str] = Field(default_factory=list)
    tool_code: str = ""


class FinalDecisionOutput(BaseModel):
    is_safe: Literal["True", "False"] = "True"
    reason: str = ""


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

        self.doubt_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.optimize_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.optimize_reused_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.single_tool_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.final_decision_prompt = ChatPromptTemplate.from_template("{prompt}")

        self.doubt_llm = self.agent.with_structured_output(
            DoubtReviewOutput, method="function_calling"
        )
        self.optimize_llm = self.agent.with_structured_output(
            ToolSpec, method="function_calling"
        )
        self.optimize_reused_llm = self.agent.with_structured_output(
            ToolSpec, method="function_calling"
        )
        self.single_tool_llm = self.agent.with_structured_output(
            DoubtReviewOutput, method="function_calling"
        )
        self.final_decision_llm = self.agent.with_structured_output(
            FinalDecisionOutput, method="function_calling"
        )

        self.doubt_chain = self.doubt_prompt | self.doubt_llm
        self.optimize_chain = self.optimize_prompt | self.optimize_llm
        self.optimize_reused_chain = (
            self.optimize_reused_prompt | self.optimize_reused_llm
        )
        self.single_tool_chain = self.single_tool_prompt | self.single_tool_llm
        self.final_decision_chain = self.final_decision_prompt | self.final_decision_llm

    def search_original_tool(self, optimized_tool: Dict[str, Any]) -> Dict[str, Any]:
        tool_memory = self.tool_repo.load()
        category_tool_set = optimized_tool.get("category", "")
        for tool in tool_memory.get(category_tool_set, []):
            if tool.get("tool_name") == optimized_tool.get("tool_name"):
                return tool
        return {}

    def _invoke_structured(self, chain, prompt: str, default_value, err_msg: str):
        try:
            return chain.invoke({"prompt": prompt})
        except Exception as e:
            print(f"{err_msg}: {str(e)}")
            return default_value

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

        optimized_tool: ToolSpec = self._invoke_structured(
            self.optimize_chain,
            prompt,
            ToolSpec(),
            "Failed to run auto_optimize_risky_tool",
        )

        optimized_dict = optimized_tool.model_dump()
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
        doubt_results = []

        for item in feedback:
            tool_info, is_reused, execution_result = item
            tool_has_risk = 0
            clean_response = {"is_safe": "True", "reason": ""}

            if not is_reused:
                prompt = TOOL_DOUBT_PROMPT.format(
                    request=data["request"],
                    agent_actions=data["agent_actions"],
                    tool=json.dumps(tool_info, indent=2, ensure_ascii=False),
                )
                supplement = get_specific_prompt_supplement("TOOL_DOUBT", self.dataset)
                prompt = compose_prompt(prompt, supplement)

                review: DoubtReviewOutput = self._invoke_structured(
                    self.doubt_chain,
                    prompt,
                    DoubtReviewOutput(),
                    "Failed to run doubt_tool",
                )
                clean_response = review.model_dump()

                if normalize_is_safe(clean_response.get("is_safe", "")) is False:
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
                system_tool = self.search_original_tool(tool_info)
                if not system_tool:
                    system_tool = tool_info

                prompt = TOOL_DOUBT_OPTIMIZE_PROMPT.format(
                    request=data["request"],
                    agent_actions=data["agent_actions"],
                    tool=json.dumps(system_tool, indent=2, ensure_ascii=False),
                    optimized_tool=json.dumps(tool_info, indent=2, ensure_ascii=False),
                )
                supplement = get_specific_prompt_supplement(
                    "TOOL_DOUBT_OPTIMIZE", self.dataset
                )
                prompt = compose_prompt(prompt, supplement)

                review: DoubtReviewOutput = self._invoke_structured(
                    self.optimize_reused_chain,
                    prompt,
                    DoubtReviewOutput(),
                    "Failed to run doubt_tool for reused tool",
                )
                clean_response = review.model_dump()

                if normalize_is_safe(clean_response.get("is_safe", "")) is False:
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
        prompt = TOOL_DOUBT_PROMPT.format(
            request=data["request"],
            agent_actions=data["agent_actions"],
            tool=json.dumps(tool_info, indent=2, ensure_ascii=False),
        )
        prompt += (
            "**Previously, it was explicitly required not to produce tools with the above CWE risks during tool production, "
            "and risky tools were optimized. You should be cautious about the decision that the tool still poses risks, "
            "and any excessive protection of the tool is unacceptable.**"
        )
        supplement = get_specific_prompt_supplement("TOOL_DOUBT_SINGLE", self.dataset)
        prompt = compose_prompt(prompt, supplement)

        review: DoubtReviewOutput = self._invoke_structured(
            self.single_tool_chain,
            prompt,
            DoubtReviewOutput(),
            "Failed to run doubt_single_tool",
        )
        return review.model_dump()

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

        for item in doubt_tool_result:
            tool_info = item[0]
            doubt_result = item[1]
            is_reused = item[2]
            execution_result = item[3]

            if (
                execution_result is True
                or normalize_is_safe(doubt_result.get("is_safe", "")) is False
            ):
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
                return tool_set, True

        base_prompt = DOUBT_DECISION_PROMPT.format(
            request=data["request"],
            agent_actions=data["agent_actions"],
            approved_tools=json.dumps(tool_set, indent=2, ensure_ascii=False),
            action_result=action_result,
        )
        supplement = get_specific_prompt_supplement("DOUBT_DECISION", self.dataset)
        prompt = compose_prompt(base_prompt, supplement)

        decision: FinalDecisionOutput = self._invoke_structured(
            self.final_decision_chain,
            prompt,
            FinalDecisionOutput(),
            "Failed to run doubt_decision",
        )
        clean_response = decision.model_dump()
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
