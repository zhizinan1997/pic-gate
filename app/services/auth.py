"""
PicGate Authentication Service
Handles admin user authentication with bcrypt password hashing.
"""

import bcrypt
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models import Admin


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    return bcrypt.checkpw(
        password.encode('utf-8'), 
        password_hash.encode('utf-8')
    )


async def get_admin_by_username(db: AsyncSession, username: str) -> Optional[Admin]:
    """Get admin by username."""
    result = await db.execute(
        select(Admin).where(Admin.username == username)
    )
    return result.scalar_one_or_none()


async def create_admin(db: AsyncSession, username: str, password: str) -> Admin:
    """Create a new admin user."""
    admin = Admin(
        username=username,
        password_hash=hash_password(password)
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)
    return admin


async def authenticate_admin(db: AsyncSession, username: str, password: str) -> Optional[Admin]:
    """Authenticate admin with username and password."""
    admin = await get_admin_by_username(db, username)
    if admin and verify_password(password, admin.password_hash):
        return admin
    return None


async def has_any_admin(db: AsyncSession) -> bool:
    """Check if any admin exists (for initial setup detection)."""
    result = await db.execute(select(func.count(Admin.id)))
    count = result.scalar()
    return count > 0
