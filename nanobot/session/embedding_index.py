"""Semantic embedding index for session history."""

from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

from nanobot.utils.helpers import ensure_dir, get_sessions_path


# Lazy import to avoid blocking if sentence-transformers unavailable
_sentence_transformer_model: Any = None
_model_name = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")


def _get_model():
    """Lazy-load embedding model."""
    global _sentence_transformer_model
    if _sentence_transformer_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"Loading embedding model: {_model_name}")
            _sentence_transformer_model = SentenceTransformer(_model_name)
        except ImportError:
            logger.warning("sentence-transformers not installed, semantic search disabled")
            return None
    return _sentence_transformer_model


@dataclass
class IndexedEntry:
    """A single indexed entry from session history."""
    session_key: str
    message_index: int  # Position in session messages
    role: str
    content: str
    timestamp: str
    embedding: list[float] | None = None


class EmbeddingIndex:
    """
    Semantic index for session history entries.
    
    Maintains a JSONL file index for fast lookup.
    Model embeddings are computed on-demand and cached.
    """

    def __init__(self, workspace: Path | None = None, max_entries: int = 5000):
        self.workspace = workspace or Path.cwd()
        self.index_dir = self.workspace / "data" / "embeddings"
        self.index_file = self.index_dir / "history_index.jsonl"
        self._entries: list[dict[str, Any]] = []
        self._vector_cache: dict[str, list[float]] = {}  # entry_id -> embedding
        self._model = None
        self.max_entries = max_entries
        self._load_index()

    def _load_index(self) -> None:
        """Load index from disk."""
        if not self.index_file.exists():
            return
        try:
            with open(self.index_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    self._entries.append(entry)
            logger.info(f"Loaded {len(self._entries)} indexed entries")
        except Exception as e:
            logger.warning(f"Failed to load embedding index: {e}")

    def _save_index(self) -> None:
        """Save index to disk."""
        ensure_dir(self.index_dir)
        with open(self.index_file, "w", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _get_entry_id(self, entry: dict[str, Any]) -> str:
        return f"{entry['session_key']}_{entry['message_index']}"

    def _init_model(self) -> bool:
        """Initialize embedding model."""
        if self._model is None:
            self._model = _get_model()
        return self._model is not None

    def index_session(self, session_key: str, messages: list[dict[str, Any]]) -> None:
        """
        Index messages from a session.
        
        Args:
            session_key: Unique session identifier
            messages: List of message dicts from session
        """
        if not self._init_model():
            logger.warning("Embedding model not available, skipping indexing")
            return

        new_entries = []
        existing_ids = {self._get_entry_id(e) for e in self._entries}

        for idx, msg in enumerate(messages):
            entry_id = f"{session_key}_{idx}"
            if entry_id in existing_ids:
                continue

            content = msg.get("content") or ""
            if not isinstance(content, str) or len(content.strip()) < 5:
                continue

            role = msg.get("role", "unknown")
            timestamp = msg.get("timestamp", datetime.now().isoformat())

            entry = {
                "session_key": session_key,
                "message_index": idx,
                "role": role,
                "content": content.strip(),
                "timestamp": timestamp,
                "entry_id": entry_id,
            }
            new_entries.append(entry)

        if not new_entries:
            return

        # Batch encode all new entries
        texts = [e["content"] for e in new_entries]
        embeddings = self._model.encode(texts, show_progress_bar=False).tolist()

        for entry, embedding in zip(new_entries, embeddings):
            entry["embedding"] = embedding
            self._entries.append(entry)
            self._vector_cache[entry["entry_id"]] = embedding

        # Trim if over max
        if len(self._entries) > self.max_entries:
            self._entries = self._entries[-self.max_entries:]

        self._save_index()
        logger.info(f"Indexed {len(new_entries)} new entries for session {session_key}")

    def search(
        self,
        query: str,
        top_k: int = 5,
        session_key: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic search over indexed entries.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            session_key: Optional filter by session
        
        Returns:
            List of matching entries with relevance scores
        """
        if not self._init_model():
            return []
        if not self._entries:
            return []

        # Filter entries
        candidates = self._entries
        if session_key:
            candidates = [e for e in candidates if e.get("session_key") == session_key]

        if not candidates:
            return []

        # Encode query
        query_embedding = self._model.encode(query).tolist()

        # Compute cosine similarity
        scored = []
        for entry in candidates:
            emb = entry.get("embedding")
            if not emb:
                continue
            score = self._cosine_sim(query_embedding, emb)
            scored.append((score, entry))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, entry in scored[:top_k]:
            result = {
                "session_key": entry["session_key"],
                "message_index": entry["message_index"],
                "role": entry["role"],
                "content": entry["content"],
                "timestamp": entry["timestamp"],
                "relevance_score": round(score, 4),
            }
            results.append(result)

        return results

    def _cosine_sim(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def clear(self) -> None:
        """Clear the entire index."""
        self._entries = []
        self._vector_cache = {}
        if self.index_file.exists():
            self.index_file.unlink()
        logger.info("Embedding index cleared")