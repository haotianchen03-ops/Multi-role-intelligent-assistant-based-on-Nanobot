"""Heartbeat service - periodic agent wake-up to check for tasks."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

# Default interval: 20 minutes
DEFAULT_HEARTBEAT_INTERVAL_S = 20 * 60

# The prompt sent to agent during heartbeat
HEARTBEAT_PROMPT = """Read HEARTBEAT.md in your workspace (if it exists).
Follow any instructions or tasks listed there.
If nothing needs attention, reply with just: HEARTBEAT_OK"""

# Token that indicates "nothing to do"
HEARTBEAT_OK_TOKEN = "HEARTBEAT_OK"


def _is_heartbeat_empty(content: str | None) -> bool:
    """Check if HEARTBEAT.md has no actionable content."""
    if not content:
        return True
    
    # Lines to skip: empty, headers, HTML comments, empty checkboxes
    skip_patterns = {"- [ ]", "* [ ]", "- [x]", "* [x]"}
    
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("<!--") or line in skip_patterns:
            continue
        return False  # Found actionable content
    
    return True


class HeartbeatState:
    """Heartbeat service persistent state."""
    
    def __init__(
        self,
        enabled: bool = False,
        last_run_ms: int = 0,
        last_status: str = "never_run",
        last_error: str | None = None,
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
    ):
        self.enabled = enabled
        self.last_run_ms = last_run_ms
        self.last_status = last_status
        self.last_error = last_error
        self.interval_s = interval_s
    
    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "lastRunMs": self.last_run_ms,
            "lastStatus": self.last_status,
            "lastError": self.last_error,
            "intervalS": self.interval_s,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "HeartbeatState":
        return cls(
            enabled=data.get("enabled", False),
            last_run_ms=data.get("lastRunMs", 0),
            last_status=data.get("lastStatus", "never_run"),
            last_error=data.get("lastError"),
            interval_s=data.get("intervalS", DEFAULT_HEARTBEAT_INTERVAL_S),
        )


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.
    
    The agent reads HEARTBEAT.md from the workspace and executes any
    tasks listed there. If nothing needs attention, it replies HEARTBEAT_OK.
    
    State is persisted to disk and requires user confirmation to start.
    """
    
    def __init__(
        self,
        workspace: Path,
        state_path: Path | None = None,
        on_heartbeat: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        interval_s: int = DEFAULT_HEARTBEAT_INTERVAL_S,
    ):
        self.workspace = workspace
        self._state_path = state_path or (workspace.parent / "heartbeat_state.json")
        self.on_heartbeat = on_heartbeat
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None
        self._state: HeartbeatState = HeartbeatState(interval_s=interval_s)
        self._load_state()
    
    def _load_state(self) -> None:
        """Load state from disk."""
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text())
                self._state = HeartbeatState.from_dict(data)
                self.interval_s = self._state.interval_s
            except Exception as e:
                logger.warning(f"Failed to load heartbeat state: {e}")
                self._state = HeartbeatState(interval_s=self.interval_s)
    
    def _save_state(self) -> None:
        """Save state to disk."""
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(self._state.to_dict(), indent=2))
    
    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"
    
    @property
    def is_enabled(self) -> bool:
        """Check if heartbeat is enabled (requires user confirmation)."""
        return self._state.enabled
    
    @property
    def is_running(self) -> bool:
        """Check if heartbeat loop is currently running."""
        return self._running
    
    def _read_heartbeat_file(self) -> str | None:
        """Read HEARTBEAT.md content."""
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text()
            except Exception:
                return None
        return None
    
    def enable(self) -> bool:
        """
        Enable heartbeat service. Returns True if successful.
        This should be called after user confirmation.
        """
        if self._running:
            return True
        
        self._state.enabled = True
        self._state.interval_s = self.interval_s
        self._save_state()
        return True
    
    def disable(self) -> bool:
        """Disable heartbeat service."""
        self.stop()
        self._state.enabled = False
        self._save_state()
        return True
    
    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self._state.enabled:
            logger.info("Heartbeat not enabled (user confirmation required)")
            return
        
        if self._running:
            logger.info("Heartbeat already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Heartbeat started (every {self.interval_s}s)")
    
    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Heartbeat stopped")
    
    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
                self._state.last_status = "error"
                self._state.last_error = str(e)
                self._save_state()
    
    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        content = self._read_heartbeat_file()
        now_ms = int(time.time() * 1000)
        
        # Skip if HEARTBEAT.md is empty or doesn't exist
        if _is_heartbeat_empty(content):
            logger.debug("Heartbeat: no tasks (HEARTBEAT.md empty)")
            self._state.last_run_ms = now_ms
            self._state.last_status = "skipped"
            self._state.last_error = None
            self._save_state()
            return
        
        logger.info("Heartbeat: checking for tasks...")
        
        if self.on_heartbeat:
            try:
                response = await self.on_heartbeat(HEARTBEAT_PROMPT)
                self._state.last_run_ms = now_ms
                
                # Check if agent said "nothing to do"
                if HEARTBEAT_OK_TOKEN.replace("_", "") in response.upper().replace("_", ""):
                    logger.info("Heartbeat: OK (no action needed)")
                    self._state.last_status = "ok"
                else:
                    logger.info(f"Heartbeat: completed task")
                    self._state.last_status = "task_done"
                self._state.last_error = None
                    
            except Exception as e:
                logger.error(f"Heartbeat execution failed: {e}")
                self._state.last_run_ms = now_ms
                self._state.last_status = "error"
                self._state.last_error = str(e)
        
        self._save_state()
    
    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        if self.on_heartbeat:
            return await self.on_heartbeat(HEARTBEAT_PROMPT)
        return None
    
    def get_status(self) -> dict:
        """Get heartbeat status."""
        return {
            "enabled": self._state.enabled,
            "running": self._running,
            "interval_s": self.interval_s,
            "last_run_ms": self._state.last_run_ms,
            "last_status": self._state.last_status,
            "last_error": self._state.last_error,
            "heartbeat_file": str(self.heartbeat_file),
            "heartbeat_file_exists": self.heartbeat_file.exists(),
        }
