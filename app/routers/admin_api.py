"""
PicGate Admin API Router
JSON API endpoints for admin operations.
"""

import secrets
import logging
from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db import get_db
from app.services.auth import has_any_admin, create_admin, authenticate_admin
from app.services.settings_service import get_settings, update_settings, settings_to_dict
from app.services.stats import get_stats
from app.config import SESSION_SECRET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/api", tags=["Admin API"])


# --- Request Models ---

class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class SettingsUpdateRequest(BaseModel):
    upstream_api_base: str = None
    upstream_api_key: str = None
    upstream_model_name: str = None
    gateway_api_key: str = None
    gateway_model_name: str = None
    public_base_url: str = None
    r2_account_id: str = None
    r2_access_key_id: str = None
    r2_secret_access_key: str = None
    r2_bucket_name: str = None
    local_cache_ttl_hours: int = None
    metadata_retention_days: int = None
    max_local_cache_mb: int = None
    allow_external_image_fetch: bool = None
    delete_r2_on_metadata_expire: bool = None


# --- Session Management ---

# Simple in-memory session store (for MVP - consider Redis for production)
sessions: Dict[str, str] = {}


def generate_session_token() -> str:
    """Generate a secure session token."""
    return secrets.token_urlsafe(32)


def verify_session(request: Request) -> str:
    """Verify session from cookie and return username."""
    token = request.cookies.get("session")
    if not token or token not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return sessions[token]


# --- Endpoints ---

@router.get("/status")
async def get_status(db: AsyncSession = Depends(get_db)):
    """Check if initial setup is needed."""
    has_admin = await has_any_admin(db)
    return {"needs_setup": not has_admin}


@router.post("/setup")
async def setup_admin(
    data: SetupRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create the first admin user."""
    # Check if admin already exists
    if await has_any_admin(db):
        raise HTTPException(status_code=400, detail="Admin already exists")
    
    if len(data.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    await create_admin(db, data.username, data.password)
    
    # Also initialize default settings
    await get_settings(db)
    
    logger.info(f"Admin user '{data.username}' created successfully")
    return {"success": True, "message": "Admin created successfully"}


@router.post("/login")
async def login(
    data: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate admin and create session."""
    admin = await authenticate_admin(db, data.username, data.password)
    
    if not admin:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    # Create session
    token = generate_session_token()
    sessions[token] = admin.username
    
    response = JSONResponse({"success": True, "username": admin.username})
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7  # 7 days
    )
    
    logger.info(f"Admin '{admin.username}' logged in")
    return response


@router.post("/logout")
async def logout(request: Request):
    """End admin session."""
    token = request.cookies.get("session")
    if token and token in sessions:
        del sessions[token]
    
    response = JSONResponse({"success": True})
    response.delete_cookie("session")
    return response


@router.get("/settings")
async def get_current_settings(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get current settings (secrets masked)."""
    verify_session(request)
    settings = await get_settings(db)
    return settings_to_dict(settings, hide_secrets=True)


@router.get("/settings/full")
async def get_full_settings(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get current settings including secrets (for form population)."""
    verify_session(request)
    settings = await get_settings(db)
    return settings_to_dict(settings, hide_secrets=False)


@router.post("/settings")
async def save_settings(
    request: Request,
    data: SettingsUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update settings."""
    verify_session(request)
    
    # Build updates dict, excluding None values
    updates = {k: v for k, v in data.model_dump().items() if v is not None}
    
    await update_settings(db, updates)
    
    logger.info(f"Settings updated: {list(updates.keys())}")
    return {"success": True, "message": "Settings saved successfully"}


@router.post("/settings/generate-key")
async def generate_gateway_key(request: Request):
    """Generate a new random gateway API key."""
    verify_session(request)
    new_key = f"pg-{secrets.token_urlsafe(32)}"
    return {"key": new_key}


@router.post("/settings/test-upstream")
async def test_upstream_api(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Test upstream API connection."""
    verify_session(request)
    
    settings = await get_settings(db)
    
    if not settings.upstream_api_base or not settings.upstream_api_key:
        return {"success": False, "message": "上游 API 未配置"}
    
    import httpx
    
    try:
        # Test by calling /models endpoint
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{settings.upstream_api_base.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {settings.upstream_api_key}"}
            )
            
            if response.status_code == 200:
                data = response.json()
                model_count = len(data.get("data", []))
                return {
                    "success": True,
                    "message": f"连接成功！发现 {model_count} 个可用模型"
                }
            elif response.status_code == 401:
                return {"success": False, "message": "API 密钥无效"}
            else:
                return {"success": False, "message": f"连接失败: HTTP {response.status_code}"}
                
    except httpx.ConnectError:
        return {"success": False, "message": "无法连接到上游 API 地址"}
    except httpx.TimeoutException:
        return {"success": False, "message": "连接超时"}
    except Exception as e:
        return {"success": False, "message": f"测试失败: {str(e)}"}


@router.post("/settings/test-r2")
async def test_r2_connection(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Test R2 connection."""
    verify_session(request)
    
    settings = await get_settings(db)
    
    if not all([settings.r2_account_id, settings.r2_access_key_id, 
                settings.r2_secret_access_key, settings.r2_bucket_name]):
        return {"success": False, "message": "R2 配置不完整"}
    
    from app.services.r2_client import create_r2_client
    
    try:
        r2_client = create_r2_client(settings)
        if not r2_client:
            return {"success": False, "message": "R2 客户端创建失败"}
        
        # Test by listing bucket (head request)
        import boto3
        from botocore.exceptions import ClientError
        
        # Just try to list a few objects to verify connection
        try:
            await r2_client._run_sync(
                r2_client._client.list_objects_v2,
                Bucket=settings.r2_bucket_name,
                MaxKeys=1
            )
            return {
                "success": True,
                "message": f"R2 连接成功！存储桶: {settings.r2_bucket_name}"
            }
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', '')
            if error_code == 'NoSuchBucket':
                return {"success": False, "message": "存储桶不存在"}
            elif error_code in ['AccessDenied', 'InvalidAccessKeyId']:
                return {"success": False, "message": "访问密钥无效"}
            else:
                return {"success": False, "message": f"R2 错误: {error_code}"}
                
    except Exception as e:
        return {"success": False, "message": f"测试失败: {str(e)}"}


@router.get("/stats")
async def get_statistics(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Get cache and storage statistics."""
    verify_session(request)
    return await get_stats(db)


@router.post("/cleanup")
async def trigger_cleanup(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger cache cleanup.
    
    Deletes local files that have exceeded the configured TTL.
    """
    verify_session(request)
    
    from app.services.cleanup import cleanup_expired_local, cleanup_expired_metadata
    
    try:
        # Clean expired local files
        local_result = await cleanup_expired_local(db)
        
        # Clean expired metadata (optional, less frequent)
        metadata_result = await cleanup_expired_metadata(db)
        
        message = f"Cleanup complete: {local_result['deleted_count']} local files deleted "
        message += f"({local_result['deleted_mb']} MB freed)"
        
        if metadata_result['deleted_count'] > 0:
            message += f", {metadata_result['deleted_count']} metadata entries removed"
        
        logger.info(message)
        
        return {
            "success": True,
            "message": message,
            "local_cleanup": local_result,
            "metadata_cleanup": metadata_result
        }
        
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return {
            "success": False,
            "message": f"Cleanup failed: {str(e)}"
        }


@router.post("/clear-all-local")
async def clear_all_local_cache(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Clear ALL local cache files.
    
    Deletes all local image files but keeps metadata for R2 retrieval.
    """
    verify_session(request)
    
    from sqlalchemy import select, update
    from app.models import Image
    from app.config import IMAGES_DIR
    import os
    
    try:
        deleted_count = 0
        deleted_bytes = 0
        
        # Get all images with local copies
        result = await db.execute(
            select(Image).where(Image.has_local_copy == True)
        )
        images = result.scalars().all()
        
        for image in images:
            if image.local_path:
                local_file = IMAGES_DIR / image.local_path
                if local_file.exists():
                    file_size = local_file.stat().st_size
                    local_file.unlink()
                    deleted_count += 1
                    deleted_bytes += file_size
            
            # Update database
            image.has_local_copy = False
        
        await db.commit()
        
        deleted_mb = round(deleted_bytes / (1024 * 1024), 2)
        message = f"已清除 {deleted_count} 个本地缓存文件，释放 {deleted_mb} MB 空间"
        
        add_log("INFO", message)
        logger.info(message)
        
        return {
            "success": True,
            "message": message,
            "deleted_count": deleted_count,
            "deleted_mb": deleted_mb
        }
        
    except Exception as e:
        logger.error(f"Clear all local cache failed: {e}")
        return {
            "success": False,
            "message": f"清除失败: {str(e)}"
        }


@router.post("/retry-uploads")
async def retry_failed_uploads_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Retry failed R2 uploads.
    
    Resets failed uploads to pending and attempts to upload again.
    """
    verify_session(request)
    
    from app.services.cleanup import retry_failed_uploads
    
    try:
        result = await retry_failed_uploads(db)
        
        if result.get("upload_results"):
            upload_results = result["upload_results"]
            message = f"Retried {result['reset_count']} uploads: "
            message += f"{upload_results.get('uploaded_count', 0)} succeeded, "
            message += f"{upload_results.get('failed_count', 0)} failed"
        else:
            message = result.get("message", "No uploads to retry")
        
        logger.info(message)
        
        return {
            "success": True,
            "message": message,
            "details": result
        }
        
    except Exception as e:
        logger.error(f"Retry uploads failed: {e}")
        return {
            "success": False,
            "message": f"Retry failed: {str(e)}"
        }


@router.post("/upload-pending")
async def upload_pending_images(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Manually trigger upload of pending images to R2.
    """
    verify_session(request)
    
    from app.services.cleanup import process_pending_uploads
    
    try:
        result = await process_pending_uploads(db)
        
        if not result.get("success"):
            return {
                "success": False,
                "message": result.get("message", "Upload failed")
            }
        
        message = f"Processed {result['total_processed']} images: "
        message += f"{result['uploaded_count']} uploaded, {result['failed_count']} failed"
        
        logger.info(message)
        
        return {
            "success": True,
            "message": message,
            "details": result
        }
        
    except Exception as e:
        logger.error(f"Upload pending failed: {e}")
        return {
            "success": False,
            "message": f"Upload failed: {str(e)}"
        }


# --- Logs API ---

# Store logs in memory for display
_logs = []
_max_logs = 500


def add_log(level: str, message: str):
    """Add a log entry to the in-memory log store."""
    from datetime import datetime, timezone, timedelta
    # Use Beijing time (UTC+8)
    beijing_tz = timezone(timedelta(hours=8))
    # Ensure we get UTC time first, then convert to Beijing
    utc_now = datetime.now(timezone.utc)
    beijing_time = utc_now.astimezone(beijing_tz)
    
    _logs.append({
        "time": beijing_time.strftime("%Y-%m-%d %H:%M:%S"),
        "level": level,
        "message": message
    })
    # Keep only the last N logs
    if len(_logs) > _max_logs:
        _logs.pop(0)


@router.get("/logs")
async def get_logs(request: Request):
    """Get system logs."""
    verify_session(request)
    return {"logs": list(_logs)}


@router.delete("/logs")
async def clear_logs(request: Request):
    """Clear all logs."""
    verify_session(request)
    _logs.clear()
    return {"success": True, "message": "日志已清除"}


# --- Images API ---

@router.get("/images")
async def list_images(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    size: int = 20,
    sort: str = "created_desc"
):
    """List all images with pagination."""
    verify_session(request)
    
    from sqlalchemy import select, func, desc, asc
    from app.models import Image
    
    # Build query
    query = select(Image)
    
    # Apply sorting
    if sort == "created_desc":
        query = query.order_by(desc(Image.created_at))
    elif sort == "created_asc":
        query = query.order_by(asc(Image.created_at))
    elif sort == "accessed_desc":
        query = query.order_by(desc(Image.last_accessed_at))
    elif sort == "size_desc":
        query = query.order_by(desc(Image.size_bytes))
    else:
        query = query.order_by(desc(Image.created_at))
    
    # Get total count
    count_result = await db.execute(select(func.count(Image.id)))
    total = count_result.scalar() or 0
    
    # Apply pagination
    offset = (page - 1) * size
    query = query.offset(offset).limit(size)
    
    result = await db.execute(query)
    images = result.scalars().all()
    
    return {
        "images": [
            {
                "image_id": img.image_id,
                "content_type": img.content_type,
                "size_bytes": img.size_bytes,
                "has_local_copy": img.has_local_copy,
                "has_r2_copy": img.has_r2_copy,
                "created_at": img.created_at.isoformat() if img.created_at else None,
                "last_accessed_at": img.last_accessed_at.isoformat() if img.last_accessed_at else None
            }
            for img in images
        ],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size
    }


@router.delete("/images/{image_id}")
async def delete_image(
    image_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Delete an image."""
    verify_session(request)
    
    from sqlalchemy import select
    from app.models import Image
    from app.config import IMAGES_DIR
    
    result = await db.execute(select(Image).where(Image.image_id == image_id))
    image = result.scalar_one_or_none()
    
    if not image:
        raise HTTPException(status_code=404, detail="图片不存在")
    
    # Delete local file
    if image.has_local_copy and image.local_path:
        local_file = IMAGES_DIR / image.local_path
        if local_file.exists():
            local_file.unlink()
    
    # Delete from database
    await db.delete(image)
    await db.commit()
    
    add_log("INFO", f"图片已删除: {image_id}")
    
    return {"success": True, "message": "图片已删除"}


class BatchDeleteRequest(BaseModel):
    image_ids: list
    delete_type: str  # 'local', 'r2', 'all'


@router.post("/images/batch-delete")
async def batch_delete_images(
    request: Request,
    data: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db)
):
    """Batch delete images from local/R2/all."""
    verify_session(request)
    
    from sqlalchemy import select
    from app.models import Image
    from app.config import IMAGES_DIR
    from app.services.settings_service import get_settings
    from app.services.r2_client import create_r2_client
    
    settings = await get_settings(db)
    r2_client = None
    if data.delete_type in ['r2', 'all'] and all([
        settings.r2_account_id, settings.r2_access_key_id,
        settings.r2_secret_access_key, settings.r2_bucket_name
    ]):
        r2_client = create_r2_client(settings)
    
    deleted_count = 0
    errors = []
    
    for image_id in data.image_ids:
        try:
            result = await db.execute(select(Image).where(Image.image_id == image_id))
            image = result.scalar_one_or_none()
            
            if not image:
                continue
            
            # Delete local
            if data.delete_type in ['local', 'all']:
                if image.has_local_copy and image.local_path:
                    local_file = IMAGES_DIR / image.local_path
                    if local_file.exists():
                        local_file.unlink()
                    image.has_local_copy = False
            
            # Delete from R2
            if data.delete_type in ['r2', 'all'] and r2_client and image.has_r2_copy:
                try:
                    await r2_client.delete(image.r2_key)
                    image.has_r2_copy = False
                except Exception as e:
                    errors.append(f"{image_id[:8]}: R2删除失败")
            
            # Delete metadata if 'all'
            if data.delete_type == 'all':
                await db.delete(image)
            
            deleted_count += 1
            
        except Exception as e:
            errors.append(f"{image_id[:8]}: {str(e)}")
    
    await db.commit()
    
    type_text = {'local': '本地', 'r2': 'R2', 'all': '全部'}[data.delete_type]
    message = f"已删除 {deleted_count} 张图片的{type_text}数据"
    if errors:
        message += f"，{len(errors)} 个错误"
    
    add_log("INFO", message)
    
    return {
        "success": True,
        "message": message,
        "deleted_count": deleted_count,
        "errors": errors
    }


@router.post("/generate-thumbnails")
async def generate_thumbnails(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Generate thumbnails for all images missing them.
    
    Only processes images with local copies.
    """
    verify_session(request)
    
    from sqlalchemy import select, or_
    from app.models import Image
    from app.services.image_store import ImageStore
    from app.config import IMAGES_DIR
    
    image_store = ImageStore(db)
    
    # Get images with local copies but no thumbnails
    result = await db.execute(
        select(Image).where(
            Image.has_local_copy == True,
            or_(Image.thumbnail_path == "", Image.thumbnail_path == None)
        )
    )
    images = result.scalars().all()
    
    generated = 0
    skipped = 0
    errors = 0
    
    for img in images:
        try:
            if img.local_path:
                local_file = IMAGES_DIR / img.local_path
                if local_file.exists():
                    image_bytes = local_file.read_bytes()
                    thumb_filename = await image_store._generate_thumbnail(img.image_id, image_bytes)
                    if thumb_filename:
                        img.thumbnail_path = thumb_filename
                        generated += 1
                    else:
                        errors += 1
                else:
                    skipped += 1
            else:
                skipped += 1
        except Exception as e:
            logger.warning(f"Failed to generate thumbnail for {img.image_id}: {e}")
            errors += 1
    
    await db.commit()
    
    message = f"缩略图生成完成: {generated} 成功, {skipped} 跳过, {errors} 失败"
    add_log("INFO", message)
    
    return {
        "success": True,
        "message": message,
        "generated": generated,
        "skipped": skipped,
        "errors": errors,
        "total": len(images)
    }
