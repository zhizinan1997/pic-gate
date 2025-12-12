"""
PicGate URL Builder Service
Handles public URL generation with proper base URL resolution.

CRITICAL: This module ensures all image URLs returned to OpenWebUI
use the correct public base URL (either from settings or inferred from request).
"""

from typing import Optional
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Settings


async def get_settings(db: AsyncSession) -> Optional[Settings]:
    """Get the singleton settings row."""
    result = await db.execute(select(Settings).where(Settings.id == 1))
    return result.scalar_one_or_none()


def parse_forwarded_header(forwarded: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse RFC 7239 Forwarded header.
    Returns (proto, host) tuple.
    Example: Forwarded: for=192.0.2.60;proto=https;host=example.com
    """
    proto = None
    host = None
    
    for part in forwarded.split(";"):
        part = part.strip()
        if part.lower().startswith("proto="):
            proto = part[6:].strip()
        elif part.lower().startswith("host="):
            host = part[5:].strip()
    
    return proto, host


def infer_base_url_from_request(request: Request) -> str:
    """
    Infer the public base URL from request headers.
    
    Priority:
    1. X-Forwarded-Proto + X-Forwarded-Host
    2. Forwarded header (RFC 7239)
    3. request.url.scheme + request.headers["host"]
    """
    # Try X-Forwarded-* headers first (most common for reverse proxies)
    x_proto = request.headers.get("x-forwarded-proto")
    x_host = request.headers.get("x-forwarded-host")
    
    if x_proto and x_host:
        return f"{x_proto}://{x_host}"
    
    # Try standard Forwarded header
    forwarded = request.headers.get("forwarded")
    if forwarded:
        proto, host = parse_forwarded_header(forwarded)
        if proto and host:
            return f"{proto}://{host}"
    
    # Fall back to request URL
    host = request.headers.get("host", request.url.netloc)
    scheme = request.url.scheme
    
    return f"{scheme}://{host}"


async def get_public_base_url(request: Request, db: AsyncSession) -> str:
    """
    Get the public base URL for generating image links.
    
    Priority:
    1. Settings.public_base_url (if configured and non-empty)
    2. Inferred from request headers (for reverse proxy scenarios)
    
    Returns URL without trailing slash.
    """
    settings = await get_settings(db)
    
    if settings and settings.public_base_url:
        # Use configured public_base_url
        base = settings.public_base_url.strip()
        # Remove trailing slash for consistent joining
        return base.rstrip("/")
    
    # Infer from request
    base = infer_base_url_from_request(request)
    return base.rstrip("/")


async def build_image_url(request: Request, db: AsyncSession, image_id: str) -> str:
    """
    Build the full public URL for an image.
    
    Ensures:
    - Proper base URL (from settings or inferred)
    - No double slashes
    - Consistent format: {base}/images/{image_id}
    """
    base = await get_public_base_url(request, db)
    return f"{base}/images/{image_id}"


def build_image_url_sync(base_url: str, image_id: str) -> str:
    """
    Synchronous version for building image URL when base is already known.
    Used in response formatting.
    """
    base = base_url.rstrip("/")
    return f"{base}/images/{image_id}"
