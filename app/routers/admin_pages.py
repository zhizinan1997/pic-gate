"""
PicGate Admin HTML Pages Router
Server-side rendered admin interface using Jinja2.
"""

import logging
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from app.db import get_db
from app.services.auth import has_any_admin
from app.routers.admin_api import sessions

logger = logging.getLogger(__name__)

# Setup templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

router = APIRouter(prefix="/admin", tags=["Admin Pages"])


def is_authenticated(request: Request) -> bool:
    """Check if request has valid session."""
    token = request.cookies.get("session")
    return token is not None and token in sessions


def get_username(request: Request) -> str:
    """Get username from session."""
    token = request.cookies.get("session")
    return sessions.get(token, "")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_root(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Admin root - redirect based on state."""
    # Check if setup needed
    if not await has_any_admin(db):
        return RedirectResponse(url="/admin/setup", status_code=302)
    
    # Check if authenticated
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return RedirectResponse(url="/admin/dashboard", status_code=302)


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Initial admin setup page."""
    # If admin exists, redirect to login
    if await has_any_admin(db):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("setup.html", {"request": request})


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Admin login page."""
    # If no admin, redirect to setup
    if not await has_any_admin(db):
        return RedirectResponse(url="/admin/setup", status_code=302)
    
    # If already authenticated, go to dashboard
    if is_authenticated(request):
        return RedirectResponse(url="/admin/dashboard", status_code=302)
    
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Admin dashboard with stats."""
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "username": get_username(request)
    })


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Settings configuration page."""
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "username": get_username(request)
    })


@router.get("/cache", response_class=HTMLResponse)
async def cache_page(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Cache management page."""
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("cache.html", {
        "request": request,
        "username": get_username(request)
    })


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Logs page."""
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("logs.html", {
        "request": request,
        "username": get_username(request)
    })


@router.get("/images", response_class=HTMLResponse)
async def images_page(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Images preview page."""
    if not is_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    return templates.TemplateResponse("images.html", {
        "request": request,
        "username": get_username(request)
    })

