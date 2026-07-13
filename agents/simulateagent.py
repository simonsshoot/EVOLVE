import json
import os
import time
import argparse
from typing import List, Dict, Any, Tuple, Optional
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage


from prompts.base_prompts import SIMULATE_AGENT_PROMPT
from agent import BaseAgent


class SimulateOutput(BaseModel):
    agent_actions: str = Field(default="", description="simulate agent's actions")
    environment: str = Field(
        default="", description="simulate execution environment/context"
    )


class SimulateAgent(BaseAgent):
    def __init__(self, simulate_model: str):
        super().__init__(model_name=simulate_model)
        self.agent = BaseAgent(
            simulate_model, logger="simulate_agent_logger"
        ).initagent()

        self.simulate_prompt = ChatPromptTemplate.from_template(SIMULATE_AGENT_PROMPT)
        self.simulate_llm = self.agent.with_structured_output(
            SimulateOutput, method="function_calling"
        )
        self.simulate_chain = self.simulate_prompt | self.simulate_llm

    def _format_tools(self, present_tools: Optional[List[Dict[str, Any]]]) -> str:
        if not present_tools:
            return "No tools available."

        lines = ["Available tools:"]
        for tool in present_tools:
            lines.append(
                f"- {tool.get('tool_name', 'unknown')}: {tool.get('description', 'No description')}"
            )
            params = tool.get("parameters", {})
            if params:
                lines.append(f"  Parameters: {json.dumps(params, ensure_ascii=False)}")
        return "\n".join(lines)

    def simulate(
        self, data: Dict[str, Any], present_tools: List[Dict] = None
    ) -> Dict[str, Any]:
        tools_desc = self._format_tools(present_tools)
        result: SimulateOutput = self.simulate_chain.invoke(
            {
                "request": data["request"],
                "tools": tools_desc,
            }
        )
        simu_data = dict(data)
        simu_data["agent_actions"] = result.agent_actions
        simu_data["environment"] = result.environment
        return simu_data


class SimulateMultiRoundAgent(BaseAgent):
    def __init__(self, model_name: str, logger=None):
        self.logger = logger
        self.agent = BaseAgent(
            model_name=model_name, logger="simulate_agent_logger"
        ).initagent()
        self.structured_llm = self.agent.with_structured_output(
            SimulateOutput, method="function_calling"
        )
        self.history: List[Any] = []

        self.system_prompt = SystemMessage(
            content=(
                "You are a mock agent, responsible for multi-turn interaction with users. "
                "In each round of dialogue, you need to output the actions that the agent might perform "
                "based on the user's request and the dialogue history. "
                "Please ensure that your responses are coherent and take into account the previous dialogue context."
            )
        )

    def _build_user_prompt(
        self, request: str, extra_prompt: Optional[str] = None
    ) -> str:
        if extra_prompt:
            return (
                f"User request:\n{request}\n\n"
                f"Current round instruction:\n{extra_prompt}\n\n"
                "Please return structured output with fields: agent_actions, environment."
            )
        return (
            f"User request:\n{request}\n\n"
            "Please return structured output with fields: agent_actions, environment."
        )

    def multi_round_simulate(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        data:
            {
                "request": "...",
                "description": ["round1 prompt", "round2 prompt", ...],
                ...
            }
        """
        imple_data = dict(data)
        imple_data["agent_actions"] = [""]
        imple_data["init"] = [""]

        prompts_set = data.get("description", [])
        if isinstance(prompts_set, str):
            prompts_set = [prompts_set]

        self.history = [self.system_prompt]
        user_initial_prompt = HumanMessage(
            content=self._build_user_prompt(data["request"])
        )
        self.history.append(user_initial_prompt)

        for round_num, prompt in enumerate(prompts_set):
            try:
                if round_num > 0:
                    self.history.append(HumanMessage(content=prompt))

                result: SimulateOutput = self.structured_llm.invoke(self.history)

                imple_data["agent_actions"].append(result.agent_actions)
                imple_data["init"].append(result.environment)
                self.history.append(
                    AIMessage(content=result.model_dump_json(ensure_ascii=False))
                )

            except Exception as e:
                if self.logger:
                    self.logger.error(f"Exception while multi round simulate: {str(e)}")
                break

        return imple_data

    def __warp_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        description_list = data.get("description", [])
        action_list = data.get("agent_actions", [])
        init_list = data.get("init", [])

        return {
            "user_identity": data.get("user_identity", ""),
            "labels": data.get("labels", ""),
            "request": (
                " && ".join(description_list)
                if isinstance(description_list, list)
                else str(description_list)
            ),
            "agent_actions": (
                " && ".join(action_list)
                if isinstance(action_list, list)
                else str(action_list)
            ),
            "init": (
                " && ".join(init_list)
                if isinstance(init_list, list)
                else str(init_list)
            ),
        }

    def simulate(self, data: Dict[str, Any]) -> str:
        simulated = self.multi_round_simulate(data)
        wrapped = self.__warp_data(simulated)
        return json.dumps(wrapped, ensure_ascii=False, indent=2)
