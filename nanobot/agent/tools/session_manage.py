"""Session management tool for creating and switching sessions."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool
from nanobot.session.manager import SessionManager
from nanobot.utils.helpers import truncate_string


class SessionManageTool(Tool):
    """Tool to create, switch, and list sessions for the current chat.
    
    Supports natural language requests like:
    - "创建一个叫xxx的新会话"
    - "切换到xxx会话"
    - "列出会话" / "看看有哪些会话"
    - "当前会话是什么"
    - "重置会话" / "回到默认会话"
    """

    def __init__(self, manager: SessionManager):
        self._sessions = manager
        self._channel = ""
        self._chat_id = ""
        self._last_result: str = ""  # Store last result for session history

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set current channel/chat context."""
        self._channel = channel
        self._chat_id = chat_id

    @property
    def name(self) -> str:
        return "session_manage"

    @property
    def description(self) -> str:
        return (
            "管理对话会话，支持自然语言操作。功能：\n"
            "- 创建会话：action=create, 可用session_key指定名称，title设置标题，seed用内容生成标题\n"
            "- 切换会话：action=switch, 用session_key指定目标会话\n"
            "- 列出会话：action=list, 查看所有会话列表，当前激活的会标记*\n"
            "- 查看当前：action=current, 查看当前激活的会话\n"
            "- 重置会话：action=reset, 清除激活状态，回到默认会话\n\n"
            "自然语言示例：\n"
            "- '创建一个叫python学习的新会话' → action=create, session_key=python学习\n"
            "- '切换到项目会话' → action=switch, session_key=项目\n"
            "- '有哪些会话？' → action=list\n"
            "- '现在用哪个会话？' → action=current\n"
            "- '重置会话' → action=reset"
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "switch", "list", "current", "reset"],
                    "description": "要执行的操作: create(创建), switch(切换), list(列出), current(当前), reset(重置)",
                },
                "session_key": {
                    "type": "string",
                    "description": "目标会话的标识符",
                },
                "title": {
                    "type": "string",
                    "description": "会话标题（可选）",
                },
                "seed": {
                    "type": "string",
                    "description": "用于自动生成标题的种子文本",
                },
                "activate": {
                    "type": "boolean",
                    "description": "创建后是否激活新会话",
                    "default": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "列出会话的最大数量",
                    "default": 20,
                },
                "allow_existing": {
                    "type": "boolean",
                    "description": "允许create复用已存在的会话key",
                    "default": False,
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        session_key: str | None = None,
        title: str | None = None,
        seed: str | None = None,
        activate: bool = True,
        limit: int = 20,
        allow_existing: bool = False,
        _log_to_session: bool = True,
        **kwargs: Any,
    ) -> str:
        logger.debug(f"session_manage called: action={action}, session_key={session_key}")
        
        if action == "create":
            result = self._create_session(session_key, title, seed, activate, allow_existing)
        elif action == "switch":
            result = self._switch_session(session_key)
        elif action == "list":
            result = self._list_sessions(limit)
        elif action == "current":
            result = self._current_session()
        elif action == "reset":
            result = self._reset_session()
        else:
            result = f"未知操作: {action}，支持的操作为: create, switch, list, current, reset"
        
        self._last_result = result
        return result

    @property
    def last_result(self) -> str:
        """Get the last execution result for session history."""
        return self._last_result

    def _create_session(
        self,
        session_key: str | None,
        title: str | None,
        seed: str | None,
        activate: bool,
        allow_existing: bool,
    ) -> str:
        if not self._channel or not self._chat_id:
            return "错误：缺少会话上下文（channel/chat_id）"

        key = self._resolve_key_for_create(session_key)
        if not allow_existing and self._sessions.session_exists(key):
            return f"错误：会话已存在: {key}"

        session = self._sessions.get_or_create(key)
        if title:
            session.metadata["title"] = title.strip()
        elif "title" not in session.metadata:
            session.metadata["title"] = self._generate_title(seed)

        self._sessions.save(session)

        if activate:
            self._sessions.set_active_session_key(self._channel, self._chat_id, key)
            return f"✅ 已创建并激活会话：{key}\n标题：{session.metadata.get('title', '')}"
        return f"✅ 已创建会话：{key}\n标题：{session.metadata.get('title', '')}"

    def _switch_session(self, session_key: str | None) -> str:
        if not self._channel or not self._chat_id:
            return "错误：缺少会话上下文（channel/chat_id）"
        if not session_key:
            return "错误：switch 操作需要指定 session_key"

        target_key = self._resolve_key_for_switch(session_key)
        if not target_key:
            return f"错误：找不到会话: {session_key}\n可用 /会话列表 查看所有会话"

        self._sessions.set_active_session_key(self._channel, self._chat_id, target_key)
        title = self._sessions.get_session_title(target_key) or ""
        title_part = f"\n标题：{title}" if title else ""
        return f"✅ 已切换到会话：{target_key}{title_part}"

    def _list_sessions(self, limit: int) -> str:
        sessions = self._sessions.list_sessions()
        if not sessions:
            return "📭 暂无会话记录"

        active = None
        if self._channel and self._chat_id:
            active = self._sessions.get_active_session_key(self._channel, self._chat_id)

        lines = ["📋 会话列表："]
        for idx, info in enumerate(sessions[: max(limit, 1)], start=1):
            key = info.get("key", "")
            title = info.get("title", "")
            updated = info.get("updated_at", "")
            if updated:
                try:
                    dt = datetime.fromisoformat(updated)
                    updated = dt.strftime("%m-%d %H:%M")
                except Exception:
                    pass
            mark = "⭐" if active and key == active else "  "
            label = f"{mark} {idx}. {key}"
            if title:
                label += f" | {title}"
            if updated:
                label += f" | {updated}"
            lines.append(label)

        return "\n".join(lines)

    def _current_session(self) -> str:
        if not self._channel or not self._chat_id:
            return "错误：缺少会话上下文（channel/chat_id）"
        active = self._sessions.get_active_session_key(self._channel, self._chat_id)
        if not active:
            return "📍 当前使用默认会话（channel:chat_id）"
        title = self._sessions.get_session_title(active) or ""
        title_part = f"\n标题：{title}" if title else ""
        return f"📍 当前会话：{active}{title_part}"

    def _reset_session(self) -> str:
        if not self._channel or not self._chat_id:
            return "错误：缺少会话上下文（channel/chat_id）"
        self._sessions.clear_active_session_key(self._channel, self._chat_id)
        return "✅ 已重置，当前使用默认会话（channel:chat_id）"

    def _resolve_key_for_create(self, session_key: str | None) -> str:
        base = f"{self._channel}:{self._chat_id}"
        if session_key:
            if ":" in session_key:
                return session_key
            return f"{base}:{self._slugify(session_key)}"
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        return f"{base}:{stamp}"

    def _resolve_key_for_switch(self, session_key: str) -> str | None:
        if self._sessions.session_exists(session_key):
            return session_key
        if ":" not in session_key and self._channel and self._chat_id:
            candidate = f"{self._channel}:{self._chat_id}:{self._slugify(session_key)}"
            if self._sessions.session_exists(candidate):
                return candidate
        return None

    def _generate_title(self, seed: str | None) -> str:
        if seed:
            clean = seed.strip().splitlines()[0].strip()
            if clean:
                return truncate_string(clean, max_len=60)
        stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
        return f"Session {stamp}"

    def _slugify(self, text: str) -> str:
        text = text.strip().lower()
        text = re.sub(r"[^a-z0-9\- ]", "", text)
        text = re.sub(r"\s+", "-", text)
        text = re.sub(r"-+", "-", text)
        return text.strip("-") or "session"
