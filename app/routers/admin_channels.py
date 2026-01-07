from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..deps import get_current_admin

router = APIRouter(prefix="/admin/channels", tags=["admin-channels"])


@router.post("/", response_model=schemas.ChannelOut, status_code=status.HTTP_201_CREATED)
def create_channel(
    channel_in: schemas.ChannelCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    db_ch = models.Channel(
        name=channel_in.name,
        logo_url=channel_in.logo_url,
        stream_url=channel_in.stream_url,
        category_id=channel_in.category_id,
        is_premium=channel_in.is_premium,
        is_adult=channel_in.is_adult,
        is_available=channel_in.is_available,
        external_id=channel_in.external_id,
    )
    db.add(db_ch)
    db.commit()
    db.refresh(db_ch)
    return db_ch
@router.get("/", response_model=list[schemas.ChannelOut])
def list_channels(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    return db.query(models.Channel).order_by(models.Channel.id).all()


@router.get("/{channel_id}", response_model=schemas.ChannelOut)
def get_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    ch = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    return ch

@router.put("/{channel_id}", response_model=schemas.ChannelOut)
def update_channel(
    channel_id: int,
    channel_in: schemas.ChannelCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    ch = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    ch.name = channel_in.name
    ch.logo_url = channel_in.logo_url
    ch.stream_url = channel_in.stream_url
    ch.category_id = channel_in.category_id
    ch.is_premium = channel_in.is_premium
    ch.is_adult = channel_in.is_adult
    ch.is_available = channel_in.is_available
    ch.external_id = channel_in.external_id
    db.commit()
    db.refresh(ch)
    return ch

@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(
    channel_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    ch = db.query(models.Channel).filter(models.Channel.id == channel_id).first()
    if not ch:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(ch)
    db.commit()
    return None
