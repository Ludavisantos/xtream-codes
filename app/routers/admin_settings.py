from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..deps import get_db, get_current_panel_user, get_current_admin

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])


def _get_or_create_settings(db: Session) -> models.PanelSettings:
    settings = db.query(models.PanelSettings).first()
    if settings is None:
        settings = models.PanelSettings(panel_name="Xtream Python", server_message="")
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _get_or_create_ui_settings(db: Session) -> models.PanelUiSettings:
    ui = db.query(models.PanelUiSettings).first()
    if ui is None:
        ui = models.PanelUiSettings(timezone="UTC", login_theme="default")
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
        "timezone": ui.timezone or "UTC",
        "login_theme": ui.login_theme or "default",
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

    if not panel_name:
        raise HTTPException(status_code=400, detail="panel_name is required")

    settings = _get_or_create_settings(db)
    settings.panel_name = panel_name
    settings.server_message = server_message

    ui = _get_or_create_ui_settings(db)
    ui.timezone = timezone or "UTC"
    ui.login_theme = login_theme or "default"

    db.add(settings)
    db.add(ui)
    db.commit()
    db.refresh(settings)
    db.refresh(ui)

    return {
        "panel_name": settings.panel_name,
        "server_message": settings.server_message or "",
        "timezone": ui.timezone or "UTC",
        "login_theme": ui.login_theme or "default",
    }
