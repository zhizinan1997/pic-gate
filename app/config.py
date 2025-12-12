"""
PicGate Configuration Module
Handles environment variables and application settings.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file if exists
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
IMAGES_DIR = Path(os.getenv("IMAGES_DIR", DATA_DIR / "images"))
DB_DIR = Path(os.getenv("DB_DIR", DATA_DIR / "db"))

# Ensure directories exist
IMAGES_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    f"sqlite+aiosqlite:///{DB_DIR}/picgate.db"
)

# Server
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "5643"))

# Session secret (generate random if not set)
import secrets
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
