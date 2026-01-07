from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models
from ..deps import get_current_admin

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])


def _get_or_create_settings(db: Session) -> models.PanelSettings:
    settings = db.query(models.PanelSettings).first()
    if settings is None:
        settings = models.PanelSettings(panel_name="Xtream Python", server_message="")
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("/", response_model=dict)
def get_settings(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    settings = _get_or_create_settings(db)
    return {
        "panel_name": settings.panel_name,
        "server_message": settings.server_message or "",
    }


@router.put("/", response_model=dict)
def update_settings(
    payload: dict,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    panel_name = (payload.get("panel_name") or "").strip()
    server_message = (payload.get("server_message") or "").strip()

    if not panel_name:
        raise HTTPException(status_code=400, detail="panel_name is required")

    settings = _get_or_create_settings(db)
    settings.panel_name = panel_name
    settings.server_message = server_message

    db.add(settings)
    db.commit()
    db.refresh(settings)

    return {
        "panel_name": settings.panel_name,
        "server_message": settings.server_message or "",
    }
