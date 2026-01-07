from fastapi import APIRouter, Depends, HTTPException, status, Body, Response
from sqlalchemy.orm import Session
import logging
from datetime import datetime
from typing import List

from ..database import get_db
from .. import models, schemas
from ..security import get_password_hash
from ..deps import get_current_admin, get_current_panel_user

logger = logging.getLogger("uvicorn.error")

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.get("/me", response_model=schemas.UserOut)
def get_current_panel_user_info(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_panel_user),
):
    """Retorna os dados do usuário logado no painel (admin ou vendedor)."""

    return current_user


@router.post("/bootstrap", status_code=status.HTTP_201_CREATED)
def bootstrap_first_admin(user_in: dict = Body(...), db: Session = Depends(get_db)):
    """Cria o primeiro usuário admin SEM autenticação.

    **ATENÇÃO**: esta rota só pode ser usada enquanto NÃO existir
    nenhum admin (is_admin=True ou role="admin") no banco.

    Ela existe apenas para o bootstrap inicial do painel e deve ser
    desconsiderada em produção.
    """

    admins_count = (
        db.query(models.User)
        .filter((models.User.is_admin == True) | (models.User.role == "admin"))
        .count()
    )
    if admins_count > 0:
        raise HTTPException(status_code=403, detail="Bootstrap already completed (admin exists)")

    username = user_in.get("username")
    password = user_in.get("password")
    if not username or not password:
        raise HTTPException(status_code=400, detail="username and password are required")

    existing = db.query(models.User).filter(models.User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")

    is_active = bool(user_in.get("is_active", True))
    max_connections = int(user_in.get("max_connections", 1))

    db_user = models.User(
        username=username,
        password_hash=get_password_hash(password),
        is_active=is_active,
        is_admin=True,
        max_connections=max_connections,
        # primeiro admin não precisa de expiração nem painel específico
        expires_at=None,
        role="admin",
        panel_expires_at=None,
        panel_credits=0,
    )

    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    return {
        "id": db_user.id,
        "username": db_user.username,
        "is_active": db_user.is_active,
        "is_admin": db_user.is_admin,
        "role": db_user.role,
        "panel_expires_at": db_user.panel_expires_at,
        "panel_credits": db_user.panel_credits,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_user(
    user_in: dict = Body(...),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    try:
        logger.info("[create_user] payload=%r", user_in)

        username = user_in.get("username")
        password = user_in.get("password")
        is_active = bool(user_in.get("is_active", True))
        # Papel no painel: "admin" ou "vendor". Default = admin.
        role = (user_in.get("role") or "admin").lower()
        # Mantemos is_admin em sincronia com o papel.
        is_admin = role == "admin"
        max_connections = int(user_in.get("max_connections", 1))

        # Expiração da linha IPTV (campo antigo, para o player)
        expires_at = user_in.get("expires_at")

        # Campos específicos de vendedores (painel)
        panel_expires_at = user_in.get("panel_expires_at")
        panel_credits = user_in.get("panel_credits", 0)

        existing = db.query(models.User).filter(models.User.username == username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already registered")

        # Converte expires_at para datetime se vier como string (ex.: "2026-01-05T17:44")
        if isinstance(expires_at, str) and expires_at.strip():
            try:
                # fromisoformat lida com "YYYY-MM-DDTHH:MM[:SS[.ffffff]]"
                expires_at = datetime.fromisoformat(expires_at)
            except ValueError:
                # Se formato inválido, podemos optar por None ou lançar erro 400.
                # Aqui, tratamos como None para não quebrar.
                expires_at = None

        if expires_at is None:
            expires_at = datetime.utcnow()

        # Para vendedores, exigimos validade e créditos de painel.
        if role == "vendor":
            if isinstance(panel_expires_at, str) and panel_expires_at.strip():
                try:
                    panel_expires_at_dt = datetime.fromisoformat(panel_expires_at)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid panel_expires_at format. Use ISO format, e.g. 2026-01-05T17:44",
                    )
            elif panel_expires_at is None:
                raise HTTPException(
                    status_code=400,
                    detail="panel_expires_at is required for vendor users",
                )
            else:
                panel_expires_at_dt = panel_expires_at

            try:
                panel_credits_int = int(panel_credits)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="panel_credits must be an integer")

            if panel_credits_int < 0:
                raise HTTPException(status_code=400, detail="panel_credits must be >= 0")
        else:
            panel_expires_at_dt = None
            panel_credits_int = 0

        db_user = models.User(
            username=username,
            password_hash=get_password_hash(password),
            is_active=is_active,
            is_admin=is_admin,
            max_connections=max_connections,
            expires_at=expires_at,
            role=role,
            panel_expires_at=panel_expires_at_dt,
            panel_credits=panel_credits_int,
        )
        logger.info(
            "[create_user] new User built: username=%s role=%s is_admin=%s is_active=%s expires_at=%s panel_expires_at=%s panel_credits=%s",
            db_user.username,
            db_user.role,
            db_user.is_admin,
            db_user.is_active,
            db_user.expires_at,
            db_user.panel_expires_at,
            db_user.panel_credits,
        )

        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        logger.info("[create_user] user created with id=%s", db_user.id)
        # Para evitar qualquer erro de serialização, retornamos um payload simples
        return {
            "id": db_user.id,
            "username": db_user.username,
            "is_active": db_user.is_active,
            "is_admin": db_user.is_admin,
            "role": db_user.role,
            "panel_expires_at": db_user.panel_expires_at,
            "panel_credits": db_user.panel_credits,
        }
    except HTTPException:
        # repassa erros HTTP esperados (como usuário já existente)
        logger.exception("[create_user] HTTPException raised")
        raise
    except Exception as e:
        # registra o erro completo no log e expõe o texto no detail para debug via Swagger
        logger.exception("[create_user] unexpected error")
        raise HTTPException(status_code=500, detail=f"create_user error: {e!r}")


@router.get("/", response_model=List[schemas.UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    return db.query(models.User).all()


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: models.User = Depends(get_current_admin),
):
    """Exclui um usuário de painel (admin ou vendor).

    Somente admins podem excluir. Impede que o admin exclua a si mesmo
    para evitar travar o acesso ao painel.
    """

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="Você não pode excluir a si mesmo.")

    db.delete(user)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{user_id}/expires", response_model=schemas.UserOut)
def update_user_expires(
    user_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Atualiza apenas a data de expiração de um usuário."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    expires_at = payload.get("expires_at")

    if isinstance(expires_at, str) and expires_at.strip():
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid expires_at format. Use ISO format, e.g. 2026-01-05T17:44")
    else:
        # Qualquer outro valor ("", null) é tratado como sem expiração
        expires_at = None

    user.expires_at = expires_at
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.put("/{user_id}/panel", response_model=schemas.UserOut)
def update_user_panel_info(
    user_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Atualiza informações de painel de um usuário (role, validade e créditos).

    Apenas admin pode chamar. Usado principalmente para gerenciar revendedores.
    """

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Atualiza role se enviado
    if "role" in payload:
        role = (payload["role"] or "admin").lower()
        if role not in ("admin", "vendor"):
            raise HTTPException(status_code=400, detail="role must be 'admin' or 'vendor'")
        user.role = role
        user.is_admin = role == "admin"

    # Atualiza panel_expires_at se enviado
    if "panel_expires_at" in payload:
        panel_expires_at = payload["panel_expires_at"]
        if isinstance(panel_expires_at, str) and panel_expires_at.strip():
            try:
                user.panel_expires_at = datetime.fromisoformat(panel_expires_at)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid panel_expires_at format. Use ISO format, e.g. 2026-01-05T17:44",
                )
        elif panel_expires_at is None:
            user.panel_expires_at = None

    # Atualiza créditos se enviado
    if "panel_credits" in payload:
        try:
            credits = int(payload["panel_credits"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="panel_credits must be an integer")
        if credits < 0:
            raise HTTPException(status_code=400, detail="panel_credits must be >= 0")
        user.panel_credits = credits

    db.add(user)
    db.commit()
    db.refresh(user)
    return user
