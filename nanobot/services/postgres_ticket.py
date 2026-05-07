"""PostgreSQL Ticket Service.

Stores tickets, workflow status, and assignment data in PostgreSQL.
Supports ticket lifecycle management with status transitions.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    """Ticket status states."""
    OPEN = "open"                  # Newly created
    PENDING = "pending"            # Waiting for customer response
    IN_PROGRESS = "in_progress"   # Being handled
    RESOLVED = "resolved"          # Solved, awaiting confirmation
    CLOSED = "closed"              # Confirmed resolved or archived
    CANCELLED = "cancelled"       # Cancelled


class TicketPriority(str, Enum):
    """Ticket priority levels."""
    P1_CRITICAL = "p1"  # Critical, immediate response
    P2_HIGH = "p2"      # High priority
    P3_NORMAL = "p3"    # Normal priority
    P4_LOW = "p4"       # Low priority


class TicketCategory(str, Enum):
    """Ticket categories by business type."""
    TECHNICAL = "technical"       # Technical issues
    BILLING = "billing"           # Billing/payment issues
    PRODUCT = "product"            # Product inquiry
    COMPLAINT = "complaint"       # Complaints
    SUGGESTION = "suggestion"     # Suggestions
    OTHER = "other"               # Other issues


class TicketSource(str, Enum):
    """Ticket source channels."""
    FEISHU = "feishu"
    WECHAT = "wechat"
    WEB = "web"
    API = "api"
    PHONE = "phone"
    EMAIL = "email"


class Message(BaseModel):
    """Message in ticket conversation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    ticket_id: str
    sender_id: str
    sender_name: str
    sender_type: str = "user"  # user, agent, bot, system
    content: str
    content_type: str = "text"  # text, image, file, card
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)


class Ticket(BaseModel):
    """Ticket model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    
    # Basic info
    title: str
    description: str
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.P3_NORMAL
    status: TicketStatus = TicketStatus.OPEN
    source: TicketSource = TicketSource.FEISHU
    
    # Customer info
    customer_id: str
    customer_name: str
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    
    # Assignment
    assigned_to: Optional[str] = None
    assigned_name: Optional[str] = None
    department: Optional[str] = None
    
    # Enterprise (for multi-tenant)
    enterprise_id: Optional[str] = None
    
    # Resolution
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    
    # Feedback
    rating: Optional[int] = None  # 1-5 stars
    feedback: Optional[str] = None
    
    # Metadata
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Messages
    messages: list[Message] = Field(default_factory=list)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    closed_at: Optional[datetime] = None


class PostgresTicketService:
    """PostgreSQL Ticket Service.
    
    Usage:
        ticket_service = PostgresTicketService()
        ticket_service.init_db()
        
        # Create ticket
        ticket = ticket_service.create(
            title="无法登录",
            description="登录时提示密码错误",
            customer_id="user_001",
            customer_name="张三",
            category=TicketCategory.TECHNICAL,
            priority=TicketPriority.P2_HIGH
        )
        
        # Add message
        ticket_service.add_message(ticket.id, "user_001", "张三", "我已经重置密码了")
        
        # Update status
        ticket_service.update_status(ticket.id, TicketStatus.IN_PROGRESS)
        
        # Search tickets
        tickets = ticket_service.search(
            enterprise_id="ent_001",
            status=TicketStatus.OPEN,
            category=TicketCategory.TECHNICAL
        )
        
        # Get ticket with messages
        ticket = ticket_service.get_by_id(ticket.id, include_messages=True)
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
        """Initialize database schema for tickets."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            # Enable UUID extension
            cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            
            # Create tickets table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    
                    -- Basic info
                    title VARCHAR(500) NOT NULL,
                    description TEXT,
                    category VARCHAR(50) NOT NULL DEFAULT 'other',
                    priority VARCHAR(10) NOT NULL DEFAULT 'p3',
                    status VARCHAR(30) NOT NULL DEFAULT 'open',
                    source VARCHAR(20) NOT NULL DEFAULT 'feishu',
                    
                    -- Customer info
                    customer_id VARCHAR(100) NOT NULL,
                    customer_name VARCHAR(200),
                    customer_email VARCHAR(255),
                    customer_phone VARCHAR(50),
                    
                    -- Assignment
                    assigned_to VARCHAR(100),
                    assigned_name VARCHAR(200),
                    department VARCHAR(100),
                    
                    -- Enterprise (multi-tenant)
                    enterprise_id VARCHAR(100),
                    
                    -- Resolution
                    resolution TEXT,
                    resolved_at TIMESTAMP,
                    resolved_by VARCHAR(100),
                    
                    -- Feedback
                    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
                    feedback TEXT,
                    
                    -- Metadata
                    tags TEXT[] DEFAULT '{}',
                    metadata JSONB DEFAULT '{}',
                    
                    -- Timestamps
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    closed_at TIMESTAMP
                )
            """)
            
            # Create messages table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_messages (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    ticket_id UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
                    sender_id VARCHAR(100) NOT NULL,
                    sender_name VARCHAR(200),
                    sender_type VARCHAR(20) NOT NULL DEFAULT 'user',
                    content TEXT NOT NULL,
                    content_type VARCHAR(20) NOT NULL DEFAULT 'text',
                    metadata JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
            
            # Create indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_enterprise ON tickets(enterprise_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_customer ON tickets(customer_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_category ON tickets(category)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_assigned ON tickets(assigned_to)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_tickets_created ON tickets(created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_messages_ticket ON ticket_messages(ticket_id)")
            
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
            cur.execute("DROP TRIGGER IF EXISTS update_tickets_updated_at ON tickets")
            cur.execute("""
                CREATE TRIGGER update_tickets_updated_at
                BEFORE UPDATE ON tickets
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column()
            """)
        
        conn.commit()
        logger.info(f"Tickets table initialized in '{self.database}'")

    def create(self, **kwargs) -> Ticket:
        """Create a new ticket."""
        conn = self._get_connection()
        
        fields = []
        values = []
        params = []
        
        for key, value in kwargs.items():
            if key in ["id", "created_at", "updated_at", "messages"]:
                continue
            fields.append(key)
            if isinstance(value, Enum):
                values.append(value.value)
            elif key == "metadata":
                values.append(json.dumps(value))
            elif key == "tags":
                values.append(value)
            else:
                values.append(value)
            params.append(values[-1])
        
        query = f"""
            INSERT INTO tickets ({', '.join(fields)})
            VALUES ({', '.join(['%s'] * len(fields))})
            RETURNING *
        """
        
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        
        conn.commit()
        
        return self._row_to_ticket(row)

    def get_by_id(self, ticket_id: str, include_messages: bool = False) -> Optional[Ticket]:
        """Get ticket by ID."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tickets WHERE id = %s", (ticket_id,))
            row = cur.fetchone()
        
        if not row:
            return None
        
        ticket = self._row_to_ticket(row)
        
        if include_messages:
            ticket.messages = self._get_messages(ticket_id)
        
        return ticket

    def search(
        self,
        enterprise_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        status: Optional[TicketStatus] = None,
        priority: Optional[TicketPriority] = None,
        category: Optional[TicketCategory] = None,
        assigned_to: Optional[str] = None,
        department: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Ticket]:
        """Search tickets with filters."""
        conn = self._get_connection()
        
        conditions = []
        params = []
        
        if enterprise_id:
            conditions.append("enterprise_id = %s")
            params.append(enterprise_id)
        
        if customer_id:
            conditions.append("customer_id = %s")
            params.append(customer_id)
        
        if status:
            conditions.append("status = %s")
            params.append(status.value)
        
        if priority:
            conditions.append("priority = %s")
            params.append(priority.value)
        
        if category:
            conditions.append("category = %s")
            params.append(category.value)
        
        if assigned_to:
            conditions.append("assigned_to = %s")
            params.append(assigned_to)
        
        if department:
            conditions.append("department = %s")
            params.append(department)
        
        if keyword:
            conditions.append("(title ILIKE %s OR description ILIKE %s)")
            pattern = f"%{keyword}%"
            params.extend([pattern, pattern])
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT * FROM tickets
            WHERE {where_clause}
            ORDER BY 
                CASE priority 
                    WHEN 'p1' THEN 1 
                    WHEN 'p2' THEN 2 
                    WHEN 'p3' THEN 3 
                    WHEN 'p4' THEN 4 
                END,
                created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        
        return [self._row_to_ticket(row) for row in rows]

    def update(self, ticket_id: str, **kwargs) -> Optional[Ticket]:
        """Update ticket fields."""
        conn = self._get_connection()
        
        if not kwargs:
            return self.get_by_id(ticket_id)
        
        set_clauses = []
        params = []
        
        for key, value in kwargs.items():
            if key in ["id", "created_at", "messages"]:
                continue
            set_clauses.append(f"{key} = %s")
            if isinstance(value, Enum):
                params.append(value.value)
            elif key == "metadata":
                params.append(json.dumps(value))
            elif key == "tags":
                params.append(value)
            else:
                params.append(value)
        
        if not set_clauses:
            return self.get_by_id(ticket_id)
        
        params.append(ticket_id)
        
        query = f"""
            UPDATE tickets SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING *
        """
        
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        
        conn.commit()
        
        return self._row_to_ticket(row) if row else None

    def update_status(self, ticket_id: str, status: TicketStatus, resolution: Optional[str] = None) -> Optional[Ticket]:
        """Update ticket status with optional resolution."""
        conn = self._get_connection()
        
        if status == TicketStatus.RESOLVED:
            kwargs = {"status": status, "resolved_at": datetime.now()}
            if resolution:
                kwargs["resolution"] = resolution
        elif status == TicketStatus.CLOSED:
            kwargs = {"status": status, "closed_at": datetime.now()}
            if resolution:
                kwargs["resolution"] = resolution
        else:
            kwargs = {"status": status}
        
        return self.update(ticket_id, **kwargs)

    def assign(self, ticket_id: str, assigned_to: str, assigned_name: str, department: Optional[str] = None) -> Optional[Ticket]:
        """Assign ticket to an agent."""
        kwargs = {"assigned_to": assigned_to, "assigned_name": assigned_name}
        if department:
            kwargs["department"] = department
        return self.update(ticket_id, **kwargs)

    def add_message(
        self,
        ticket_id: str,
        sender_id: str,
        sender_name: str,
        content: str,
        sender_type: str = "user",
        content_type: str = "text",
        metadata: Optional[dict] = None,
    ) -> Message:
        """Add a message to ticket conversation."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ticket_messages 
                (ticket_id, sender_id, sender_name, sender_type, content, content_type, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    ticket_id,
                    sender_id,
                    sender_name,
                    sender_type,
                    content,
                    content_type,
                    json.dumps(metadata or {}),
                ),
            )
            row = cur.fetchone()
        
        conn.commit()
        
        return Message(
            id=str(row[0]),
            ticket_id=str(row[1]),
            sender_id=row[2],
            sender_name=row[3],
            sender_type=row[4],
            content=row[5],
            content_type=row[6],
            metadata=row[7] or {},
            created_at=row[8],
        )

    def set_feedback(self, ticket_id: str, rating: int, feedback: Optional[str] = None) -> Optional[Ticket]:
        """Set customer feedback for ticket."""
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")
        return self.update(ticket_id, rating=rating, feedback=feedback)

    def delete(self, ticket_id: str) -> bool:
        """Delete a ticket (cascades to messages)."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute("DELETE FROM tickets WHERE id = %s RETURNING id", (ticket_id,))
            deleted = cur.fetchone() is not None
        
        conn.commit()
        return deleted

    def count(
        self,
        enterprise_id: Optional[str] = None,
        status: Optional[TicketStatus] = None,
        priority: Optional[TicketPriority] = None,
        category: Optional[TicketCategory] = None,
        assigned_to: Optional[str] = None,
    ) -> int:
        """Count tickets with filters."""
        conn = self._get_connection()
        
        conditions = []
        params = []
        
        if enterprise_id:
            conditions.append("enterprise_id = %s")
            params.append(enterprise_id)
        
        if status:
            conditions.append("status = %s")
            params.append(status.value)
        
        if priority:
            conditions.append("priority = %s")
            params.append(priority.value)
        
        if category:
            conditions.append("category = %s")
            params.append(category.value)
        
        if assigned_to:
            conditions.append("assigned_to = %s")
            params.append(assigned_to)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM tickets WHERE {where_clause}", params)
            count = cur.fetchone()[0]
        
        return count

    def get_statistics(
        self,
        enterprise_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> dict:
        """Get ticket statistics."""
        conn = self._get_connection()
        
        conditions = []
        params = []
        
        if enterprise_id:
            conditions.append("enterprise_id = %s")
            params.append(enterprise_id)
        
        if start_date:
            conditions.append("created_at >= %s")
            params.append(start_date)
        
        if end_date:
            conditions.append("created_at <= %s")
            params.append(end_date)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with conn.cursor() as cur:
            # Total count
            cur.execute(f"SELECT COUNT(*) FROM tickets WHERE {where_clause}", params)
            total = cur.fetchone()[0]
            
            # By status
            cur.execute(
                f"""
                SELECT status, COUNT(*) 
                FROM tickets WHERE {where_clause}
                GROUP BY status
                """,
                params,
            )
            by_status = {row[0]: row[1] for row in cur.fetchall()}
            
            # By priority
            cur.execute(
                f"""
                SELECT priority, COUNT(*) 
                FROM tickets WHERE {where_clause}
                GROUP BY priority
                """,
                params,
            )
            by_priority = {row[0]: row[1] for row in cur.fetchall()}
            
            # By category
            cur.execute(
                f"""
                SELECT category, COUNT(*) 
                FROM tickets WHERE {where_clause}
                GROUP BY category
                """,
                params,
            )
            by_category = {row[0]: row[1] for row in cur.fetchall()}
            
            # Avg resolution time (for resolved tickets)
            cur.execute(
                f"""
                SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at))/3600) 
                FROM tickets 
                WHERE {where_clause} AND resolved_at IS NOT NULL
                """,
                params,
            )
            avg_resolution_hours = cur.fetchone()[0]
            
            # Satisfaction rating
            cur.execute(
                f"""
                SELECT AVG(rating), COUNT(*) 
                FROM tickets 
                WHERE {where_clause} AND rating IS NOT NULL
                """,
                params,
            )
            avg_rating, rating_count = cur.fetchone()
        
        return {
            "total": total,
            "by_status": by_status,
            "by_priority": by_priority,
            "by_category": by_category,
            "avg_resolution_hours": round(avg_resolution_hours, 1) if avg_resolution_hours else None,
            "avg_rating": round(float(avg_rating), 1) if avg_rating else None,
            "rating_count": rating_count,
        }

    def _get_messages(self, ticket_id: str) -> list[Message]:
        """Get messages for a ticket."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM ticket_messages WHERE ticket_id = %s ORDER BY created_at",
                (ticket_id,),
            )
            rows = cur.fetchall()
        
        return [
            Message(
                id=str(row[0]),
                ticket_id=str(row[1]),
                sender_id=row[2],
                sender_name=row[3],
                sender_type=row[4],
                content=row[5],
                content_type=row[6],
                metadata=row[7] or {},
                created_at=row[8],
            )
            for row in rows
        ]

    def _row_to_ticket(self, row: tuple) -> Ticket:
        """Convert database row to Ticket model."""
        return Ticket(
            id=str(row[0]),
            title=row[1],
            description=row[2],
            category=TicketCategory(row[3]) if row[3] else TicketCategory.OTHER,
            priority=TicketPriority(row[4]) if row[4] else TicketPriority.P3_NORMAL,
            status=TicketStatus(row[5]) if row[5] else TicketStatus.OPEN,
            source=TicketSource(row[6]) if row[6] else TicketSource.FEISHU,
            customer_id=row[7],
            customer_name=row[8],
            customer_email=row[9],
            customer_phone=row[10],
            assigned_to=row[11],
            assigned_name=row[12],
            department=row[13],
            enterprise_id=row[14],
            resolution=row[15],
            resolved_at=row[16],
            resolved_by=row[17],
            rating=row[18],
            feedback=row[19],
            tags=row[20] or [],
            metadata=row[21] or {},
            created_at=row[22],
            updated_at=row[23],
            closed_at=row[24],
        )

    def close(self) -> None:
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None


# Convenience function
def get_ticket_service(
    host: str = "localhost",
    port: int = 5432,
    database: str = "nanobot_db",
    user: str = "postgres",
    password: str = "postgres",
) -> PostgresTicketService:
    """Get a configured ticket service instance."""
    return PostgresTicketService(host, port, database, user, password)