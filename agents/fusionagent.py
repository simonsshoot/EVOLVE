import json
from typing import Dict, Any, List, Optional, Literal
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate

from agent import BaseAgent
from llm_cache import cached_chain
from tool_index import (
    CategoryAlias,
    ToolIndex,
    default_alias_path,
    default_embedder,
)
from agents.agent_utils import normalize_category
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
    if_match: Literal["yes", "no"] = Field(default="no", description='"yes" if a similar tool exists among the retrieved candidates')
    match_tool_name: Optional[str] = Field(default=None, description='Name of the matched candidate tool; "" if none')


class ToolBatch(BaseModel):
    tools: List[ToolItem] = Field(default_factory=list, description="Tools with their original fields")


class ReusedTool(BaseModel):
    category: str = Field(default="", description="Category of the existing tool; keep it unchanged")
    tool_name: str = Field(default="", description="Function name in tool_code; keep the existing tool's name")
    tool_description: str = Field(default="", description="What the tool detects and how")
    require: List[str] = Field(default_factory=list, description="Python modules the code imports, e.g. ['re']")
    tool_code: str = Field(default="", description="Python source of def <tool_name>(query: str, action: str) -> bool; True = risk detected")


def _tool_text(tool: Dict[str, Any]) -> str:
    """Embedding query/doc text for a tool: category | name: description."""
    return "%s | %s: %s" % (
        tool.get("category", ""),
        tool.get("tool_name", ""),
        tool.get("tool_description", ""),
    )


class FusionAgent:
    def __init__(
        self,
        tool_memory_path: str,
        fusion_model: str = "deepseek-chat",
        embedding_model: str = "text-embedding-3-small",
        recall_k: int = 5,
        alias_path: str = "",
        embed_fn=None,
    ):
        # 两阶段检索：一阶段 embedding 召回 top-K（无后端时词法回退），二阶段 LLM 在候选内确认
        self.tool_index = ToolIndex(
            tool_memory_path,
            alias=CategoryAlias(alias_path or default_alias_path(tool_memory_path)),
            embedder=(embed_fn, "injected") if embed_fn is not None else default_embedder(embedding_model),
            recall_k=recall_k,
        )
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

        # Stage 1: 每个待定工具从库内召回 top-K 相似工具（跨类目）
        queries = [_tool_text(t) for t in tool_result["tools"]]
        recalled = self.tool_index.recall(queries)
        candidates: Dict[str, List[Dict[str, Any]]] = {}
        seen = set()
        for records in recalled:
            for tool in records:
                cat = tool.get("category", "")
                dedup = (normalize_category(cat), tool.get("tool_name", ""))
                if dedup in seen:
                    continue
                seen.add(dedup)
                candidates.setdefault(cat, []).append(tool)

        # Stage 2: LLM 只在召回候选内做匹配确认
        return self.search_chain.invoke(
            {
                "user_tools": json.dumps(tool_result, ensure_ascii=False, indent=2),
                "existing_tools": json.dumps(
                    candidates, ensure_ascii=False, indent=2
                ),
            }
        )

    def reuse_tool(
        self, clean_relevant_tools: ToolBatch
    ) -> List[tuple[Dict[str, Any], bool]]:
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
            matched = tool_data.get("match_tool_name")
            found = (
                self.tool_index.find_tool(tool_data.get("category", ""), matched)
                if matched
                else None
            )
            if found is None:
                tool_workflow.append((tool_data, False))
                continue
            matched_tool_info, matched_key = found
            # 跨类目匹配：把变体类目折叠到已入库类目（写入持久别名表）
            if normalize_category(tool_data.get("category", "")) != normalize_category(matched_key):
                self.tool_index.learn_alias(tool_data.get("category", ""), matched_key)
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
            reused["category"] = matched_tool_info.get("category") or matched_key
            reused["tool_name"] = reused.get("tool_name") or matched
            tool_workflow.append((reused, True))
        return tool_workflow
