"""Subagent manager for background task execution."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import AppendFileTool, EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.notion import NotionTool
from nanobot.agent.tools.image_generate import ImageGenerateTool
from nanobot.agent.tools.message import MessageTool


@dataclass
class TaskStatus:
    """Status information for a subagent task."""
    task_id: str
    label: str
    task: str
    status: str = "running"  # running, completed, failed
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    completed_at_ms: int | None = None
    result: str | None = None
    error: str | None = None
    usage: dict[str, int] | None = None
    
    @property
    def duration_ms(self) -> int | None:
        if self.completed_at_ms:
            return self.completed_at_ms - self.started_at_ms
        return None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "label": self.label,
            "task": self.task,
            "status": self.status,
            "started_at_ms": self.started_at_ms,
            "completed_at_ms": self.completed_at_ms,
            "duration_ms": self.duration_ms,
            "result": self.result[:200] + "..." if self.result and len(self.result) > 200 else self.result,
            "error": self.error,
            "usage": self.usage,
        }


class SubagentManager:
    """
    Manages background subagent execution.
    
    Subagents are lightweight agent instances that run in the background
    to handle specific tasks. They share the same LLM provider but have
    isolated context and a focused system prompt.
    """
    
    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        bus: MessageBus,
        model: str | None = None,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
        web_search_config: "WebSearchConfig | None" = None,
        exec_config: "ExecToolConfig | None" = None,
        mineru_config: "MineruConfig | None" = None,
        notion_config: "NotionToolConfig | None" = None,
        image_gen_config: "ImageGenConfig | None" = None,
        feishu_config: "FeishuConfig | None" = None,
        restrict_to_workspace: bool = False,
    ):
        from nanobot.config.schema import ExecToolConfig
        from nanobot.config.schema import MineruConfig
        from nanobot.config.schema import NotionToolConfig
        from nanobot.config.schema import WebSearchConfig
        from nanobot.config.schema import ImageGenConfig
        from nanobot.config.schema import FeishuConfig
        self.provider = provider
        self.workspace = workspace
        self.bus = bus
        self.model = model or provider.get_default_model()
        self.max_tokens = max(1, int(max_tokens))
        self.reasoning_effort = reasoning_effort
        self.web_search_config = web_search_config or WebSearchConfig()
        self.exec_config = exec_config or ExecToolConfig()
        self.mineru_config = mineru_config or MineruConfig()
        self.notion_config = notion_config or NotionToolConfig()
        self.image_gen_config = image_gen_config or ImageGenConfig()
        self.feishu_config = feishu_config or FeishuConfig()
        self.restrict_to_workspace = restrict_to_workspace
        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._tasks: dict[str, TaskStatus] = {}  # Track task details for status queries

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            if value is None:
                return 0
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _accumulate_usage(cls, target: dict[str, int], usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        target["prompt_tokens"] += cls._safe_int(usage.get("prompt_tokens"))
        target["completion_tokens"] += cls._safe_int(usage.get("completion_tokens"))
        target["total_tokens"] += cls._safe_int(usage.get("total_tokens"))
        target["cache_tokens"] += cls._safe_int(usage.get("cache_tokens"))

    def _build_token_monitor(self, usage: dict[str, int]) -> dict[str, Any]:
        """Build token monitor metadata for subagent direct message sends."""
        prompt_tokens = self._safe_int(usage.get("prompt_tokens"))
        output_tokens = self._safe_int(usage.get("completion_tokens"))
        cache_tokens = self._safe_int(usage.get("cache_tokens"))
        total_tokens = self._safe_int(usage.get("total_tokens"))

        derived_input_tokens = max(0, total_tokens - output_tokens)
        input_tokens = max(prompt_tokens, derived_input_tokens)
        cache_tokens = min(cache_tokens, input_tokens)
        input_uncached_tokens = max(0, input_tokens - cache_tokens)
        normalized_total_tokens = max(total_tokens, input_tokens + output_tokens)

        output_budget = max(1, self._safe_int(self.max_tokens))
        output_used = output_tokens
        output_raw_residue = output_budget - output_used
        output_residue = max(0, output_raw_residue)
        output_ratio = min(1.0, output_used / output_budget)

        return {
            "input_tokens": input_tokens,
            "prompt_tokens_raw": prompt_tokens,
            "input_tokens_derived_from_total": derived_input_tokens,
            "input_uncached_tokens": input_uncached_tokens,
            "output_tokens": output_tokens,
            "cache_tokens": cache_tokens,
            "task_total_tokens": normalized_total_tokens,
            "output_budget_total_tokens": output_budget,
            "output_budget_used_tokens": output_used,
            "output_budget_residue_tokens": output_residue,
            "output_budget_usage_ratio": output_ratio,
            "output_budget_usage_percent": round(output_ratio * 100, 2),
            "output_budget_exceeded": output_raw_residue < 0,
            "selected_budget_mode": "output",
            "selected_budget_total_tokens": output_budget,
            "selected_budget_used_tokens": output_used,
            "selected_budget_residue_tokens": output_residue,
            "selected_budget_usage_ratio": output_ratio,
            "selected_budget_usage_percent": round(output_ratio * 100, 2),
            "chart": {
                "type": "bar",
                "direction": "horizontal",
                "title": {"text": "token用量占比图"},
                "data": {
                    "values": [
                        {
                            "category": "token用量",
                            "item": "input",
                            "value": input_tokens,
                        },
                        {
                            "category": "token用量",
                            "item": "output",
                            "value": output_tokens,
                        },
                    ]
                },
                "xField": "value",
                "yField": "category",
                "seriesField": "item",
                "stack": True,
                "legends": {"visible": True, "orient": "bottom"},
                "label": {"visible": True, "formatter": "value"},
            },
        }
    
    async def spawn(
        self,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
    ) -> str:
        """
        Spawn a subagent to execute a task in the background.
        
        Args:
            task: The task description for the subagent.
            label: Optional human-readable label for the task.
            origin_channel: The channel to announce results to.
            origin_chat_id: The chat ID to announce results to.
        
        Returns:
            Status message indicating the subagent was started.
        """
        task_id = str(uuid.uuid4())[:8]
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")
        
        origin = {
            "channel": origin_channel,
            "chat_id": origin_chat_id,
        }
        
        # Create background task
        bg_task = asyncio.create_task(
            self._run_subagent(task_id, task, display_label, origin)
        )
        self._running_tasks[task_id] = bg_task
        
        # Track task status
        self._tasks[task_id] = TaskStatus(
            task_id=task_id,
            label=display_label,
            task=task,
            status="running",
        )
        
        # Cleanup when done
        bg_task.add_done_callback(lambda _: self._running_tasks.pop(task_id, None))
        
        # Sync to global state service
        try:
            from nanobot.subagent_state import SubagentStateService
            state = SubagentStateService.get_instance()
            state.on_spawn(task_id, display_label, task)
        except Exception:
            pass  # Non-critical if state service unavailable
        
        logger.info(f"Spawned subagent [{task_id}]: {display_label}")
        return f"Subagent [{display_label}] started (id: {task_id}). I'll notify you when it completes."
    
    async def _run_subagent(
        self,
        task_id: str,
        task: str,
        label: str,
        origin: dict[str, str],
    ) -> None:
        """Execute the subagent task and announce the result."""
        logger.info(f"Subagent [{task_id}] starting task: {label}")
        
        try:
            # Build subagent tools (no spawn tool)
            tools = ToolRegistry()
            allowed_dir = self.workspace if self.restrict_to_workspace else None
            tools.register(ReadFileTool(allowed_dir=allowed_dir))
            tools.register(WriteFileTool(allowed_dir=allowed_dir))
            tools.register(AppendFileTool(allowed_dir=allowed_dir))
            tools.register(EditFileTool(allowed_dir=allowed_dir))
            tools.register(ListDirTool(allowed_dir=allowed_dir))
            tools.register(ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
            ))
            tools.register(WebSearchTool(
                api_key=self.web_search_config.api_key or None,
                max_results=self.web_search_config.max_results,
                endpoint=self.web_search_config.endpoint,
                country=self.web_search_config.country,
                language=self.web_search_config.language,
                tbs=self.web_search_config.tbs,
                page=self.web_search_config.page,
                autocorrect=self.web_search_config.autocorrect,
                search_type=self.web_search_config.search_type,
            ))
            tools.register(WebFetchTool())

            tools.register(NotionTool(
                config=self.notion_config,
                allowed_dir=allowed_dir,
            ))

            if self.mineru_config and self.mineru_config.enabled:
                from nanobot.agent.tools.pdf_mineru import MineruPdfParseTool
                tools.register(MineruPdfParseTool(
                    config=self.mineru_config,
                    allowed_dir=allowed_dir,
                ))

            # Image generation tool
            tools.register(ImageGenerateTool(
                config=self.image_gen_config,
                feishu_config=self.feishu_config,
                workspace=self.workspace,
                allowed_dir=allowed_dir,
            ))

            # Direct message send tool (supports Feishu card template and token monitor metadata)
            message_tool = MessageTool(send_callback=self.bus.publish_outbound)
            message_tool.set_context(origin["channel"], origin["chat_id"])
            tools.register(message_tool)
            
            # Build messages with subagent-specific prompt
            system_prompt = self._build_subagent_prompt(task)
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]
            
            # Run agent loop (limited iterations)
            max_iterations = 100
            iteration = 0
            final_result: str | None = None
            task_usage = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cache_tokens": 0,
            }
            message_tool.set_token_monitor_factory(lambda: self._build_token_monitor(task_usage))
            
            while iteration < max_iterations:
                iteration += 1
                
                response = await self.provider.chat(
                    messages=messages,
                    tools=tools.get_definitions(),
                    model=self.model,
                    max_tokens=self.max_tokens,
                    reasoning_effort=self.reasoning_effort,
                )
                self._accumulate_usage(task_usage, response.usage)
                
                if response.has_tool_calls:
                    # Add assistant message with tool calls
                    tool_call_dicts = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append({
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": tool_call_dicts,
                    })
                    
                    # Execute tools
                    for tool_call in response.tool_calls:
                        args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                        logger.debug(f"Subagent [{task_id}] executing: {tool_call.name} with arguments: {args_str}")
                        result = await tools.execute(tool_call.name, tool_call.arguments)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        })
                else:
                    final_result = response.content
                    break
            
            if final_result is None:
                final_result = "Task completed but no final response was generated."
            
            logger.info(f"Subagent [{task_id}] completed successfully")
            await self._announce_result(task_id, label, task, final_result, origin, "ok", task_usage)
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            logger.error(f"Subagent [{task_id}] failed: {e}")
            await self._announce_result(
                task_id,
                label,
                task,
                error_msg,
                origin,
                "error",
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cache_tokens": 0,
                },
            )
    
    async def _announce_result(
        self,
        task_id: str,
        label: str,
        task: str,
        result: str,
        origin: dict[str, str],
        status: str,
        usage: dict[str, int],
    ) -> None:
        """Announce the subagent result to the main agent via the message bus."""
        # Update task status
        if task_id in self._tasks:
            self._tasks[task_id].status = "completed" if status == "ok" else "failed"
            self._tasks[task_id].completed_at_ms = int(time.time() * 1000)
            self._tasks[task_id].result = result
            self._tasks[task_id].usage = usage
        
        status_text = "completed successfully" if status == "ok" else "failed"
        
        # Sync to global state service
        try:
            from nanobot.subagent_state import SubagentStateService
            state = SubagentStateService.get_instance()
            state.on_complete(
                task_id=task_id,
                status=status,
                result=result,
                error=None if status == "ok" else status_text,
                usage=usage,
            )
        except Exception:
            pass  # Non-critical if state service unavailable
        
        announce_content = f"""[Subagent '{label}' {status_text}]

Task: {task}

Result:
{result}

Summarize this naturally for the user. Keep it brief (1-2 sentences). Do not mention technical details like "subagent" or task IDs."""
        
        # Inject as system message to trigger main agent
        msg = InboundMessage(
            channel="system",
            sender_id="subagent",
            chat_id=f"{origin['channel']}:{origin['chat_id']}",
            content=announce_content,
            metadata={"subagent_usage": usage},
        )
        
        await self.bus.publish_inbound(msg)
        logger.debug(f"Subagent [{task_id}] announced result to {origin['channel']}:{origin['chat_id']}")
    
    def _build_subagent_prompt(self, task: str) -> str:
        """Build a focused system prompt for the subagent."""
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        return f"""# Subagent

You are a subagent spawned by the main agent to complete a specific task.

## Current Time
{now}

## Your Task
{task}

## Rules
1. Stay focused - complete only the assigned task, nothing else
2. Your final response will be reported back to the main agent
3. Do not initiate conversations or take on side tasks
4. Be concise but informative in your findings

## What You Can Do
- Read and write files in the workspace
- Execute shell commands
- Search the web and fetch web pages
- Complete the task thoroughly

## What You Cannot Do
- Spawn other subagents
- Access the main agent's conversation history

## Workspace
Your workspace is at: {self.workspace}

When you have completed the task, provide a clear summary of your findings or actions."""
    
    def get_running_count(self) -> int:
        """Return the number of currently running subagents."""
        return len(self._running_tasks)
    
    def get_task_status(self, task_id: str) -> dict[str, Any] | None:
        """Get status of a specific task by ID."""
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None
    
    def list_tasks(self, include_completed: bool = True, limit: int = 20) -> list[dict[str, Any]]:
        """List all tasks, optionally filtered by status.
        
        Args:
            include_completed: If False, only return running tasks.
            limit: Maximum number of tasks to return (most recent first).
        
        Returns:
            List of task status dictionaries.
        """
        tasks = list(self._tasks.values())
        
        # Sort by started_at_ms descending (most recent first)
        tasks.sort(key=lambda t: t.started_at_ms, reverse=True)
        
        # Filter if needed
        if not include_completed:
            tasks = [t for t in tasks if t.status == "running"]
        
        # Apply limit
        tasks = tasks[:limit]
        
        return [t.to_dict() for t in tasks]
    
    def clear_completed_tasks(self, older_than_ms: int | None = None) -> int:
        """Clear completed/failed tasks from history.
        
        Args:
            older_than_ms: Only clear tasks older than this many milliseconds.
                          If None, clear all completed tasks.
        
        Returns:
            Number of tasks cleared.
        """
        now_ms = int(time.time() * 1000)
        keys_to_remove = []
        
        for task_id, task in self._tasks.items():
            if task.status == "running":
                continue
            if older_than_ms is not None:
                if task.completed_at_ms and (now_ms - task.completed_at_ms) <= older_than_ms:
                    continue
            keys_to_remove.append(task_id)
        
        for key in keys_to_remove:
            del self._tasks[key]
        
        return len(keys_to_remove)
