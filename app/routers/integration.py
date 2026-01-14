from datetime import datetime, timedelta
import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
import logging

router = APIRouter(prefix="/integration", tags=["integration"])


def _check_integration_api_key(auth_header: Optional[str]) -> None:
    default_key = "ffdLoKJAoamU432"
    env_integration = os.getenv("IPTV_INTEGRATION_API_KEY")
    env_iptv = os.getenv("IPTV_API_KEY")
    expected = env_integration or env_iptv or default_key

    def _mask(v: Optional[str]) -> str:
        if not v:
            return "<none>"
        if len(v) <= 4:
            return "*" * len(v)
        return f"{v[:2]}***{v[-2:]}(len={len(v)})"

    # Extrai chave do header Authorization: Bearer <KEY>
    key = None
    if auth_header and auth_header.startswith("Bearer "):
        key = auth_header[len("Bearer ") :].strip()

    logging.getLogger("integration").info(
        "[integration] API key check - header=%s, env_integration=%s, env_iptv=%s, expected=%s",
        _mask(key),
        _mask(env_integration),
        _mask(env_iptv),
        _mask(expected),
    )

    # Também envia para stdout para aparecer claramente nos logs do serviço
    print(
        "[integration] API key check - header=",
        _mask(key),
        "env_integration=",
        _mask(env_integration),
        "env_iptv=",
        _mask(env_iptv),
        "expected=",
        _mask(expected),
    )

    if not expected or key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid integration API key",
        )


def _get_default_owner(db: Session) -> models.User:
    """Retorna um usuário admin para ser dono das linhas criadas pela integração.

    Preferimos um user com role="admin"; se não existir, pegamos o primeiro admin legacy
    (is_admin=True)."""

    owner = (
        db.query(models.User)
        .filter(models.User.role == "admin")
        .order_by(models.User.id)
        .first()
    )
    if not owner:
        owner = (
            db.query(models.User)
            .filter(models.User.is_admin.is_(True))
            .order_by(models.User.id)
            .first()
        )
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No admin user available as IPTV owner",
        )
    return owner


@router.post("/lines", response_model=schemas.IptvLineOut, status_code=status.HTTP_201_CREATED)
def create_line_from_integration(
    payload: schemas.IntegrationCreateLine,
    db: Session = Depends(get_db),
    authorization: Optional[str] = Header(default=None),
):
    """Cria uma linha IPTV via integração externa (ex: app mobile + Mercado Pago).

    Autenticação é feita por API key via header `X-API-KEY`.

    - Dono da linha: um admin padrão (não debita créditos de revendedor).
    - Username/senha são gerados automaticamente.
    - Expiração: `months` meses a partir de agora (mínimo 1 mês).
    - max_connections é limitado ao intervalo [1, 3].
    """

    _check_integration_api_key(authorization)

    owner = _get_default_owner(db)

    # Define validade em meses (mínimo 1)
    months = payload.months if payload.months and payload.months > 0 else 1
    expires_at = datetime.utcnow() + timedelta(days=30 * months)

    # Garante max_connections entre 1 e 3
    max_conns = payload.max_connections or 1
    if max_conns < 1:
        max_conns = 1
    if max_conns > 3:
        max_conns = 3

    # Gera username/senha aleatórios, garantindo unicidade do username
    base_username = f"u{payload.external_user_id[:6]}" if payload.external_user_id else "u"
    suffix = 1
    username = f"{base_username}{suffix}"
    while db.query(models.IptvLine).filter(models.IptvLine.username == username).first() is not None:
        suffix += 1
        username = f"{base_username}{suffix}"

    password = os.urandom(6).hex()

    iptv_line = models.IptvLine(
        name=payload.name,
        username=username,
        password=password,
        customer_email=payload.email,
        customer_phone=payload.phone,
        owner_id=owner.id,
        created_by=owner.id,
        expires_at=expires_at,
        is_active=True,
        max_connections=max_conns,
        is_test=False,
    )

    db.add(iptv_line)
    db.commit()
    db.refresh(iptv_line)

    return iptv_line
