from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from ..deps import get_current_admin
from .. import models

router = APIRouter(prefix="/admin/vod", tags=["admin-vod"])


@router.get("/")
async def list_vod(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Lista conteúdos VOD (filmes e séries) básicos para o painel admin."""

    items = (
        db.query(models.VodContent)
        .order_by(models.VodContent.id)
        .all()
    )
    out: List[dict] = []
    for v in items:
        out.append(
            {
                "id": v.id,
                "title": v.title,
                "type": v.type,
                "tmdb_id": v.tmdb_id,
                "category": v.category,
                "is_available": v.is_available,
            }
        )
    return out


@router.put("/{vod_id}")
async def update_vod(
    vod_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Atualiza campos simples de um VOD (por enquanto, apenas is_available)."""

    vod = db.query(models.VodContent).filter(models.VodContent.id == vod_id).first()
    if not vod:
        raise HTTPException(status_code=404, detail="VOD not found")

    if "is_available" in payload:
        vod.is_available = bool(payload["is_available"])

    db.add(vod)
    db.commit()
    db.refresh(vod)

    return {
        "id": vod.id,
        "title": vod.title,
        "type": vod.type,
        "tmdb_id": vod.tmdb_id,
        "category": vod.category,
        "is_available": vod.is_available,
    }
