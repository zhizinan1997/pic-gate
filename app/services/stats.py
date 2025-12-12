"""
PicGate Statistics Service
Provides cache and storage statistics.
"""

from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pathlib import Path

from app.models import Image
from app.config import IMAGES_DIR


async def get_stats(db: AsyncSession) -> Dict[str, Any]:
    """Get comprehensive statistics about images and storage."""
    
    # Count total images
    total_result = await db.execute(select(func.count(Image.id)))
    total_images = total_result.scalar() or 0
    
    # Count images with local copy
    local_result = await db.execute(
        select(func.count(Image.id)).where(Image.has_local_copy == True)
    )
    local_count = local_result.scalar() or 0
    
    # Count images with R2 copy
    r2_result = await db.execute(
        select(func.count(Image.id)).where(Image.has_r2_copy == True)
    )
    r2_count = r2_result.scalar() or 0
    
    # Count images pending upload
    pending_result = await db.execute(
        select(func.count(Image.id)).where(Image.upload_status == "pending")
    )
    pending_count = pending_result.scalar() or 0
    
    # Count failed uploads
    failed_result = await db.execute(
        select(func.count(Image.id)).where(Image.upload_status == "failed")
    )
    failed_count = failed_result.scalar() or 0
    
    # Total size in database
    size_result = await db.execute(
        select(func.sum(Image.size_bytes)).where(Image.has_local_copy == True)
    )
    total_size_bytes = size_result.scalar() or 0
    
    # Calculate actual disk usage
    disk_usage = calculate_disk_usage()
    
    return {
        "total_images": total_images,
        "local_images": local_count,
        "r2_images": r2_count,
        "pending_uploads": pending_count,
        "failed_uploads": failed_count,
        "total_size_bytes": total_size_bytes,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 2),
        "disk_usage_bytes": disk_usage,
        "disk_usage_mb": round(disk_usage / (1024 * 1024), 2),
    }


def calculate_disk_usage() -> int:
    """Calculate actual disk usage of images directory."""
    total = 0
    if IMAGES_DIR.exists():
        for file in IMAGES_DIR.rglob("*"):
            if file.is_file():
                total += file.stat().st_size
    return total


def format_bytes(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
