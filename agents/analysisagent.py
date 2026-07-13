import json
import time
import argparse
from functools import lru_cache
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from agent import BaseAgent
from prompts.base_prompts import RISK_ANALYSIS_PROMPT, TOOL_PLAN_PROMPT
from prompts.prompt_utils import compose_prompt, get_specific_prompt_supplement


class RiskItem(BaseModel):
    category: str = Field(default="")
    description: str = Field(default="")


class RiskAnalysisOutput(BaseModel):
    risks: List[RiskItem] = Field(default_factory=list)
    new_risks: Literal["yes", "no"] = "no"
    need_tools: Literal["yes", "no"] = "no"
    reason: str = ""


class ToolSpec(BaseModel):
    category: str = Field(default="")
    tool_name: str = Field(default="")
    tool_description: str = Field(default="")
    require: List[str] = Field(default_factory=list)
    tool_code: str = Field(default="")


class ToolPlanOutput(BaseModel):
    tools: List[ToolSpec] = Field(default_factory=list)


class AnalysisAgent(BaseAgent):
    def __init__(
        self,
        analysis_model,
        risk_memory_path: str = "lifelong_library/risks.json",
        dataset: str = "",
    ):
        super().__init__(model_name=analysis_model, logger="analysis_agent_logger")
        self.risk_memory_path = risk_memory_path
        self.dataset = dataset

        self.agent = BaseAgent(
            model_name=analysis_model, logger="analysis_agent_logger"
        ).initagent()
        # We compose full prompts (base + dataset supplement) before invoking.
        self.risk_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.tool_plan_prompt = ChatPromptTemplate.from_template("{prompt}")
        self.risk_llm = self.agent.with_structured_output(
            RiskAnalysisOutput, method="function_calling"
        )
        self.tool_plan_llm = self.agent.with_structured_output(
            ToolPlanOutput, method="function_calling"
        )
        self.risk_chain = self.risk_prompt | self.risk_llm
        self.tool_plan_chain = self.tool_plan_prompt | self.tool_plan_llm

    def _load_risk_memory(self) -> Dict[str, Any]:
        with open(self.risk_memory_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def risk_analysis(
        self, request: str, agent_actions: str, risk_categories: str
    ) -> Dict[str, Any]:
        base_prompt = RISK_ANALYSIS_PROMPT.format(
            request=request,
            agent_actions=agent_actions,
            risk_categories=risk_categories,
        )
        supplement = get_specific_prompt_supplement("RISK_ANALYSIS", self.dataset)
        prompt = compose_prompt(base_prompt, supplement)
        try:
            result: RiskAnalysisOutput = self.risk_chain.invoke({"prompt": prompt})
            return result.model_dump()
        except Exception as e:
            self.logger.error(f"Failed to run risk analysis: {str(e)}")
            return {
                "need_tools": "no",
                "reason": "risk analysis failed",
                "new_risks": "no",
                "risks": [],
            }

    def safetytool_definition(
        self, risk: Dict[str, Any], user_request: str, agent_actions: str
    ) -> Dict[str, Any]:
        base_prompt = TOOL_PLAN_PROMPT.format(
            request=user_request,
            agent_actions=agent_actions,
            risk_analysis=json.dumps(risk, indent=2, ensure_ascii=False),
        )
        supplement = get_specific_prompt_supplement("TOOL_PLAN", self.dataset)
        prompt = compose_prompt(base_prompt, supplement)
        try:
            result: ToolPlanOutput = self.tool_plan_chain.invoke({"prompt": prompt})
            return result.model_dump()
        except Exception as e:
            self.logger.error(f"Failed to run tool plan: {str(e)}")
            return {"tools": []}

    def analysis(
        self,
        args: argparse.Namespace,
        data: Dict[str, Any],
        present_tools: List[Dict] = None,
    ):
        user_request = data.get("request", "")
        agent_actions = data.get("agent_actions", "")

        analysis_result = self.risk_analysis(
            request=user_request,
            agent_actions=agent_actions,
            risk_categories=self._load_risk_memory(),
        )
        self.logger.info(
            f"Risk Analysis Result: {json.dumps(analysis_result, ensure_ascii=False)}"
        )
        need_tools = analysis_result.get("need_tools", "no")

        if need_tools == "yes":
            time.sleep(1)
            tool_result = self.safetytool_definition(
                risk=analysis_result.get("risks", []),
                user_request=user_request,
                agent_actions=agent_actions,
            )
            self.logger.info(
                f"Generate guardrail tools: {json.dumps(tool_result, ensure_ascii=False)}"
            )
        else:
            tool_result = {"tools": []}
        return tool_result, analysis_result
