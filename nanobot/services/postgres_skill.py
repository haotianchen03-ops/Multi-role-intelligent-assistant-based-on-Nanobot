"""PostgreSQL Skill Service.

Stores skills, their descriptions, and metadata in PostgreSQL.
Supports skill categorization by business type and capability domain.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel, Field


class SkillStatus(str, Enum):
    """Skill deployment status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"
    DEPRECATED = "deprecated"


class SkillCategory(str, Enum):
    """Skill categories by business domain."""
    # Enterprise business
    CUSTOMER_SERVICE = "customer_service"   # Customer support
    SALES = "sales"                           # Sales & marketing
    TECHNICAL = "technical"                   # Technical support
    BILLING = "billing"                       # Billing & finance
    HR = "hr"                                 # Human resources
    OPERATIONS = "operations"                 # Business operations
    
    # Special skills
    PRODUCT = "product"                       # Product information
    FAQ = "faq"                               # FAQ handler
    TICKET = "ticket"                         # Ticket management
    KNOWLEDGE = "knowledge"                   # Knowledge retrieval
    
    # AI/Agent skills
    SUMMARIZE = "summarize"                   # Text summarization
    TRANSLATE = "translate"                   # Translation
    INTERVIEW = "interview"                   # Interview coach
    COACH = "coach"                           # Coaching
    
    # Platform skills
    WECHAT = "wechat"                         # WeChat integration
    FEISHU = "feishu"                         # Feishu integration
    SLACK = "slack"                           # Slack integration
    
    # Utility
    OTHER = "other"


class SkillParameter(BaseModel):
    """Skill parameter definition."""
    name: str
    type: str  # string, number, boolean, array, object
    description: str
    required: bool = False
    default: Optional[Any] = None


class Skill(BaseModel):
    """Skill model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    
    # Basic info
    name: str                                    # Unique name (e.g., "hotel-booking")
    display_name: str                             # Display name (e.g., "酒店预订助手")
    description: str                             # One-line description
    
    # Classification
    category: SkillCategory = SkillCategory.OTHER
    tags: list[str] = Field(default_factory=list)
    status: SkillStatus = SkillStatus.DRAFT
    
    # Business context
    enterprise_id: Optional[str] = None         # For multi-tenant isolation
    business_type: Optional[str] = None         # e.g., "hotel", "retail", "fintech"
    
    # Capability
    triggers: list[str] = Field(default_factory=list)  # Trigger keywords
    capabilities: list[str] = Field(default_factory=list)  # What it can do
    limitations: list[str] = Field(default_factory=list)  # What it can't do
    
    # Parameters
    parameters: list[SkillParameter] = Field(default_factory=list)
    
    # Configuration
    config: dict[str, Any] = Field(default_factory=dict)
    
    # Source
    source: str = "local"                        # local, skills.sh, custom
    source_url: Optional[str] = None             # GitHub or skills.sh URL
    version: str = "1.0.0"
    
    # Usage statistics
    invocation_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    
    # Content
    skill_md: Optional[str] = None              # Full SKILL.md content
    readme: Optional[str] = None                # README content
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_used_at: Optional[datetime] = None


class SkillInvocation(BaseModel):
    """Record of skill invocation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    skill_id: str
    skill_name: str
    user_id: str
    enterprise_id: Optional[str] = None
    input_summary: str                          # Truncated input
    output_summary: Optional[str] = None       # Truncated output
    status: str = "success"                     # success, failure
    error_message: Optional[str] = None
    duration_ms: int                            # Execution time
    created_at: datetime = Field(default_factory=datetime.now)


class PostgresSkillService:
    """PostgreSQL Skill Service.
    
    Usage:
        skill_service = PostgresSkillService()
        skill_service.init_db()
        
        # Register a skill
        skill = skill_service.create(
            name="hotel-booking",
            display_name="酒店预订助手",
            description="帮助用户预订酒店房间",
            category=SkillCategory.CUSTOMER_SERVICE,
            business_type="hotel",
            triggers=["酒店", "预订", "房间"],
            capabilities=["查询房型", "预订房间", "取消预订"],
            skill_md="# Hotel Booking Skill..."
        )
        
        # Search skills
        skills = skill_service.search(
            category=SkillCategory.CUSTOMER_SERVICE,
            business_type="hotel",
            keyword="预订"
        )
        
        # Get skill by name
        skill = skill_service.get_by_name("hotel-booking", enterprise_id="ent_001")
        
        # Record invocation
        skill_service.record_invocation(
            skill_id=skill.id,
            skill_name=skill.name,
            user_id="user_001",
            input_summary="查询酒店房间",
            duration_ms=150
        )
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 5432,
        database: str = "nanobot_db",
        user: str = "postgres",
        password: str = "postgres",
    ):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self._conn: Optional[Any] = None

    def _get_connection(self) -> Any:
        """Get or create database connection."""
        import psycopg
        
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                host=self.host,
                port=self.port,
                dbname=self.database,
                user=self.user,
                password=self.password,
                connect_timeout=5,
            )
        return self._conn

    def init_db(self) -> None:
        """Initialize database schema for skills."""
        conn = self._get_connection()
        
        # Check if skills table exists
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name = 'skills'
            """)
            exists = cur.fetchone() is not None
        
        if exists:
            logger.info("Skills table already exists, skipping creation")
            return
        
        with conn.cursor() as cur:
            # Enable UUID extension
            cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            
            # Create skills table (skills is a reserved word, need quotes)
            cur.execute("""
                CREATE TABLE "skills" (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    
                    -- Basic info
                    name VARCHAR(100) NOT NULL,
                    display_name VARCHAR(200) NOT NULL,
                    description VARCHAR(500),
                    
                    -- Classification
                    category VARCHAR(50) NOT NULL DEFAULT 'other',
                    tags TEXT[] DEFAULT '{}',
                    status VARCHAR(20) NOT NULL DEFAULT 'draft',
                    
                    -- Business context
                    enterprise_id VARCHAR(100),
                    business_type VARCHAR(50),
                    
                    -- Capability
                    triggers TEXT[] DEFAULT '{}',
                    capabilities TEXT[] DEFAULT '{}',
                    limitations TEXT[] DEFAULT '{}',
                    
                    -- Configuration
                    config JSONB DEFAULT '{}',
                    
                    -- Source
                    source VARCHAR(50) DEFAULT 'local',
                    source_url VARCHAR(500),
                    version VARCHAR(20) DEFAULT '1.0.0',
                    
                    -- Usage statistics
                    invocation_count INTEGER DEFAULT 0,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    
                    -- Content
                    skill_md TEXT,
                    readme TEXT,
                    
                    -- Metadata
                    metadata JSONB DEFAULT '{}',
                    
                    -- Timestamps
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    last_used_at TIMESTAMP,
                    
                    -- Constraints
                    CONSTRAINT unique_name_enterprise UNIQUE (name, enterprise_id)
                )
            """)
            
            # Create invocation logs table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS skill_invocations (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    skill_id UUID REFERENCES skills(id) ON DELETE SET NULL,
                    skill_name VARCHAR(100),
                    user_id VARCHAR(100),
                    enterprise_id VARCHAR(100),
                    input_summary TEXT,
                    output_summary TEXT,
                    status VARCHAR(20) NOT NULL DEFAULT 'success',
                    error_message TEXT,
                    duration_ms INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Create indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_enterprise ON skills(enterprise_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_status ON skills(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_business ON skills(business_type)")
            
            cur.execute("CREATE INDEX IF NOT EXISTS idx_invocations_skill ON skill_invocations(skill_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_invocations_user ON skill_invocations(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_invocations_enterprise ON skill_invocations(enterprise_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_invocations_created ON skill_invocations(created_at DESC)")
            
            # Create update trigger
            cur.execute("""
                CREATE OR REPLACE FUNCTION update_updated_at_column()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$ language 'plpgsql'
            """)
            cur.execute("DROP TRIGGER IF EXISTS update_skills_updated_at ON skills")
            cur.execute("""
                CREATE TRIGGER update_skills_updated_at
                BEFORE UPDATE ON skills
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column()
            """)
            
            # Create full-text search (skip if column exists, sometimes this fails)
            try:
                # First check if column exists
                cur.execute("""
                    SELECT 1 FROM information_schema.columns 
                    WHERE table_name = 'skills' AND column_name = 'fts_vector'
                """)
                if not cur.fetchone():
                    cur.execute("""
                        ALTER TABLE skills ADD COLUMN 
                        fts_vector TSVECTOR GENERATED ALWAYS AS (
                            to_tsvector('chinese'::regconfig, 
                                coalesce(name, '') || ' ' || 
                                coalesce(display_name, '') || ' ' || 
                                coalesce(description, '') || ' ' ||
                                coalesce(array_to_string(tags, ' '), '') || ' ' ||
                                coalesce(array_to_string(triggers, ' '), '') || ' ' ||
                                coalesce(array_to_string(capabilities, ' '), '')
                            )
                        ) STORED
                    """)
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_fts ON skills USING GIN(fts_vector)")
            except Exception as e:
                logger.warning(f"FTS index skipped: {e}")
                # Create simple text search as fallback
                try:
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_name_search ON skills(name)")
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_skills_display ON skills(display_name)")
                except:
                    pass
        
        conn.commit()
        logger.info(f"Skills table initialized in '{self.database}'")

    def create(self, **kwargs) -> Skill:
        """Create a new skill."""
        conn = self._get_connection()
        
        fields = []
        values = []
        params = []
        
        for key, value in kwargs.items():
            if key in ["id", "created_at", "updated_at", "parameters"]:
                continue
            
            # Convert enums and special types
            if isinstance(value, Enum):
                value = value.value
            elif key == "metadata":
                value = json.dumps(value)
            elif key == "parameters" and isinstance(value, list):
                # Parameters is a list of SkillParameter objects
                value = [p.model_dump() if hasattr(p, 'model_dump') else p for p in value]
                value = json.dumps(value)
            elif isinstance(value, list):
                value = value
            
            fields.append(key)
            values.append(value)
            params.append(value)
        
        query = f"""
            INSERT INTO skills ({', '.join(fields)})
            VALUES ({', '.join(['%s'] * len(fields))})
            RETURNING *
        """
        
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        
        conn.commit()
        
        return self._row_to_skill(row)

    def get_by_id(self, skill_id: str) -> Optional[Skill]:
        """Get skill by ID."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM skills WHERE id = %s", (skill_id,))
            row = cur.fetchone()
        
        return self._row_to_skill(row) if row else None

    def get_by_name(self, name: str, enterprise_id: Optional[str] = None) -> Optional[Skill]:
        """Get skill by name (optionally within enterprise)."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            if enterprise_id:
                cur.execute(
                    "SELECT * FROM skills WHERE name = %s AND enterprise_id = %s",
                    (name, enterprise_id)
                )
            else:
                cur.execute(
                    "SELECT * FROM skills WHERE name = %s",
                    (name,)
                )
            row = cur.fetchone()
        
        return self._row_to_skill(row) if row else None

    def search(
        self,
        enterprise_id: Optional[str] = None,
        category: Optional[SkillCategory] = None,
        status: Optional[SkillStatus] = None,
        business_type: Optional[str] = None,
        keyword: Optional[str] = None,
        trigger: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Skill]:
        """Search skills with filters."""
        conn = self._get_connection()
        
        conditions = []
        params = []
        
        if enterprise_id:
            conditions.append("(enterprise_id = %s OR enterprise_id IS NULL)")
            params.append(enterprise_id)
        
        if category:
            conditions.append("category = %s")
            params.append(category.value)
        
        if status:
            conditions.append("status = %s")
            params.append(status.value)
        
        if business_type:
            conditions.append("business_type = %s")
            params.append(business_type)
        
        if keyword:
            conditions.append("fts_vector @@ plainto_tsquery('chinese', %s)")
            params.append(keyword)
        
        if trigger:
            conditions.append("%s = ANY(triggers)")
            params.append(trigger)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT * FROM skills
            WHERE {where_clause}
            ORDER BY invocation_count DESC, created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        
        return [self._row_to_skill(row) for row in rows]

    def search_by_trigger(self, query_text: str, enterprise_id: Optional[str] = None, limit: int = 5) -> list[Skill]:
        """Find skills matching a user's query text using triggers and capabilities."""
        conn = self._get_connection()
        
        pattern = f"%{query_text}%"
        
        with conn.cursor() as cur:
            if enterprise_id:
                cur.execute(
                    """
                    SELECT * FROM skills
                    WHERE status = 'active'
                    AND (enterprise_id = %s OR enterprise_id IS NULL)
                    AND (
                        %s = ANY(triggers) OR
                        %s = ANY(capabilities) OR
                        display_name ILIKE %s OR
                        name ILIKE %s
                    )
                    ORDER BY 
                        CASE WHEN %s = ANY(triggers) THEN 0 ELSE 1 END,
                        invocation_count DESC
                    LIMIT %s
                    """,
                    (enterprise_id, query_text, query_text, pattern, pattern, query_text, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM skills
                    WHERE status = 'active'
                    AND (
                        %s = ANY(triggers) OR
                        %s = ANY(capabilities) OR
                        display_name ILIKE %s OR
                        name ILIKE %s
                    )
                    ORDER BY 
                        CASE WHEN %s = ANY(triggers) THEN 0 ELSE 1 END,
                        invocation_count DESC
                    LIMIT %s
                    """,
                    (query_text, query_text, pattern, pattern, query_text, limit)
                )
            rows = cur.fetchall()
        
        return [self._row_to_skill(row) for row in rows]

    def update(self, skill_id: str, **kwargs) -> Optional[Skill]:
        """Update skill fields."""
        conn = self._get_connection()
        
        if not kwargs:
            return self.get_by_id(skill_id)
        
        set_clauses = []
        params = []
        
        for key, value in kwargs.items():
            if key in ["id", "created_at", "parameters"]:
                continue
            
            if isinstance(value, Enum):
                value = value.value
            elif key == "metadata":
                value = json.dumps(value)
            elif key == "parameters" and isinstance(value, list):
                value = json.dumps([p.model_dump() if hasattr(p, 'model_dump') else p for p in value])
            elif isinstance(value, list):
                pass
            else:
                pass
            
            set_clauses.append(f"{key} = %s")
            params.append(value)
        
        if not set_clauses:
            return self.get_by_id(skill_id)
        
        params.append(skill_id)
        
        query = f"""
            UPDATE skills SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING *
        """
        
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        
        conn.commit()
        
        return self._row_to_skill(row) if row else None

    def delete(self, skill_id: str) -> bool:
        """Delete a skill."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute("DELETE FROM skills WHERE id = %s RETURNING id", (skill_id,))
            deleted = cur.fetchone() is not None
        
        conn.commit()
        return deleted

    def count(
        self,
        enterprise_id: Optional[str] = None,
        category: Optional[SkillCategory] = None,
        status: Optional[SkillStatus] = None,
    ) -> int:
        """Count skills with filters."""
        conn = self._get_connection()
        
        conditions = []
        params = []
        
        if enterprise_id:
            conditions.append("enterprise_id = %s")
            params.append(enterprise_id)
        
        if category:
            conditions.append("category = %s")
            params.append(category.value)
        
        if status:
            conditions.append("status = %s")
            params.append(status.value)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM skills WHERE {where_clause}", params)
            count = cur.fetchone()[0]
        
        return count

    def record_invocation(
        self,
        skill_id: str,
        skill_name: str,
        user_id: str,
        input_summary: str,
        duration_ms: int,
        enterprise_id: Optional[str] = None,
        output_summary: Optional[str] = None,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> SkillInvocation:
        """Record a skill invocation."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO skill_invocations 
                (skill_id, skill_name, user_id, enterprise_id, input_summary, output_summary, status, error_message, duration_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    skill_id, skill_name, user_id, enterprise_id,
                    input_summary[:500], output_summary[:500] if output_summary else None,
                    status, error_message, duration_ms
                ),
            )
            row = cur.fetchone()
        
        conn.commit()
        
        # Update skill statistics
        with conn.cursor() as cur:
            if status == "success":
                cur.execute(
                    """
                    UPDATE skills 
                    SET invocation_count = invocation_count + 1,
                        success_count = success_count + 1,
                        last_used_at = NOW()
                    WHERE id = %s
                    """,
                    (skill_id,)
                )
            else:
                cur.execute(
                    """
                    UPDATE skills 
                    SET invocation_count = invocation_count + 1,
                        failure_count = failure_count + 1,
                        last_used_at = NOW()
                    WHERE id = %s
                    """,
                    (skill_id,)
                )
        
        conn.commit()
        
        return SkillInvocation(
            id=str(row[0]),
            skill_id=str(row[1]),
            skill_name=row[2],
            user_id=row[3],
            enterprise_id=row[4],
            input_summary=row[5],
            output_summary=row[6],
            status=row[7],
            error_message=row[8],
            duration_ms=row[9],
            created_at=row[10],
        )

    def get_invocation_history(
        self,
        skill_id: Optional[str] = None,
        user_id: Optional[str] = None,
        enterprise_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[SkillInvocation]:
        """Get skill invocation history."""
        conn = self._get_connection()
        
        conditions = []
        params = []
        
        if skill_id:
            conditions.append("skill_id = %s")
            params.append(skill_id)
        
        if user_id:
            conditions.append("user_id = %s")
            params.append(user_id)
        
        if enterprise_id:
            conditions.append("enterprise_id = %s")
            params.append(enterprise_id)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM skill_invocations
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                params + [limit]
            )
            rows = cur.fetchall()
        
        return [
            SkillInvocation(
                id=str(row[0]),
                skill_id=str(row[1]) if row[1] else "",
                skill_name=row[2],
                user_id=row[3],
                enterprise_id=row[4],
                input_summary=row[5],
                output_summary=row[6],
                status=row[7],
                error_message=row[8],
                duration_ms=row[9],
                created_at=row[10],
            )
            for row in rows
        ]

    def get_statistics(
        self,
        enterprise_id: Optional[str] = None,
    ) -> dict:
        """Get skill usage statistics."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            if enterprise_id:
                cur.execute(
                    """
                    SELECT 
                        COUNT(*) as total_skills,
                        SUM(invocation_count) as total_invocations,
                        SUM(success_count) as total_successes,
                        SUM(failure_count) as total_failures,
                        AVG(CASE WHEN invocation_count > 0 THEN success_count * 100.0 / invocation_count END) as success_rate
                    FROM skills
                    WHERE enterprise_id = %s OR enterprise_id IS NULL
                    """,
                    (enterprise_id,)
                )
            else:
                cur.execute(
                    """
                    SELECT 
                        COUNT(*) as total_skills,
                        SUM(invocation_count) as total_invocations,
                        SUM(success_count) as total_successes,
                        SUM(failure_count) as total_failures,
                        AVG(CASE WHEN invocation_count > 0 THEN success_count * 100.0 / invocation_count END) as success_rate
                    FROM skills
                    """
                )
            
            row = cur.fetchone()
            
            # Top skills by usage
            cur.execute(
                """
                SELECT name, display_name, invocation_count, success_count
                FROM skills
                WHERE status = 'active'
                ORDER BY invocation_count DESC
                LIMIT 10
                """
            )
            top_skills = [
                {"name": r[0], "display_name": r[1], "invocations": r[2], "successes": r[3]}
                for r in cur.fetchall()
            ]
        
        return {
            "total_skills": row[0] or 0,
            "total_invocations": row[1] or 0,
            "total_successes": row[2] or 0,
            "total_failures": row[3] or 0,
            "success_rate": round(row[4] or 0, 1),
            "top_skills": top_skills,
        }

    def _row_to_skill(self, row: tuple) -> Optional[Skill]:
        """Convert database row to Skill model."""
        if not row:
            return None
        
        # Parse parameters if stored as JSON
        parameters = []
        if row[10]:  # config field, adjust index based on schema
            pass  # Already stored as JSONB
        
        return Skill(
            id=str(row[0]),
            name=row[1],
            display_name=row[2],
            description=row[3],
            category=SkillCategory(row[4]) if row[4] else SkillCategory.OTHER,
            tags=row[5] or [],
            status=SkillStatus(row[6]) if row[6] else SkillStatus.DRAFT,
            enterprise_id=row[7],
            business_type=row[8],
            triggers=row[9] or [],
            capabilities=row[10] or [],
            limitations=row[11] or [],
            config=row[12] or {},
            source=row[13] or "local",
            source_url=row[14],
            version=row[15] or "1.0.0",
            invocation_count=row[16] or 0,
            success_count=row[17] or 0,
            failure_count=row[18] or 0,
            skill_md=row[19],
            readme=row[20],
            metadata=row[21] or {},
            created_at=row[22],
            updated_at=row[23],
            last_used_at=row[24],
        )

    def close(self) -> None:
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None


# Convenience function
def get_skill_service(
    host: str = "localhost",
    port: int = 5432,
    database: str = "nanobot_db",
    user: str = "postgres",
    password: str = "postgres",
) -> PostgresSkillService:
    """Get a configured skill service instance."""
    return PostgresSkillService(host, port, database, user, password)