"""
PicGate SQLAlchemy ORM Models
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, func
from app.db import Base


class Admin(Base):
    """Admin user for management interface."""
    __tablename__ = "admins"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Settings(Base):
    """
    Application settings (single row table).
    All configuration is stored here for admin UI management.
    """
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, default=1)
    
    # Upstream AI API configuration
    upstream_api_base = Column(String(255), default="")
    upstream_api_key = Column(String(255), default="")
    upstream_model_name = Column(String(100), default="")
    
    # Gateway configuration (exposed to clients)
    gateway_api_key = Column(String(255), default="")
    gateway_model_name = Column(String(100), default="picgate")
    
    # Public URL configuration (CRITICAL)
    # When set, all image URLs returned to OpenWebUI use this as base
    # Example: https://img.example.com
    public_base_url = Column(String(255), default="")
    
    # Cloudflare R2 configuration
    r2_account_id = Column(String(100), default="")
    r2_access_key_id = Column(String(100), default="")
    r2_secret_access_key = Column(String(255), default="")
    r2_bucket_name = Column(String(100), default="")
    
    # Cache configuration
    local_cache_ttl_hours = Column(Integer, default=72)  # 3 days default
    metadata_retention_days = Column(Integer, default=365)
    max_local_cache_mb = Column(Integer, default=0)  # 0 = unlimited
    
    # Security settings
    allow_external_image_fetch = Column(Boolean, default=False)
    delete_r2_on_metadata_expire = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Image(Base):
    """
    Image metadata and storage tracking.
    Does NOT store actual image data (base64) - only references.
    """
    __tablename__ = "images"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(String(36), unique=True, nullable=False, index=True)  # UUID
    
    # Storage paths
    local_path = Column(String(500), default="")  # Relative path in data/images
    r2_key = Column(String(255), default="")  # Key in R2 bucket
    
    # File info
    size_bytes = Column(Integer, default=0)
    content_type = Column(String(50), default="image/png")
    
    # Storage status
    has_local_copy = Column(Boolean, default=True)
    has_r2_copy = Column(Boolean, default=False)
    
    # R2 upload tracking
    upload_status = Column(String(20), default="pending")  # pending/uploading/uploaded/failed
    upload_error = Column(Text, default="")
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_accessed_at = Column(DateTime, default=datetime.utcnow)
