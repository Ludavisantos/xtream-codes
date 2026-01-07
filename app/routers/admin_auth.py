from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import datetime

from ..database import get_db
from .. import models
from ..security import verify_password, create_access_token


router = APIRouter(prefix="/admin", tags=["admin-auth"])


@router.post("/login")
async def admin_login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Login para o painel (admin ou vendedor).

    - Admin: role="admin" e is_admin=True.
    - Vendedor: role="vendor" e panel_expires_at ainda válida.
    """

    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário inativo")

    role = (user.role or "admin").lower()

    # Regra para admin de painel
    if role == "admin":
        if not user.is_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso não autorizado")

    # Regra para vendedor de painel
    elif role == "vendor":
        if user.panel_expires_at is None or user.panel_expires_at < datetime.utcnow():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Painel do revendedor expirado")

    else:
        # Qualquer outro papel não tem acesso ao painel
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso não autorizado para este papel")

    access_token = create_access_token({
        "sub": user.username,
        "is_admin": bool(user.is_admin),
        "role": role,
    })
    return {"access_token": access_token, "token_type": "bearer"}
