"""
PicGate Settings Service
Handles application settings CRUD operations.
"""

from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.models import Settings


async def get_settings(db: AsyncSession) -> Settings:
    """
    Get the singleton settings row.
    Creates default settings if none exist.
    """
    result = await db.execute(select(Settings).where(Settings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        # Create default settings
        settings = Settings(id=1)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    
    return settings


async def update_settings(db: AsyncSession, updates: Dict[str, Any]) -> Settings:
    """
    Update settings with given values.
    Only updates fields that are provided in the updates dict.
    """
    settings = await get_settings(db)
    
    # List of allowed fields to update
    allowed_fields = [
        "upstream_api_base",
        "upstream_api_key", 
        "upstream_model_name",
        "gateway_api_key",
        "gateway_model_name",
        "public_base_url",
        "r2_account_id",
        "r2_access_key_id",
        "r2_secret_access_key",
        "r2_bucket_name",
        "local_cache_ttl_hours",
        "metadata_retention_days",
        "allow_external_image_fetch",
        "delete_r2_on_metadata_expire",
    ]
    
    for field in allowed_fields:
        if field in updates:
            setattr(settings, field, updates[field])
    
    settings.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(settings)
    
    return settings


def settings_to_dict(settings: Settings, hide_secrets: bool = True) -> Dict[str, Any]:
    """
    Convert settings to dictionary for API response.
    Optionally hides sensitive fields.
    """
    data = {
        "upstream_api_base": settings.upstream_api_base or "",
        "upstream_api_key": settings.upstream_api_key or "",
        "upstream_model_name": settings.upstream_model_name or "",
        "gateway_api_key": settings.gateway_api_key or "",
        "gateway_model_name": settings.gateway_model_name or "",
        "public_base_url": settings.public_base_url or "",
        "r2_account_id": settings.r2_account_id or "",
        "r2_access_key_id": settings.r2_access_key_id or "",
        "r2_secret_access_key": settings.r2_secret_access_key or "",
        "r2_bucket_name": settings.r2_bucket_name or "",
        "local_cache_ttl_hours": settings.local_cache_ttl_hours,
        "metadata_retention_days": settings.metadata_retention_days,
        "allow_external_image_fetch": settings.allow_external_image_fetch,
        "delete_r2_on_metadata_expire": settings.delete_r2_on_metadata_expire,
        "created_at": settings.created_at.isoformat() if settings.created_at else None,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }
    
    if hide_secrets:
        # Mask sensitive fields
        if data["upstream_api_key"]:
            data["upstream_api_key"] = "***" + data["upstream_api_key"][-4:] if len(data["upstream_api_key"]) > 4 else "****"
        if data["gateway_api_key"]:
            data["gateway_api_key"] = "***" + data["gateway_api_key"][-4:] if len(data["gateway_api_key"]) > 4 else "****"
        if data["r2_secret_access_key"]:
            data["r2_secret_access_key"] = "***" + data["r2_secret_access_key"][-4:] if len(data["r2_secret_access_key"]) > 4 else "****"
    
    return data
