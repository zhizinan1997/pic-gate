"""
PicGate Database Module
Async SQLAlchemy setup for SQLite.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.config import DATABASE_URL

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True
)

# Session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """Dependency for getting database session."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Initialize database tables and run migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # Run migrations for new columns (SQLite doesn't auto-add columns)
        await _run_migrations(conn)


async def _run_migrations(conn):
    """
    Run database migrations for schema updates.
    SQLite doesn't support ALTER TABLE ADD COLUMN through SQLAlchemy,
    so we need to do it manually.
    """
    import logging
    from sqlalchemy import text
    logger = logging.getLogger(__name__)
    
    def sync_migrations(connection):
        try:
            # Check if images table exists
            result = connection.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='images'")
            )
            if not result.fetchone():
                return  # Table doesn't exist yet, skip migration
            
            # Check if thumbnail_path column exists in images table
            result = connection.execute(
                text("SELECT name FROM pragma_table_info('images') WHERE name='thumbnail_path'")
            )
            if not result.fetchone():
                logger.info("Adding thumbnail_path column to images table")
                connection.execute(
                    text("ALTER TABLE images ADD COLUMN thumbnail_path VARCHAR(500) DEFAULT ''")
                )
                logger.info("thumbnail_path column added successfully")
        except Exception as e:
            # Log but don't fail - column might already exist or other issue
            logger.warning(f"Migration check/update: {e}")
    
    await conn.run_sync(sync_migrations)
