import json
import argparse
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from agent import BaseAgent
from llm_cache import cached_chain
from prompts.base_prompts import RISK_ANALYSIS_PROMPT, TOOL_PLAN_PROMPT
from prompts.prompt_utils import compose_prompt, get_specific_prompt_supplement


class RiskItem(BaseModel):
    category: str = Field(default="", description="Risk category name")
    description: str = Field(default="", description="Detailed description of the risk")


class RiskAnalysisOutput(BaseModel):
    risks: List[RiskItem] = Field(default_factory=list, description="Identified risks; empty list if there is no real risk")
    new_risks: Literal["yes", "no"] = Field(default="no", description='"yes" if any risk category is not among the existing categories')
    need_tools: Literal["yes", "no"] = Field(default="no", description='"yes" only if security tools are needed for automated detection/protection')
    reason: str = Field(default="", description="Why tools are or are not needed")


class ToolSpec(BaseModel):
    category: str = Field(default="", description="Risk category the tool protects against")
    tool_name: str = Field(default="", description="Must equal the function name in tool_code")
    tool_description: str = Field(default="", description="What the tool detects and how")
    require: List[str] = Field(default_factory=list, description="Python modules the code imports, e.g. ['re']")
    tool_code: str = Field(default="", description="Python source of def <tool_name>(query: str, action: str) -> bool; True = risk detected")


class ToolPlanOutput(BaseModel):
    tools: List[ToolSpec] = Field(default_factory=list, description="Designed security tools")


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
        # 落盘缓存包装：重复样本/重跑时相同提示词直接命中缓存
        self.risk_chain = cached_chain(self.risk_prompt | self.risk_llm, analysis_model, RiskAnalysisOutput)
        self.tool_plan_chain = cached_chain(self.tool_plan_prompt | self.tool_plan_llm, analysis_model, ToolPlanOutput)

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
