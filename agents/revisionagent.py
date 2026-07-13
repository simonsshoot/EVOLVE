import json
import os
import time
import argparse
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from agent import BaseAgent
from prompts.base_prompts import (
    REFINE_ACTION_PROMPT,
)


class ReviseOutput(BaseModel):
    refined_action: str = Field(default="", description="refined agent action")


class RevisionAgent(BaseAgent):
    def __init__(self, revision_model: str):
        super().__init__(model_name=revision_model)
        self.agent = BaseAgent(
            revision_model, logger="revision_agent_logger"
        ).initagent()

        self.revise_prompt = ChatPromptTemplate.from_template(REFINE_ACTION_PROMPT)
        self.revise_llm = self.agent.with_structured_output(ReviseOutput)
        self.revise_chain = self.revise_prompt | self.revise_llm

    def revise(self, data: Dict[str, Any], risk_analysis: Dict[str, Any]) -> str:
        user_request = data.get("user_request", "")
        agent_action = data.get("agent_action", "")
        risk_summary = risk_analysis.get("risks", "")

        result: ReviseOutput = self.revise_chain.invoke(
            {
                "user_request": user_request,
                "agent_action": agent_action,
                "risk_summary": risk_summary,
            }
        )
        return result.refined_action
