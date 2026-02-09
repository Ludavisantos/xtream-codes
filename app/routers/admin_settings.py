from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..deps import get_db, get_current_panel_user, get_current_admin

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])


def _get_or_create_settings(db: Session) -> models.PanelSettings:
    settings = db.query(models.PanelSettings).first()
    if settings is None:
        settings = models.PanelSettings(
            panel_name="Xtream Python",
            server_message="",
            sync_mode="contents_json",
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _get_or_create_ui_settings(db: Session) -> models.PanelUiSettings:
    ui = db.query(models.PanelUiSettings).first()
    if ui is None:
        ui = models.PanelUiSettings(timezone="UTC", login_theme="default", panel_theme="default")
        db.add(ui)
        db.commit()
        db.refresh(ui)
    return ui


@router.get("/", response_model=dict)
def get_settings(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_panel_user),
):
    settings = _get_or_create_settings(db)
    ui = _get_or_create_ui_settings(db)
    return {
        "panel_name": settings.panel_name,
        "server_message": settings.server_message or "",
        "sync_mode": settings.sync_mode or "contents_json",
        "origin_host": settings.origin_host or "",
        "origin_username": settings.origin_username or "",
        # Nunca retornamos a senha em texto plano; apenas indicador se existe
        "origin_password_set": bool(settings.origin_password),
        "timezone": ui.timezone or "UTC",
        "login_theme": ui.login_theme or "default",
        "panel_theme": ui.panel_theme or "default",
    }


@router.put("/", response_model=dict)
def update_settings(
    payload: dict,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    panel_name = (payload.get("panel_name") or "").strip()
    server_message = (payload.get("server_message") or "").strip()
    timezone = (payload.get("timezone") or "UTC").strip()
    login_theme = (payload.get("login_theme") or "default").strip()
    panel_theme = (payload.get("panel_theme") or "default").strip()

    sync_mode = (payload.get("sync_mode") or "contents_json").strip()
    origin_host = (payload.get("origin_host") or "").strip()
    origin_username = (payload.get("origin_username") or "").strip()

    origin_password_raw = payload.get("origin_password")

    if not panel_name:
        raise HTTPException(status_code=400, detail="panel_name is required")

    if sync_mode not in ("contents_json", "xtream_origin"):
        raise HTTPException(status_code=400, detail="sync_mode must be 'contents_json' or 'xtream_origin'")

    if sync_mode == "xtream_origin":
        if not origin_host or not origin_username:
            raise HTTPException(
                status_code=400,
                detail="origin_host and origin_username are required when sync_mode is 'xtream_origin'",
            )

    settings = _get_or_create_settings(db)
    settings.panel_name = panel_name
    settings.server_message = server_message
    settings.sync_mode = sync_mode
    settings.origin_host = origin_host or None
    settings.origin_username = origin_username or None
    if isinstance(origin_password_raw, str) and origin_password_raw.strip():
        settings.origin_password = origin_password_raw.strip()

    ui = _get_or_create_ui_settings(db)
    ui.timezone = timezone or "UTC"
    ui.login_theme = login_theme or "default"
    ui.panel_theme = panel_theme or "default"

    db.add(settings)
    db.add(ui)
    db.commit()
    db.refresh(settings)
    db.refresh(ui)

    return {
        "panel_name": settings.panel_name,
        "server_message": settings.server_message or "",
        "sync_mode": settings.sync_mode or "contents_json",
        "origin_host": settings.origin_host or "",
        "origin_username": settings.origin_username or "",
        "origin_password_set": bool(settings.origin_password),
        "timezone": ui.timezone or "UTC",
        "login_theme": ui.login_theme or "default",
    }
