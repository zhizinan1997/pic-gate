"""
PicGate - AI Image Gateway for OpenWebUI

Main application entry point.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import HOST, PORT, IMAGES_DIR
from app.db import init_db
from app.routers import gateway_openai, images, admin_pages, admin_api

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting PicGate...")
    await init_db()
    logger.info(f"Database initialized")
    logger.info(f"Images directory: {IMAGES_DIR}")
    yield
    # Shutdown
    logger.info("Shutting down PicGate...")


# Create FastAPI app
app = FastAPI(
    title="PicGate",
    description="AI Image Gateway for OpenWebUI with local caching and R2 archival",
    version="1.0.0",
    lifespan=lifespan
)

# Static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Include routers
app.include_router(gateway_openai.router)
app.include_router(images.router)
app.include_router(admin_pages.router)
app.include_router(admin_api.router)


@app.get("/")
async def root():
    """Root endpoint - redirect to admin."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin")


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "picgate"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=HOST,
        port=PORT,
        reload=True
    )
