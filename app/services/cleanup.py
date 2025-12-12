"""
PicGate Cleanup Service
Handles TTL-based cache cleanup and R2 upload processing.

Features:
- Delete local files past TTL
- Delete old metadata entries
- Process pending R2 uploads
- Retry failed R2 uploads
"""

import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete

from app.models import Image
from app.config import IMAGES_DIR
from app.services.r2_client import R2Client, create_r2_client
from app.services.settings_service import get_settings

logger = logging.getLogger(__name__)


async def cleanup_expired_local(db: AsyncSession) -> Dict[str, Any]:
    """
    Delete local image files that have exceeded the TTL.
    
    Flow:
    1. Get TTL from settings
    2. Find images with has_local_copy=True older than TTL
    3. Delete local files
    4. Update database (has_local_copy=False)
    
    Returns:
        Dict with cleanup results
    """
    settings = await get_settings(db)
    ttl_hours = settings.local_cache_ttl_hours or 72  # Default 3 days
    
    cutoff_time = datetime.utcnow() - timedelta(hours=ttl_hours)
    
    # Find expired images with local copy
    result = await db.execute(
        select(Image).where(
            and_(
                Image.has_local_copy == True,
                Image.last_accessed_at < cutoff_time
            )
        )
    )
    expired_images = result.scalars().all()
    
    deleted_count = 0
    deleted_bytes = 0
    errors = []
    
    for image in expired_images:
        try:
            # Delete local file
            if image.local_path:
                local_file = IMAGES_DIR / image.local_path
                if local_file.exists():
                    file_size = local_file.stat().st_size
                    local_file.unlink()
                    deleted_bytes += file_size
                    logger.info(f"Deleted expired local file: {image.image_id}")
            
            # Update database
            image.has_local_copy = False
            deleted_count += 1
            
        except Exception as e:
            error_msg = f"Failed to delete {image.image_id}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
    
    await db.commit()
    
    return {
        "deleted_count": deleted_count,
        "deleted_bytes": deleted_bytes,
        "deleted_mb": round(deleted_bytes / (1024 * 1024), 2),
        "ttl_hours": ttl_hours,
        "errors": errors
    }


async def cleanup_expired_metadata(db: AsyncSession) -> Dict[str, Any]:
    """
    Delete old metadata entries past the retention period.
    
    Flow:
    1. Get retention days from settings
    2. Find images older than retention period with no local/R2 copy
    3. Optionally delete from R2 if configured
    4. Delete metadata from database
    
    Returns:
        Dict with cleanup results
    """
    settings = await get_settings(db)
    retention_days = settings.metadata_retention_days or 365
    delete_r2 = settings.delete_r2_on_metadata_expire
    
    cutoff_time = datetime.utcnow() - timedelta(days=retention_days)
    
    # Find old images without local copy (already cleaned)
    result = await db.execute(
        select(Image).where(
            and_(
                Image.has_local_copy == False,
                Image.created_at < cutoff_time
            )
        )
    )
    old_images = result.scalars().all()
    
    deleted_count = 0
    r2_deleted_count = 0
    errors = []
    
    # Create R2 client if needed for deletion
    r2_client = None
    if delete_r2:
        r2_client = create_r2_client(settings)
    
    for image in old_images:
        try:
            # Optionally delete from R2
            if delete_r2 and image.has_r2_copy and r2_client:
                success, error = await r2_client.delete_image(image.image_id)
                if success:
                    r2_deleted_count += 1
                else:
                    logger.warning(f"R2 delete failed for {image.image_id}: {error}")
            
            # Delete from database
            await db.delete(image)
            deleted_count += 1
            
        except Exception as e:
            error_msg = f"Failed to cleanup metadata for {image.image_id}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)
    
    await db.commit()
    
    return {
        "deleted_count": deleted_count,
        "r2_deleted_count": r2_deleted_count,
        "retention_days": retention_days,
        "errors": errors
    }


async def process_pending_uploads(db: AsyncSession, limit: int = 50) -> Dict[str, Any]:
    """
    Process pending R2 uploads.
    
    Uploads images with upload_status='pending' to R2.
    
    Args:
        db: Database session
        limit: Maximum number of images to process
        
    Returns:
        Dict with upload results
    """
    settings = await get_settings(db)
    r2_client = create_r2_client(settings)
    
    if not r2_client:
        return {
            "success": False,
            "message": "R2 not configured",
            "uploaded_count": 0
        }
    
    # Find pending images with local copy
    result = await db.execute(
        select(Image).where(
            and_(
                Image.upload_status == "pending",
                Image.has_local_copy == True
            )
        ).limit(limit)
    )
    pending_images = result.scalars().all()
    
    uploaded_count = 0
    failed_count = 0
    errors = []
    
    for image in pending_images:
        try:
            # Read local file
            if not image.local_path:
                continue
                
            local_file = IMAGES_DIR / image.local_path
            if not local_file.exists():
                image.has_local_copy = False
                image.upload_status = "failed"
                image.upload_error = "Local file not found"
                continue
            
            image_bytes = local_file.read_bytes()
            
            # Upload to R2
            image.upload_status = "uploading"
            await db.commit()
            
            success, error = await r2_client.upload_image(
                image.image_id,
                image_bytes,
                image.content_type or "image/png"
            )
            
            if success:
                image.has_r2_copy = True
                image.upload_status = "uploaded"
                image.upload_error = ""
                uploaded_count += 1
            else:
                image.upload_status = "failed"
                image.upload_error = error or "Unknown error"
                failed_count += 1
                errors.append(f"{image.image_id}: {error}")
            
        except Exception as e:
            error_msg = f"Upload error for {image.image_id}: {e}"
            logger.error(error_msg)
            image.upload_status = "failed"
            image.upload_error = str(e)
            failed_count += 1
            errors.append(error_msg)
    
    await db.commit()
    
    return {
        "success": True,
        "uploaded_count": uploaded_count,
        "failed_count": failed_count,
        "total_processed": len(pending_images),
        "errors": errors
    }


async def retry_failed_uploads(db: AsyncSession, limit: int = 50) -> Dict[str, Any]:
    """
    Retry failed R2 uploads.
    
    Resets failed images to 'pending' and processes them.
    
    Args:
        db: Database session
        limit: Maximum number of images to retry
        
    Returns:
        Dict with retry results
    """
    # Reset failed uploads to pending
    result = await db.execute(
        select(Image).where(
            and_(
                Image.upload_status == "failed",
                Image.has_local_copy == True
            )
        ).limit(limit)
    )
    failed_images = result.scalars().all()
    
    reset_count = 0
    for image in failed_images:
        image.upload_status = "pending"
        image.upload_error = ""
        reset_count += 1
    
    await db.commit()
    
    if reset_count == 0:
        return {
            "success": True,
            "message": "No failed uploads to retry",
            "reset_count": 0,
            "upload_results": None
        }
    
    # Process the reset uploads
    upload_results = await process_pending_uploads(db, limit)
    
    return {
        "success": True,
        "message": f"Reset {reset_count} failed uploads",
        "reset_count": reset_count,
        "upload_results": upload_results
    }


async def download_from_r2(db: AsyncSession, image_id: str) -> bytes | None:
    """
    Download an image from R2 and save locally.
    
    Used when local file is missing but R2 copy exists.
    
    Args:
        db: Database session
        image_id: UUID of the image
        
    Returns:
        Image bytes if successful, None otherwise
    """
    settings = await get_settings(db)
    r2_client = create_r2_client(settings)
    
    if not r2_client:
        logger.warning("R2 not configured, cannot download")
        return None
    
    # Get image metadata
    result = await db.execute(
        select(Image).where(Image.image_id == image_id)
    )
    image = result.scalar_one_or_none()
    
    if not image:
        logger.warning(f"Image {image_id} not found in database")
        return None
    
    if not image.has_r2_copy:
        logger.warning(f"Image {image_id} has no R2 copy")
        return None
    
    # Download from R2
    image_bytes, error = await r2_client.download_image(image_id)
    
    if not image_bytes:
        logger.error(f"Failed to download {image_id} from R2: {error}")
        return None
    
    # Save locally
    try:
        filename = f"{image_id}.png"
        local_file = IMAGES_DIR / filename
        local_file.write_bytes(image_bytes)
        
        # Update database
        image.has_local_copy = True
        image.local_path = filename
        image.last_accessed_at = datetime.utcnow()
        await db.commit()
        
        logger.info(f"Downloaded {image_id} from R2 and saved locally")
        return image_bytes
        
    except Exception as e:
        logger.error(f"Failed to save downloaded image {image_id}: {e}")
        return None


async def schedule_r2_upload(db: AsyncSession, image_id: str):
    """
    Schedule an image for R2 upload.
    
    This is called asynchronously after saving an image locally.
    The actual upload happens in the background.
    """
    # For now, just mark as pending - actual upload happens via process_pending_uploads
    # In production, you might use a task queue like Celery or arq
    pass


# Background task to periodically process uploads
async def background_upload_task(db_session_factory, interval_seconds: int = 60):
    """
    Background task that periodically processes pending uploads.
    
    Args:
        db_session_factory: Async session factory
        interval_seconds: Seconds between runs
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            
            async with db_session_factory() as db:
                result = await process_pending_uploads(db)
                if result.get("uploaded_count", 0) > 0:
                    logger.info(f"Background upload: processed {result['uploaded_count']} images")
                    
        except Exception as e:
            logger.error(f"Background upload task error: {e}")


# Background task to periodically cleanup expired files
async def background_cleanup_task(db_session_factory, interval_seconds: int = 3600):
    """
    Background task that periodically cleans up expired cache.
    
    Args:
        db_session_factory: Async session factory
        interval_seconds: Seconds between runs (default 1 hour)
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            
            async with db_session_factory() as db:
                result = await cleanup_expired_local(db)
                if result.get("deleted_count", 0) > 0:
                    logger.info(f"Background cleanup: deleted {result['deleted_count']} expired files")
                    
        except Exception as e:
            logger.error(f"Background cleanup task error: {e}")
