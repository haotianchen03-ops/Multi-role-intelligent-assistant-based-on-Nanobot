"""PostgreSQL Knowledge Base Service.

Stores FAQ, tickets, and product documentation in PostgreSQL.

Uses psycopg3 for better compatibility with Windows Chinese environment.
psycopg3 (psycopg) is a complete rewrite that doesn't have encoding issues.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel, Field


# Use psycopg3 (psycopg) instead of psycopg2
# psycopg3 is a complete rewrite with better encoding support
import psycopg
from psycopg import sql

from nanobot.utils.helpers import ensure_dir


class KBCategory(str, Enum):
    """Knowledge base categories."""
    FAQ = "faq"
    TICKET = "ticket"
    PRODUCT = "product"
    TROUBLESHOOT = "troubleshoot"


class KBPriority(int, Enum):
    """Priority levels for KB entries."""
    P1_CRITICAL = 1
    P2_HIGH = 2
    P3_MEDIUM = 3
    P4_LOW = 4


class KBEntry(BaseModel):
    """Knowledge base entry model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: KBCategory
    title: str
    question: Optional[str] = None
    answer: str
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    priority: KBPriority = KBPriority.P3_MEDIUM
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    source_file: Optional[str] = None
    view_count: int = 0
    helpful_count: int = 0


class PostgresKBService:
    """PostgreSQL Knowledge Base Service.
    
    Usage:
        kb = PostgresKBService()
        kb.init_db()  # First time setup
        
        # Add entry
        kb.add_entry(KBEntry(
            category=KBCategory.FAQ,
            title="如何注册？",
            question="注册账户",
            answer="访问官网点击注册..."
        ))
        
        # Search
        results = kb.search("注册", category=KBCategory.FAQ, limit=5)
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "nanobot_kb",
        user: str = "postgres",
        password: str = "postgres",
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self._conn: Optional[psycopg.Connection] = None

    def _get_connection(self) -> psycopg.Connection:
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.user,
                password=self.password,
                connect_timeout=5,
                # psycopg3 handles encoding correctly, no workaround needed
            )
        return self._conn

    def init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            # Enable UUID extension
            cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            
            # Create main KB table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kb_entries (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    category VARCHAR(50) NOT NULL,
                    title VARCHAR(500) NOT NULL,
                    question TEXT,
                    answer TEXT NOT NULL,
                    keywords TEXT[] DEFAULT '{}',
                    tags TEXT[] DEFAULT '{}',
                    priority INTEGER DEFAULT 3,
                    metadata JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    source_file VARCHAR(500),
                    view_count INTEGER DEFAULT 0,
                    helpful_count INTEGER DEFAULT 0
                )
            """)
            
            # Create indexes for search
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kb_category ON kb_entries(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kb_priority ON kb_entries(priority)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_kb_created ON kb_entries(created_at DESC)")
            
            # Create Chinese text search configuration if not exists
            try:
                cur.execute("""
                    SELECT 1 FROM pg_ts_config WHERE cfgname = 'chinese'
                """)
                if not cur.fetchone():
                    cur.execute("""
                        CREATE TEXT SEARCH CONFIGURATION chinese (PARSER = pg_catalog.default);
                        ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR asciiword WITH english_stem;
                        ALTER TEXT SEARCH CONFIGURATION chinese ADD MAPPING FOR word WITH simple;
                    """)
                    logger.info("Created Chinese text search configuration")
            except Exception as e:
                logger.warning(f"Could not create Chinese FTS config: {e}")
            
            # Create full-text search index (if not exists)
            try:
                cur.execute("""
                    ALTER TABLE kb_entries ADD COLUMN IF NOT EXISTS 
                    fts_vector TSVECTOR GENERATED ALWAYS AS (
                        to_tsvector('chinese'::regconfig, coalesce(title, '') || ' ' || coalesce(question, '') || ' ' || coalesce(answer, ''))
                    ) STORED
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_kb_fts ON kb_entries USING GIN(fts_vector)")
                logger.info("Created full-text search index")
            except Exception as e:
                logger.warning(f"FTS index may already exist: {e}")
        
        conn.commit()
        logger.info(f"Database '{self.database}' initialized successfully")

    def add_entry(self, entry: KBEntry) -> str:
        """Add a new knowledge base entry."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kb_entries 
                (category, title, question, answer, keywords, tags, priority, metadata, source_file)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    entry.category.value,
                    entry.title,
                    entry.question,
                    entry.answer,
                    entry.keywords,
                    entry.tags,
                    entry.priority.value,
                    json.dumps(entry.metadata),
                    entry.source_file,
                ),
            )
            entry_id = cur.fetchone()[0]
        
        conn.commit()
        logger.info(f"Added KB entry: {entry_id} - {entry.title}")
        return str(entry_id)

    def add_entries_batch(self, entries: list[KBEntry]) -> list[str]:
        """Add multiple entries in batch."""
        if not entries:
            return []
        
        conn = self._get_connection()
        entry_ids = []
        
        # psycopg3: Use executemany or individual inserts
        # executemany is available but less efficient than psycopg2's execute_values
        # For best performance, we use a single INSERT with multiple VALUES
        if entries:
            values_placeholders = ", ".join(
                ["(%s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(entries)
            )
            values = []
            for e in entries:
                values.extend([
                    e.category.value,
                    e.title,
                    e.question,
                    e.answer,
                    e.keywords,
                    e.tags,
                    e.priority.value,
                    json.dumps(e.metadata),
                    e.source_file,
                ])
            
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO kb_entries 
                    (category, title, question, answer, keywords, tags, priority, metadata, source_file)
                    VALUES {values_placeholders}
                    RETURNING id
                    """,
                    values,
                )
                entry_ids = [str(row[0]) for row in cur.fetchall()]
        
        conn.commit()
        logger.info(f"Batch inserted {len(entry_ids)} KB entries")
        return entry_ids

    def search(
        self,
        query: str,
        category: Optional[KBCategory] = None,
        limit: int = 5,
        min_priority: Optional[KBPriority] = None,
    ) -> list[KBEntry]:
        """Search knowledge base using full-text search with Chinese ILIKE fallback.
        
        Tries FTS first, falls back to ILIKE if results are too few.
        This handles cases where Chinese tokenizers (like pg_jieba) are not installed.
        """
        conn = self._get_connection()
        
        # Build query with Chinese language support
        sql_query = """
            SELECT id, category, title, question, answer, keywords, tags, 
                   priority, metadata, created_at, updated_at, source_file,
                   view_count, helpful_count,
                   ts_rank(fts_vector, plainto_tsquery('chinese', %s)) as rank
            FROM kb_entries
            WHERE fts_vector @@ plainto_tsquery('chinese', %s)
        """
        params: list[Any] = [query, query]
        
        if category:
            sql_query += " AND category = %s"
            params.append(category.value)
        
        if min_priority:
            sql_query += " AND priority <= %s"
            params.append(min_priority.value)
        
        sql_query += " ORDER BY rank DESC, priority ASC, helpful_count DESC LIMIT %s"
        params.append(limit)
        
        with conn.cursor() as cur:
            cur.execute(sql_query, params)
            rows = cur.fetchall()
        
        # Fallback: if FTS returns too few results, try ILIKE search
        if len(rows) < 2:
            logger.debug(f"FTS returned {len(rows)} results for '{query}', trying ILIKE fallback")
            
            ilike_query = """
                SELECT id, category, title, question, answer, keywords, tags, 
                       priority, metadata, created_at, updated_at, source_file,
                       view_count, helpful_count,
                       0.0 as rank
                FROM kb_entries
                WHERE (title ILIKE %s OR question ILIKE %s OR answer ILIKE %s)
            """
            ilike_pattern = f"%{query}%"
            ilike_params: list[Any] = [ilike_pattern, ilike_pattern, ilike_pattern]
            
            if category:
                ilike_query += " AND category = %s"
                ilike_params.append(category.value)
            
            if min_priority:
                ilike_query += " AND priority <= %s"
                ilike_params.append(min_priority.value)
            
            ilike_query += " ORDER BY priority ASC, helpful_count DESC LIMIT %s"
            ilike_params.append(limit)
            
            with conn.cursor() as cur:
                cur.execute(ilike_query, ilike_params)
                rows = cur.fetchall()
            
            logger.info(f"ILIKE fallback found {len(rows)} results for '{query}'")
        
        # Increment view counts
        if rows:
            ids = [str(row[0]) for row in rows]
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE kb_entries SET view_count = view_count + 1 WHERE id = ANY(%s)",
                    (ids,)
                )
            conn.commit()
        
        return [
            KBEntry(
                id=str(row[0]),
                category=KBCategory(row[1]),
                title=row[2],
                question=row[3],
                answer=row[4],
                keywords=row[5] or [],
                tags=row[6] or [],
                priority=KBPriority(row[7]),
                metadata=row[8] or {},
                created_at=row[9],
                updated_at=row[10],
                source_file=row[11],
                view_count=row[12] or 0,
                helpful_count=row[13] or 0,
            )
            for row in rows
        ]

    def get_by_id(self, entry_id: str) -> Optional[KBEntry]:
        """Get entry by ID."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM kb_entries WHERE id = %s", (entry_id,))
            row = cur.fetchone()
        
        if not row:
            return None
        
        return KBEntry(
            id=str(row[0]),
            category=KBCategory(row[1]),
            title=row[2],
            question=row[3],
            answer=row[4],
            keywords=row[5] or [],
            tags=row[6] or [],
            priority=KBPriority(row[7]),
            metadata=row[8] or {},
            created_at=row[9],
            updated_at=row[10],
            source_file=row[11],
            view_count=row[12] or 0,
            helpful_count=row[13] or 0,
        )

    def get_all(self, category: Optional[KBCategory] = None) -> list[KBEntry]:
        """Get all entries, optionally filtered by category."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            if category:
                cur.execute(
                    "SELECT * FROM kb_entries WHERE category = %s ORDER BY priority, created_at DESC",
                    (category.value,)
                )
            else:
                cur.execute("SELECT * FROM kb_entries ORDER BY priority, created_at DESC")
            
            rows = cur.fetchall()
        
        return [
            KBEntry(
                id=str(row[0]),
                category=KBCategory(row[1]),
                title=row[2],
                question=row[3],
                answer=row[4],
                keywords=row[5] or [],
                tags=row[6] or [],
                priority=KBPriority(row[7]),
                metadata=row[8] or {},
                created_at=row[9],
                updated_at=row[10],
                source_file=row[11],
                view_count=row[12] or 0,
                helpful_count=row[13] or 0,
            )
            for row in rows
        ]

    def mark_helpful(self, entry_id: str) -> None:
        """Mark an entry as helpful."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE kb_entries SET helpful_count = helpful_count + 1 WHERE id = %s",
                (entry_id,)
            )
        
        conn.commit()

    def delete(self, entry_id: str) -> bool:
        """Delete an entry."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kb_entries WHERE id = %s RETURNING id", (entry_id,))
            deleted = cur.fetchone() is not None
        
        conn.commit()
        return deleted

    def count(self, category: Optional[KBCategory] = None) -> int:
        """Count entries."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            if category:
                cur.execute(
                    "SELECT COUNT(*) FROM kb_entries WHERE category = %s",
                    (category.value,)
                )
            else:
                cur.execute("SELECT COUNT(*) FROM kb_entries")
            
            count = cur.fetchone()[0]
        
        return count

    def close(self) -> None:
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None
