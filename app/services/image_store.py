"""
PicGate Image Store Service
Handles local image storage, metadata tracking, and R2 integration.
"""

import uuid
import base64
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Image
from app.config import IMAGES_DIR

logger = logging.getLogger(__name__)


class ImageStore:
    """Service for storing and retrieving images."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.images_dir = IMAGES_DIR
        
    async def save_from_base64(
        self,
        base64_data: str,
        content_type: str = "image/png"
    ) -> Image:
        """
        Save a base64-encoded image to local storage.
        
        Args:
            base64_data: Base64-encoded image data (without data: prefix)
            content_type: MIME type of the image
            
        Returns:
            Image model instance with metadata
        """
        # Generate unique ID
        image_id = str(uuid.uuid4())
        
        # Determine file extension
        ext = self._get_extension(content_type)
        filename = f"{image_id}{ext}"
        local_path = filename  # Relative path
        
        # Decode base64
        try:
            # Handle data URL prefix if present
            if base64_data.startswith("data:"):
                # Extract the base64 part after the comma
                base64_data = base64_data.split(",", 1)[1]
            
            image_bytes = base64.b64decode(base64_data)
        except Exception as e:
            logger.error(f"Failed to decode base64: {e}")
            raise ValueError(f"Invalid base64 data: {e}")
        
        # Write to disk
        file_path = self.images_dir / filename
        file_path.write_bytes(image_bytes)
        
        size_bytes = len(image_bytes)
        logger.info(f"Saved image {image_id} ({size_bytes} bytes) to {file_path}")
        
        # Create database record
        image = Image(
            image_id=image_id,
            local_path=local_path,
            r2_key=f"openwebui/{image_id}{ext}",
            size_bytes=size_bytes,
            content_type=content_type,
            has_local_copy=True,
            has_r2_copy=False,
            upload_status="pending",
            created_at=datetime.utcnow(),
            last_accessed_at=datetime.utcnow()
        )
        
        self.db.add(image)
        await self.db.commit()
        await self.db.refresh(image)
        
        # Trigger background upload to R2
        import asyncio
        asyncio.create_task(self._auto_upload_to_r2(image_id, file_path, image.r2_key))
        
        # Check cache size limit and cleanup if needed
        asyncio.create_task(self._check_cache_size_limit())
        
        return image
    
    async def _check_cache_size_limit(self):
        """Check if cache size exceeds limit and cleanup oldest images if needed."""
        try:
            from app.services.settings_service import get_settings
            from app.db import async_session_maker
            from sqlalchemy import select, func
            
            async with async_session_maker() as db:
                settings = await get_settings(db)
                max_mb = settings.max_local_cache_mb or 0
                
                if max_mb <= 0:
                    return  # No limit set
                
                # Calculate current disk usage
                current_bytes = 0
                if self.images_dir.exists():
                    for f in self.images_dir.iterdir():
                        if f.is_file():
                            current_bytes += f.stat().st_size
                
                current_mb = current_bytes / (1024 * 1024)
                
                if current_mb <= max_mb:
                    return  # Under limit
                
                # Need to cleanup - delete oldest images until under limit
                target_mb = max_mb * 0.9  # Target 90% of max
                deleted_count = 0
                
                # Get oldest images with local copies
                result = await db.execute(
                    select(Image)
                    .where(Image.has_local_copy == True)
                    .order_by(Image.created_at.asc())
                )
                images = result.scalars().all()
                
                for image in images:
                    if current_mb <= target_mb:
                        break
                    
                    if image.local_path:
                        local_file = self.images_dir / image.local_path
                        if local_file.exists():
                            file_size_mb = local_file.stat().st_size / (1024 * 1024)
                            local_file.unlink()
                            current_mb -= file_size_mb
                            deleted_count += 1
                        
                        image.has_local_copy = False
                
                if deleted_count > 0:
                    await db.commit()
                    logger.info(f"Auto-cleanup: Deleted {deleted_count} oldest local images to stay under {max_mb}MB limit")
                    
                    # Add to admin logs
                    from app.routers.admin_api import add_log
                    add_log("INFO", f"自动清理: 删除 {deleted_count} 张最早的图片，保持在 {max_mb}MB 限制内")
                    
        except Exception as e:
            logger.error(f"Cache size limit check failed: {e}")
    
    async def _auto_upload_to_r2(self, image_id: str, local_path: Path, r2_key: str):
        """Background task to upload image to R2."""
        try:
            from app.services.settings_service import get_settings
            from app.services.r2_client import create_r2_client
            from app.db import async_session_maker
            
            async with async_session_maker() as db:
                settings = await get_settings(db)
                
                # Check if R2 is configured
                if not all([settings.r2_account_id, settings.r2_access_key_id,
                           settings.r2_secret_access_key, settings.r2_bucket_name]):
                    return  # R2 not configured, skip
                
                r2_client = create_r2_client(settings)
                if not r2_client:
                    return
                
                # Read and upload
                if local_path.exists():
                    image_data = local_path.read_bytes()
                    success = await r2_client.upload(r2_key, image_data)
                    
                    if success:
                        # Update database
                        from sqlalchemy import select
                        result = await db.execute(select(Image).where(Image.image_id == image_id))
                        image = result.scalar_one_or_none()
                        if image:
                            image.has_r2_copy = True
                            image.upload_status = "uploaded"
                            await db.commit()
                            logger.info(f"Auto-uploaded {image_id} to R2")
                    else:
                        logger.warning(f"Failed to auto-upload {image_id} to R2")
        except Exception as e:
            logger.error(f"Auto-upload error for {image_id}: {e}")
    
    async def get_by_id(self, image_id: str) -> Optional[Image]:
        """Get image record by ID."""
        result = await self.db.execute(
            select(Image).where(Image.image_id == image_id)
        )
        return result.scalar_one_or_none()
    
    async def get_local_path(self, image_id: str) -> Optional[Path]:
        """
        Get the local file path for an image.
        Returns None if image doesn't exist locally.
        """
        image = await self.get_by_id(image_id)
        if not image:
            return None
            
        if image.has_local_copy and image.local_path:
            path = self.images_dir / image.local_path
            if path.exists():
                return path
            else:
                # File missing, update database
                image.has_local_copy = False
                await self.db.commit()
                
        return None
    
    async def get_base64(self, image_id: str) -> Optional[str]:
        """
        Get base64-encoded image data.
        Loads from local storage first, with R2 fallback if local not available.
        
        Args:
            image_id: UUID of the image (36 characters with 4 hyphens)
        
        Returns:
            Base64-encoded string or None if not found anywhere
        """
        # Input validation
        if not image_id or not isinstance(image_id, str):
            logger.warning(f"Invalid image_id provided: {image_id}")
            return None
        
        image_id = image_id.strip()
        
        # Basic UUID format validation
        if len(image_id) != 36 or image_id.count("-") != 4:
            logger.warning(f"Image ID does not look like a UUID: {image_id}")
            return None
        
        # Try local path first
        try:
            local_path = await self.get_local_path(image_id)
            
            if local_path:
                try:
                    image_bytes = local_path.read_bytes()
                    return base64.b64encode(image_bytes).decode('utf-8')
                except Exception as e:
                    logger.error(f"Failed to read local file {local_path}: {e}")
                    # Fall through to R2 fallback
        except Exception as e:
            logger.error(f"Error getting local path for {image_id}: {e}")
        
        # R2 fallback - download from R2 if available
        try:
            image = await self.get_by_id(image_id)
        except Exception as e:
            logger.error(f"Database error getting image {image_id}: {e}")
            return None
        
        if image and image.has_r2_copy:
            try:
                from app.services.settings_service import get_settings
                from app.services.r2_client import create_r2_client
                
                settings = await get_settings(self.db)
                r2_client = create_r2_client(settings)
                
                if r2_client:
                    logger.info(f"Attempting R2 fallback for image {image_id}")
                    image_bytes, error = await r2_client.download_image(image_id)
                    
                    if image_bytes:
                        logger.info(f"Downloaded image {image_id} from R2 ({len(image_bytes)} bytes)")
                        
                        # Cache locally for future use
                        try:
                            # Ensure images directory exists
                            self.images_dir.mkdir(parents=True, exist_ok=True)
                            
                            ext = self._get_extension(image.content_type or "image/png")
                            filename = f"{image_id}{ext}"
                            local_file = self.images_dir / filename
                            local_file.write_bytes(image_bytes)
                            
                            image.has_local_copy = True
                            image.local_path = filename
                            await self.db.commit()
                            logger.info(f"Cached R2 image {image_id} locally")
                        except Exception as e:
                            logger.warning(f"Failed to cache R2 image locally: {e}")
                        
                        return base64.b64encode(image_bytes).decode('utf-8')
                    else:
                        logger.warning(f"Failed to download {image_id} from R2: {error}")
                else:
                    logger.warning(f"R2 client not available for fallback of {image_id}")
            except Exception as e:
                logger.error(f"R2 fallback failed for {image_id}: {e}")
        
        return None
    
    async def update_last_accessed(self, image_id: str):
        """Update the last_accessed_at timestamp."""
        image = await self.get_by_id(image_id)
        if image:
            image.last_accessed_at = datetime.utcnow()
            await self.db.commit()
    
    def _get_extension(self, content_type: str) -> str:
        """Get file extension from content type."""
        mapping = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }
        return mapping.get(content_type, ".png")


async def extract_image_id_from_url(url: str, public_base_url: str = "") -> Optional[str]:
    """
    Extract image ID from a PicGate image URL.
    
    Handles various URL formats:
    - /images/{image_id}
    - http://host/images/{image_id}
    - https://domain.com/images/{image_id}
    - URLs with query strings: /images/{image_id}?foo=bar
    - URLs with fragments: /images/{image_id}#section
    - URL-encoded paths
    
    Args:
        url: The URL to extract image ID from
        public_base_url: Optional base URL to match against
    
    Returns:
        Image ID if URL matches PicGate format, None otherwise
    """
    # Input validation
    if not url or not isinstance(url, str):
        return None
    
    # Normalize URL
    url = url.strip()
    
    if not url:
        return None
    
    # Handle URL encoding
    try:
        from urllib.parse import unquote
        url = unquote(url)
    except Exception:
        pass
    
    # Check for /images/ pattern
    if "/images/" in url:
        # Extract everything after /images/
        parts = url.split("/images/")
        if len(parts) >= 2:
            # Get the last part (in case of multiple /images/ in URL)
            image_id_part = parts[-1]
            
            # Remove query string and fragment
            image_id = image_id_part.split("?")[0].split("#")[0].strip()
            
            # Remove any trailing slashes or file extensions that might be appended
            if image_id.endswith("/"):
                image_id = image_id[:-1]
            
            # Basic UUID validation (36 chars with hyphens in correct positions)
            if len(image_id) == 36 and image_id.count("-") == 4:
                # Additional validation: check hyphen positions (8-4-4-4-12 format)
                parts = image_id.split("-")
                if len(parts) == 5 and all(len(p) == l for p, l in zip(parts, [8, 4, 4, 4, 12])):
                    # Validate hex characters
                    try:
                        int(image_id.replace("-", ""), 16)
                        return image_id
                    except ValueError:
                        pass
    
    return None


def is_base64_image(value: str) -> bool:
    """Check if a string is base64-encoded image data."""
    if not value:
        return False
    
    # Check for data URL prefix
    if value.startswith("data:image/"):
        return True
    
    # Check if it looks like raw base64 (no URL-like patterns)
    if value.startswith(("http://", "https://", "/")):
        return False
    
    # Try to detect base64 by character set and length
    # Base64 uses A-Za-z0-9+/= characters
    if len(value) > 100:  # Images are typically large
        try:
            # Try to decode a small portion
            test_portion = value[:100].replace("\n", "").replace("\r", "")
            base64.b64decode(test_portion + "==")  # Add padding for test
            return True
        except Exception:
            pass
    
    return False
