"""
PicGate Image Serving Router
Serves images from local cache or R2 fallback.

Phase D: Now supports R2 download when local file is missing.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

from app.db import get_db
from app.models import Image
from app.config import IMAGES_DIR

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Images"])


@router.get("/images/{image_id}")
async def get_image(
    image_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Serve an image by its ID.
    
    Priority:
    1. Serve from local cache if available
    2. Download from R2 if local cache missing
    3. Return 404 if not found anywhere
    
    Updates last_accessed_at on each access.
    """
    # Look up image in database
    result = await db.execute(
        select(Image).where(Image.image_id == image_id)
    )
    image = result.scalar_one_or_none()
    
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    
    # Update last accessed time
    image.last_accessed_at = datetime.utcnow()
    await db.commit()
    
    # Check local cache
    if image.has_local_copy and image.local_path:
        local_file = IMAGES_DIR / image.local_path
        if local_file.exists():
            return FileResponse(
                path=str(local_file),
                media_type=image.content_type or "image/png",
                filename=f"{image_id}.png"
            )
        else:
            # File missing but marked as local - update database
            image.has_local_copy = False
            await db.commit()
    
    # R2 fallback - download from R2 if available
    if image.has_r2_copy:
        logger.info(f"Image {image_id} missing locally, attempting R2 download")
        
        try:
            from app.services.cleanup import download_from_r2
            
            image_bytes = await download_from_r2(db, image_id)
            
            if image_bytes:
                # Successfully downloaded and saved locally
                # Now serve from local file
                local_file = IMAGES_DIR / f"{image_id}.png"
                if local_file.exists():
                    return FileResponse(
                        path=str(local_file),
                        media_type=image.content_type or "image/png",
                        filename=f"{image_id}.png"
                    )
                else:
                    # Return bytes directly if file save failed
                    return Response(
                        content=image_bytes,
                        media_type=image.content_type or "image/png",
                        headers={
                            "Content-Disposition": f'inline; filename="{image_id}.png"'
                        }
                    )
            else:
                logger.error(f"Failed to download {image_id} from R2")
                raise HTTPException(
                    status_code=503,
                    detail="Failed to retrieve image from cloud storage"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"R2 download error for {image_id}: {e}")
            raise HTTPException(
                status_code=503,
                detail="Error retrieving image from cloud storage"
            )
    
    raise HTTPException(status_code=404, detail="Image file not available")


@router.get("/images/{image_id}/thumbnail")
async def get_thumbnail(
    image_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Serve a thumbnail for an image.
    
    This endpoint:
    1. Returns the thumbnail if available
    2. Generates thumbnail on-the-fly if local image exists
    3. Returns 404 if no thumbnail can be provided
    
    IMPORTANT: This endpoint does NOT trigger R2 downloads.
    Thumbnails are always local-only to save bandwidth.
    """
    from app.services.image_store import ImageStore
    from app.config import THUMBNAILS_DIR
    
    image_store = ImageStore(db)
    
    # Try to get or generate thumbnail
    thumb_path = await image_store.ensure_thumbnail(image_id)
    
    if thumb_path and thumb_path.exists():
        return FileResponse(
            path=str(thumb_path),
            media_type="image/jpeg",
            filename=f"{image_id}_thumb.jpg",
            headers={
                "Cache-Control": "public, max-age=86400"  # Cache for 1 day
            }
        )
    
    # No thumbnail available - return a placeholder SVG
    placeholder_svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" viewBox="0 0 200 200">
        <rect width="200" height="200" fill="#f0f0f0"/>
        <text x="100" y="100" text-anchor="middle" dominant-baseline="middle" font-size="48" fill="#ccc">🖼️</text>
        <text x="100" y="140" text-anchor="middle" font-size="12" fill="#999">R2 Only</text>
    </svg>'''
    
    return Response(
        content=placeholder_svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=3600"  # Cache placeholder for 1 hour
        }
    )
