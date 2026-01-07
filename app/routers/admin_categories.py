from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..deps import get_current_admin

router = APIRouter(prefix="/admin/categories", tags=["admin-categories"])


@router.post("/", response_model=schemas.CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    category_in: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    db_cat = models.ChannelCategory(
        name=category_in.name,
        is_adult=category_in.is_adult,
        external_id=category_in.external_id,
    )
    db.add(db_cat)
    db.commit()
    db.refresh(db_cat)
    return db_cat
@router.get("/", response_model=list[schemas.CategoryOut])
def list_categories(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    return db.query(models.ChannelCategory).order_by(models.ChannelCategory.id).all()


@router.get("/{category_id}", response_model=schemas.CategoryOut)
def get_category(
    category_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    cat = db.query(models.ChannelCategory).filter(models.ChannelCategory.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    return cat

@router.put("/{category_id}", response_model=schemas.CategoryOut)
def update_category(
    category_id: int,
    category_in: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    cat = db.query(models.ChannelCategory).filter(models.ChannelCategory.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    cat.name = category_in.name
    cat.is_adult = category_in.is_adult
    cat.external_id = category_in.external_id
    db.commit()
    db.refresh(cat)
    return cat

@router.delete("/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    cat = db.query(models.ChannelCategory).filter(models.ChannelCategory.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    db.delete(cat)
    db.commit()
    return None
