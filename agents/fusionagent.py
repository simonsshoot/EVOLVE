import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from agent import BaseAgent
from llm_cache import cached_chain
from prompts.base_prompts import (
    TOOL_SEARCH_PROMPT,
    TOOL_REUSE_PROMPT,
)


class ToolItem(BaseModel):
    category: str = Field(description="Risk category the tool protects against")
    tool_name: str = Field(description="Function name in tool_code")
    tool_description: str = Field(default="", description="What the tool detects and how")
    require: List[str] = Field(default_factory=list, description="Python modules the code imports, e.g. ['re']")
    tool_code: str = Field(default="", description="Python source of def <tool_name>(query: str, action: str) -> bool; True = risk detected")
    if_match: Literal["yes", "no"] = Field(default="no", description='"yes" if a similar tool exists among the existing tools')
    match_tool_name: Optional[str] = Field(default=None, description='Name of the matched existing tool; "" if none')


class ToolBatch(BaseModel):
    tools: List[ToolItem] = Field(default_factory=list, description="Tools with their original fields")


class ReusedTool(BaseModel):
    category: str = Field(default="", description="Category of the existing tool; keep it unchanged")
    tool_name: str = Field(default="", description="Function name in tool_code; keep the existing tool's name")
    tool_description: str = Field(default="", description="What the tool detects and how")
    require: List[str] = Field(default_factory=list, description="Python modules the code imports, e.g. ['re']")
    tool_code: str = Field(default="", description="Python source of def <tool_name>(query: str, action: str) -> bool; True = risk detected")


class ToolMemoryRepository:
    def __init__(self, tool_memory_path: str):
        self.tool_memory_path = Path(tool_memory_path)

    def load(self) -> Dict[str, Any]:
        with self.tool_memory_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def load_relevant_tools(self, tool_result: Dict[str, Any]) -> Dict[str, Any]:
        tool_memory = self.load()
        categories = [t.get("category") for t in tool_result.get("tools", [])]
        return {cat: tool_memory[cat] for cat in categories if cat in tool_memory}


class FusionAgent:
    def __init__(self, tool_memory_path: str, fusion_model: str = "deepseek-chat"):
        self.tool_repo = ToolMemoryRepository(tool_memory_path)
        self.agent = BaseAgent(fusion_model, logger="fusion_agent_logger").initagent()

        self.search_prompt = ChatPromptTemplate.from_template(TOOL_SEARCH_PROMPT)
        self.reuse_prompt = ChatPromptTemplate.from_template(TOOL_REUSE_PROMPT)
        self.search_llm = self.agent.with_structured_output(
            ToolBatch, method="function_calling"
        )
        self.reuse_llm = self.agent.with_structured_output(
            ReusedTool, method="function_calling"
        )
        # 落盘缓存包装
        self.search_chain = cached_chain(self.search_prompt | self.search_llm, fusion_model, ToolBatch)
        self.reuse_chain = cached_chain(self.reuse_prompt | self.reuse_llm, fusion_model, ReusedTool)

    def search_tool(self, tool_result: Dict[str, Any]) -> ToolBatch:
        if not tool_result.get("tools"):
            return ToolBatch()

        relevant_tools = self.tool_repo.load_relevant_tools(tool_result)
        return self.search_chain.invoke(
            {
                "user_tools": json.dumps(tool_result, ensure_ascii=False, indent=2),
                "existing_tools": json.dumps(
                    relevant_tools, ensure_ascii=False, indent=2
                ),
            }
        )

    def reuse_tool(
        self, clean_relevant_tools: ToolBatch
    ) -> List[tuple[Dict[str, Any], bool]]:
        tool_memory = self.tool_repo.load()
        tool_workflow: List[tuple[Dict[str, Any], bool]] = []
        if not clean_relevant_tools.tools or len(clean_relevant_tools.tools) == 0:
            return tool_workflow
        for tool in clean_relevant_tools.tools:
            tool_data = tool.model_dump() if hasattr(tool, "model_dump") else dict(tool)
            match_flag = (
                tool_data.get("is_match")
                or tool_data.get("if_match")
                or tool_data.get("match")
                or "no"
            )

            if str(match_flag).lower() != "yes":
                tool_workflow.append((tool_data, False))
                continue
            matched_tool_info = None
            category = tool_data.get("category", "")
            matched = tool_data.get("match_tool_name")
            if category in tool_memory:
                for cate_tool in tool_memory[category]:
                    if cate_tool.get("tool_name") == matched:
                        matched_tool_info = cate_tool
                        break
            if matched_tool_info is None:
                tool_workflow.append((tool_data, False))
                continue
            optimized = self.reuse_chain.invoke(
                {
                    "user_tool": json.dumps(tool_data, ensure_ascii=False, indent=2),
                    "existing_tool": json.dumps(
                        matched_tool_info, ensure_ascii=False, indent=2
                    ),
                }
            )
            if optimized is None or not optimized.tool_code.strip():
                # No usable rewrite: reuse the existing tool as stored.
                reused = dict(matched_tool_info)
            else:
                reused = optimized.model_dump()
            # The library update replaces the tool by (category, tool_name).
            reused["category"] = category
            reused["tool_name"] = reused.get("tool_name") or matched
            tool_workflow.append((reused, True))
        return tool_workflow
