"""Semantic search tool for session history."""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.session.manager import SessionManager


class HistorySearchTool(Tool):
    """Tool to search session history by semantic similarity.
    
    Uses sentence-transformers embeddings to find relevant past messages
    even when exact keywords don't match.
    """

    def __init__(self, manager: SessionManager):
        self._sessions = manager

    @property
    def name(self) -> str:
        return "history_search"

    @property
    def description(self) -> str:
        return (
            "语义搜索会话历史。使用向量嵌入在历史记录中查找相关内容，"
            "即使不记得确切关键词也能找到。\n"
            "- query: 搜索查询（自然语言）\n"
            "- top_k: 返回结果数量，默认5\n"
            "- session_key: 可选，限定搜索特定会话"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询（自然语言）",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果数量",
                    "default": 5,
                },
                "session_key": {
                    "type": "string",
                    "description": "可选，限定搜索特定会话",
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        top_k: int = 5,
        session_key: str | None = None,
        **kwargs: Any,
    ) -> str:
        logger.debug(f"history_search called: query={query}, top_k={top_k}")

        results = self._sessions.semantic_search(query, top_k=top_k, session_key=session_key)

        if not results:
            return "没有找到相关的历史记录。"

        lines = [f"找到 {len(results)} 条相关记录："]
        for i, r in enumerate(results, 1):
            role_emoji = "👤" if r["role"] == "user" else "🤖"
            score = r.get("relevance_score", 0)
            content = r["content"]
            # Truncate long content
            if len(content) > 200:
                content = content[:200] + "..."
            session_part = f"[{r['session_key']}] " if session_key is None else ""
            lines.append(f"{i}. {session_part}{role_emoji} {content}")
            lines.append(f"   相关度: {score:.2f}")

        return "\n".join(lines)