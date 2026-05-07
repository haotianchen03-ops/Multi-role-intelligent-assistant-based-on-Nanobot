"""Subagent state service - shared state for subagent status across gateway API."""

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

from loguru import logger


class SubagentState:
    """Subagent state data structure."""
    
    def __init__(
        self,
        running_count: int = 0,
        total_spawned: int = 0,
        last_task_id: str | None = None,
        tasks: dict[str, dict[str, Any]] | None = None,
    ):
        self.running_count = running_count
        self.total_spawned = total_spawned
        self.last_task_id = last_task_id
        self.tasks = tasks or {}
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "runningCount": self.running_count,
            "totalSpawned": self.total_spawned,
            "lastTaskId": self.last_task_id,
            "tasks": self.tasks,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SubagentState":
        return cls(
            running_count=data.get("runningCount", 0),
            total_spawned=data.get("totalSpawned", 0),
            last_task_id=data.get("lastTaskId"),
            tasks=data.get("tasks", {}),
        )


class SubagentStateService:
    """
    Service for tracking subagent status across the gateway API.
    
    This service maintains a shared state that can be:
    1. Updated by AgentLoop when subagents spawn/complete
    2. Queried by the gateway API for status display
    
    The state is persisted to a JSON file for recovery after restarts.
    """
    
    _instance: "SubagentStateService | None" = None
    _lock = threading.Lock()
    
    def __init__(
        self,
        state_file: Path | None = None,
    ):
        self._state_file = state_file
        self._state = SubagentState()
        self._lock = threading.Lock()
        
        # Load existing state if available
        if state_file and state_file.exists():
            self._load()
    
    @classmethod
    def get_instance(cls) -> "SubagentStateService":
        """Get or create the singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    # Default state file location
                    state_file = Path.home() / ".nanobot" / "subagent_state.json"
                    cls._instance = cls(state_file=state_file)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None
    
    def _load(self) -> None:
        """Load state from file."""
        try:
            if self._state_file and self._state_file.exists():
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                self._state = SubagentState.from_dict(data)
                logger.debug(f"Loaded subagent state: {self._state.running_count} running")
        except Exception as e:
            logger.warning(f"Failed to load subagent state: {e}")
            self._state = SubagentState()
    
    def _save(self) -> None:
        """Save state to file."""
        try:
            if self._state_file:
                self._state_file.parent.mkdir(parents=True, exist_ok=True)
                self._state_file.write_text(
                    json.dumps(self._state.to_dict(), ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
        except Exception as e:
            logger.warning(f"Failed to save subagent state: {e}")
    
    def on_spawn(self, task_id: str, label: str, task: str) -> None:
        """Called when a subagent is spawned."""
        with self._lock:
            self._state.running_count += 1
            self._state.total_spawned += 1
            self._state.last_task_id = task_id
            self._state.tasks[task_id] = {
                "taskId": task_id,
                "label": label,
                "task": task,
                "status": "running",
                "spawnedAtMs": int(__import__("time").time() * 1000),
                "completedAtMs": None,
                "durationMs": None,
                "result": None,
                "error": None,
                "usage": None,
            }
            self._save()
    
    def on_complete(
        self,
        task_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
        usage: dict[str, int] | None = None,
    ) -> None:
        """Called when a subagent completes."""
        with self._lock:
            now_ms = int(__import__("time").time() * 1000)
            self._state.running_count = max(0, self._state.running_count - 1)
            
            if task_id in self._state.tasks:
                task = self._state.tasks[task_id]
                task["status"] = "completed" if status == "ok" else "failed"
                task["completedAtMs"] = now_ms
                task["durationMs"] = now_ms - task["spawnedAtMs"]
                task["result"] = result
                task["error"] = error
                task["usage"] = usage
                self._save()
    
    def get_status(self) -> dict[str, Any]:
        """Get current subagent status."""
        with self._lock:
            return self._state.to_dict()
    
    def list_tasks(
        self,
        include_completed: bool = True,
        limit: int = 20,
        running_only: bool = False,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filtering."""
        with self._lock:
            tasks = list(self._state.tasks.values())
            
            # Filter by status
            if running_only:
                tasks = [t for t in tasks if t.get("status") == "running"]
            elif not include_completed:
                tasks = [t for t in tasks if t.get("status") == "running"]
            
            # Sort by spawn time (most recent first)
            tasks.sort(key=lambda t: t.get("spawnedAtMs", 0), reverse=True)
            
            # Apply limit
            tasks = tasks[:limit]
            
            # Truncate long results
            for task in tasks:
                if task.get("result") and len(task["result"]) > 200:
                    task["result"] = task["result"][:200] + "..."
            
            return tasks
    
    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get a specific task by ID."""
        with self._lock:
            return self._state.tasks.get(task_id)
    
    def clear_completed_tasks(self, older_than_ms: int | None = None) -> int:
        """Clear completed/failed tasks from history."""
        with self._lock:
            now_ms = int(__import__("time").time() * 1000)
            keys_to_remove = []
            
            for task_id, task in self._state.tasks.items():
                if task.get("status") == "running":
                    continue
                if older_than_ms is not None:
                    completed_at = task.get("completedAtMs")
                    if completed_at and (now_ms - completed_at) <= older_than_ms:
                        continue
                keys_to_remove.append(task_id)
            
            for key in keys_to_remove:
                del self._state.tasks[key]
            
            if keys_to_remove:
                self._save()
            
            return len(keys_to_remove)


# Decorator for integration with SubagentManager
def hook_subagent_manager(manager) -> None:
    """
    Hook into a SubagentManager instance to sync state.
    
    Call this after creating a SubagentManager to enable
    state synchronization with the SubagentStateService.
    """
    state_service = SubagentStateService.get_instance()
    
    original_spawn = manager.spawn
    
    def hooked_spawn(*args, **kwargs):
        # Get task info before spawning
        task = args[0] if args else kwargs.get("task", "")
        label = kwargs.get("label") or (args[1] if len(args) > 1 else None) or task[:50]
        task_id = kwargs.get("task_id") or str(__import__("uuid").uuid4())[:8]
        
        # Call original spawn
        result = original_spawn(*args, **kwargs)
        
        # Notify state service
        state_service.on_spawn(task_id, label, task)
        
        return result
    
    manager.spawn = hooked_spawn
