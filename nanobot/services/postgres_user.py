"""PostgreSQL User Identity Service.

Stores user identity, profiles, and enterprise data in PostgreSQL.
Supports multi-tenant architecture with enterprise-based data isolation.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel, Field


class UserStatus(str, Enum):
    """User account status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    PENDING = "pending"


class UserRole(str, Enum):
    """User roles in the system."""
    ADMIN = "admin"
    MANAGER = "manager"
    AGENT = "agent"
    CUSTOMER = "customer"
    GUEST = "guest"


class User(BaseModel):
    """User model."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    username: str
    email: Optional[str] = None
    phone: Optional[str] = None
    
    # Enterprise and organization
    enterprise_id: Optional[str] = None
    department: Optional[str] = None
    position: Optional[str] = None
    
    # Role and status
    role: UserRole = UserRole.CUSTOMER
    status: UserStatus = UserStatus.ACTIVE
    
    # Authentication
    password_hash: Optional[str] = None
    openid: Optional[str] = None  # Feishu/WeChat openid
    unionid: Optional[str] = None
    
    # Profile
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    language: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    
    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_login_at: Optional[datetime] = None


class PostgresUserService:
    """PostgreSQL User Identity Service.
    
    Usage:
        user_service = PostgresUserService()
        user_service.init_db()
        
        # Create user
        user = user_service.create(
            username="john",
            email="john@example.com",
            enterprise_id="ent_001",
            role=UserRole.CUSTOMER
        )
        
        # Get user
        user = user_service.get_by_id("user_id")
        user = user_service.get_by_username("john", enterprise_id="ent_001")
        
        # Search users
        users = user_service.search(enterprise_id="ent_001", role=UserRole.AGENT)
        
        # Update user
        user_service.update(user_id, display_name="John Doe")
        
        # Delete user
        user_service.delete(user_id)
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
        """Initialize database schema for users."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            # Enable UUID extension
            cur.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            
            # Create users table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                    username VARCHAR(100) NOT NULL,
                    email VARCHAR(255),
                    phone VARCHAR(50),
                    
                    -- Enterprise and organization
                    enterprise_id VARCHAR(100),
                    department VARCHAR(100),
                    position VARCHAR(100),
                    
                    -- Role and status
                    role VARCHAR(20) NOT NULL DEFAULT 'customer',
                    status VARCHAR(20) NOT NULL DEFAULT 'active',
                    
                    -- Authentication
                    password_hash VARCHAR(255),
                    openid VARCHAR(100),
                    unionid VARCHAR(100),
                    
                    -- Profile
                    display_name VARCHAR(200),
                    avatar_url VARCHAR(500),
                    language VARCHAR(10) DEFAULT 'zh-CN',
                    timezone VARCHAR(50) DEFAULT 'Asia/Shanghai',
                    
                    -- Metadata
                    metadata JSONB DEFAULT '{}',
                    
                    -- Timestamps
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    last_login_at TIMESTAMP,
                    
                    -- Constraints
                    CONSTRAINT unique_username_enterprise UNIQUE (username, enterprise_id),
                    CONSTRAINT unique_email_enterprise UNIQUE (email, enterprise_id)
                )
            """)
            
            # Create indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_enterprise ON users(enterprise_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_openid ON users(openid)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_unionid ON users(unionid)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
            
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
            cur.execute("""
                DROP TRIGGER IF EXISTS update_users_updated_at ON users
            """)
            cur.execute("""
                CREATE TRIGGER update_users_updated_at
                BEFORE UPDATE ON users
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column()
            """)
        
        conn.commit()
        logger.info(f"Users table initialized in '{self.database}'")

    def create(self, **kwargs) -> User:
        """Create a new user."""
        conn = self._get_connection()
        
        # Build insert statement
        fields = []
        values = []
        params = []
        
        for key, value in kwargs.items():
            if key in ["created_at", "updated_at", "id"]:
                continue
            fields.append(key)
            if isinstance(value, Enum):
                values.append(value.value)
            elif key == "metadata":
                values.append(json.dumps(value))
            else:
                values.append(value)
            params.append(values[-1])
        
        query = f"""
            INSERT INTO users ({', '.join(fields)})
            VALUES ({', '.join(['%s'] * len(fields))})
            RETURNING *
        """
        
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        
        conn.commit()
        
        return self._row_to_user(row)

    def get_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            row = cur.fetchone()
        
        return self._row_to_user(row) if row else None

    def get_by_username(self, username: str, enterprise_id: Optional[str] = None) -> Optional[User]:
        """Get user by username and optional enterprise."""
        conn = self._get_connection()
        
        if enterprise_id:
            cur.execute(
                "SELECT * FROM users WHERE username = %s AND enterprise_id = %s",
                (username, enterprise_id)
            )
        else:
            cur.execute(
                "SELECT * FROM users WHERE username = %s",
                (username,)
            )
        
        row = cur.fetchone()
        return self._row_to_user(row) if row else None

    def get_by_email(self, email: str, enterprise_id: Optional[str] = None) -> Optional[User]:
        """Get user by email."""
        conn = self._get_connection()
        
        if enterprise_id:
            cur.execute(
                "SELECT * FROM users WHERE email = %s AND enterprise_id = %s",
                (email, enterprise_id)
            )
        else:
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        
        row = cur.fetchone()
        return self._row_to_user(row) if row else None

    def get_by_openid(self, openid: str) -> Optional[User]:
        """Get user by Feishu/WeChat openid."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE openid = %s", (openid,))
            row = cur.fetchone()
        
        return self._row_to_user(row) if row else None

    def search(
        self,
        enterprise_id: Optional[str] = None,
        role: Optional[UserRole] = None,
        status: Optional[UserStatus] = None,
        department: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[User]:
        """Search users with filters."""
        conn = self._get_connection()
        
        conditions = []
        params = []
        
        if enterprise_id:
            conditions.append("enterprise_id = %s")
            params.append(enterprise_id)
        
        if role:
            conditions.append("role = %s")
            params.append(role.value)
        
        if status:
            conditions.append("status = %s")
            params.append(status.value)
        
        if department:
            conditions.append("department = %s")
            params.append(department)
        
        if keyword:
            conditions.append("(username ILIKE %s OR display_name ILIKE %s OR email ILIKE %s)")
            pattern = f"%{keyword}%"
            params.extend([pattern, pattern, pattern])
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT * FROM users
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([limit, offset])
        
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        
        return [self._row_to_user(row) for row in rows]

    def update(self, user_id: str, **kwargs) -> Optional[User]:
        """Update user fields."""
        conn = self._get_connection()
        
        if not kwargs:
            return self.get_by_id(user_id)
        
        set_clauses = []
        params = []
        
        for key, value in kwargs.items():
            if key in ["id", "created_at"]:
                continue
            set_clauses.append(f"{key} = %s")
            if isinstance(value, Enum):
                params.append(value.value)
            elif key == "metadata":
                params.append(json.dumps(value))
            else:
                params.append(value)
        
        if not set_clauses:
            return self.get_by_id(user_id)
        
        params.append(user_id)
        
        query = f"""
            UPDATE users SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING *
        """
        
        with conn.cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
        
        conn.commit()
        
        return self._row_to_user(row) if row else None

    def delete(self, user_id: str) -> bool:
        """Delete a user."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
            deleted = cur.fetchone() is not None
        
        conn.commit()
        return deleted

    def count(
        self,
        enterprise_id: Optional[str] = None,
        role: Optional[UserRole] = None,
        status: Optional[UserStatus] = None,
    ) -> int:
        """Count users with filters."""
        conn = self._get_connection()
        
        conditions = []
        params = []
        
        if enterprise_id:
            conditions.append("enterprise_id = %s")
            params.append(enterprise_id)
        
        if role:
            conditions.append("role = %s")
            params.append(role.value)
        
        if status:
            conditions.append("status = %s")
            params.append(status.value)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM users WHERE {where_clause}", params)
            count = cur.fetchone()[0]
        
        return count

    def update_last_login(self, user_id: str) -> None:
        """Update user's last login timestamp."""
        conn = self._get_connection()
        
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET last_login_at = NOW() WHERE id = %s",
                (user_id,)
            )
        
        conn.commit()

    def _row_to_user(self, row: tuple) -> Optional[User]:
        """Convert database row to User model."""
        if not row:
            return None
        
        return User(
            id=str(row[0]),
            username=row[1],
            email=row[2],
            phone=row[3],
            enterprise_id=row[4],
            department=row[5],
            position=row[6],
            role=UserRole(row[7]) if row[7] else UserRole.CUSTOMER,
            status=UserStatus(row[8]) if row[8] else UserStatus.ACTIVE,
            password_hash=row[9],
            openid=row[10],
            unionid=row[11],
            display_name=row[12],
            avatar_url=row[13],
            language=row[14] or "zh-CN",
            timezone=row[15] or "Asia/Shanghai",
            metadata=row[16] or {},
            created_at=row[17],
            updated_at=row[18],
            last_login_at=row[19],
        )

    def close(self) -> None:
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None


# Convenience function
def get_user_service(
    host: str = "localhost",
    port: int = 5432,
    database: str = "nanobot_db",
    user: str = "postgres",
    password: str = "postgres",
) -> PostgresUserService:
    """Get a configured user service instance."""
    return PostgresUserService(host, port, database, user, password)