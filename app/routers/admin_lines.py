from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..deps import get_current_panel_user, get_current_admin

router = APIRouter(prefix="/admin/lines", tags=["admin-lines"])


@router.post("/", response_model=schemas.IptvLineOut, status_code=status.HTTP_201_CREATED)
def create_line(
    line_in: schemas.IptvLineCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_panel_user),
):
    """Cria uma nova linha IPTV.

    - Admin pode criar linhas para qualquer dono (owner_id), inclusive para si.
    - Vendedor só pode criar linhas para ele mesmo e consome 1 crédito por linha.
    """

    # Determina o dono da linha
    owner: models.User | None = None
    if (line_in.owner_id is not None) and (current_user.role == "admin"):
        owner = db.query(models.User).filter(models.User.id == line_in.owner_id).first()
        if not owner:
            raise HTTPException(status_code=404, detail="Owner user not found")
    else:
        owner = current_user

    if owner is None:
        raise HTTPException(status_code=400, detail="Invalid owner")

    # Garante que o username da linha é único
    existing = db.query(models.IptvLine).filter(models.IptvLine.username == line_in.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Line username already in use")

    # Calcula expiração e quantidade de meses solicitados
    months = getattr(line_in, "months", None)
    if months is not None and months <= 0:
        months = None

    if months:
        expires_at = datetime.utcnow() + timedelta(days=30 * months)
    else:
        # Define expiração padrão de 30 dias se não vier específica
        expires_at = line_in.expires_at
        if expires_at is None:
            expires_at = datetime.utcnow() + timedelta(days=30)

    is_test = getattr(line_in, "is_test", False)

    # Valida limite de conexões por linha (1 a 3)
    if line_in.max_connections < 1 or line_in.max_connections > 3:
        raise HTTPException(status_code=400, detail="max_connections must be between 1 and 3")

    # Se o dono for vendedor, precisa ter créditos disponíveis
    owner_role = (owner.role or "admin").lower()
    # Testes IPTV **não** devem debitar créditos
    if owner_role == "vendor" and not is_test:
        # Cada conexão consome 1 crédito por mês; se months não vier, assume 1 mês
        effective_months = months if months and months > 0 else 1
        max_conns = line_in.max_connections or 1
        credits_to_charge = effective_months * max_conns
        if owner.panel_credits is None or owner.panel_credits < credits_to_charge:
            raise HTTPException(
                status_code=400,
                detail="Vendor has no credits to create new lines for this period and connections",
            )
        owner.panel_credits -= credits_to_charge

    iptv_line = models.IptvLine(
        name=line_in.name,
        username=line_in.username,
        password=line_in.password,
        customer_email=getattr(line_in, "customer_email", None),
        customer_phone=getattr(line_in, "customer_phone", None),
        owner_id=owner.id,
        created_by=current_user.id,
        expires_at=expires_at,
        is_active=line_in.is_active,
        max_connections=line_in.max_connections,
        is_test=is_test,
    )

    db.add(iptv_line)
    db.add(owner)
    db.commit()
    db.refresh(iptv_line)

    return iptv_line


@router.get("/", response_model=list[schemas.IptvLineOut])
def list_lines(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_panel_user),
    owner_id: int | None = None,
    is_test: bool | None = None,
):
    """Lista linhas IPTV.

    - Admin: pode ver todas as linhas ou filtrar por owner_id.
    - Vendedor: vê apenas suas próprias linhas (ignora owner_id).
    """

    q = db.query(models.IptvLine)

    if is_test is not None:
        q = q.filter(models.IptvLine.is_test == is_test)

    role = (current_user.role or "admin").lower()
    if role == "admin":
        if owner_id is not None:
            q = q.filter(models.IptvLine.owner_id == owner_id)
    else:
        q = q.filter(models.IptvLine.owner_id == current_user.id)

    return q.order_by(models.IptvLine.id).all()


@router.post("/{line_id}/promote", response_model=schemas.IptvLineOut)
def promote_test_line(
    line_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_panel_user),
):
    """Promove uma linha de TESTE IPTV para usuário IPTV normal.

    - Apenas admin ou o vendedor dono da linha podem promover.
    - Define is_test=False e renova a validade para +30 dias.
    """

    line = db.query(models.IptvLine).filter(models.IptvLine.id == line_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Line not found")

    if not line.is_test:
        raise HTTPException(status_code=400, detail="Only test lines can be promoted")

    role = (current_user.role or "admin").lower()
    if role != "admin" and line.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to promote this line")

    # Renova validade para +30 dias a partir de agora
    line.is_test = False
    line.expires_at = datetime.utcnow() + timedelta(days=30)

    db.add(line)
    db.commit()
    db.refresh(line)
    return line


@router.patch("/{line_id}", response_model=schemas.IptvLineOut)
def update_line(
    line_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_panel_user),
):
    """Atualiza uma linha IPTV (senha, status, expiração, conexões).

    - Admin pode atualizar qualquer linha.
    - Vendedor só pode atualizar linhas que são dele (owner_id).
    """

    line = db.query(models.IptvLine).filter(models.IptvLine.id == line_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Line not found")

    role = (current_user.role or "admin").lower()
    if role != "admin" and line.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to modify this line")

    # Campos opcionais que podem ser atualizados
    if "name" in payload:
        line.name = payload.get("name") or None

    if "customer_email" in payload:
        line.customer_email = payload.get("customer_email") or None

    if "customer_phone" in payload:
        line.customer_phone = payload.get("customer_phone") or None

    if "password" in payload and isinstance(payload["password"], str) and payload["password"]:
        line.password = payload["password"]

    if "is_active" in payload:
        line.is_active = bool(payload["is_active"])

    if "max_connections" in payload:
        try:
            new_max = int(payload["max_connections"])
            if new_max < 1 or new_max > 3:
                raise HTTPException(status_code=400, detail="max_connections must be between 1 and 3")
            line.max_connections = new_max
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="max_connections must be an integer")

    # Atualização de validade com base em meses (extensão)
    months_val = payload.get("months")
    if months_val is not None:
        try:
            months_int = int(months_val)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="months must be an integer")

        if months_int > 0:
            # Base para extensão: expiração atual ou agora, se não houver
            base = line.expires_at or datetime.utcnow()
            line.expires_at = base + timedelta(days=30 * months_int)

            # Débito de créditos quando o dono for vendedor e a linha não for teste
            owner = line.owner
            if owner is not None:
                owner_role = (owner.role or "admin").lower()
                if owner_role == "vendor" and not getattr(line, "is_test", False):
                    if owner.panel_credits is None or owner.panel_credits < months_int:
                        raise HTTPException(
                            status_code=400,
                            detail="Vendor has no credits to extend this line for the requested period",
                        )
                    owner.panel_credits -= months_int
                    db.add(owner)

    # Atualização direta de expires_at (mantida para compatibilidade)
    if "expires_at" in payload:
        expires_at = payload["expires_at"]
        if isinstance(expires_at, str) and expires_at.strip():
            try:
                expires_at_dt = datetime.fromisoformat(expires_at)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid expires_at format. Use ISO format, e.g. 2026-01-05T17:44",
                )
            line.expires_at = expires_at_dt
        elif expires_at is None:
            line.expires_at = None

    db.add(line)
    db.commit()
    db.refresh(line)
    return line


@router.delete("/{line_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_line(
    line_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_panel_user),
):
    """Remove uma linha IPTV.

    - Admin pode remover qualquer linha.
    - Vendedor só pode remover suas próprias linhas.
    - Créditos não são devolvidos automaticamente.
    """

    line = db.query(models.IptvLine).filter(models.IptvLine.id == line_id).first()
    if not line:
        raise HTTPException(status_code=404, detail="Line not found")

    role = (current_user.role or "admin").lower()
    if role != "admin" and line.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to delete this line")

    db.delete(line)
    db.commit()
    return None


@router.post("/bulk/delete", status_code=status.HTTP_204_NO_CONTENT)
def bulk_delete_lines(
    ids: list[int],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_panel_user),
):
    """Exclui várias linhas IPTV de uma vez.

    - Admin pode excluir qualquer linha.
    - Vendedor só pode excluir suas próprias linhas.
    """

    if not ids:
        return None

    role = (current_user.role or "admin").lower()
    q = db.query(models.IptvLine).filter(models.IptvLine.id.in_(ids))
    if role != "admin":
        q = q.filter(models.IptvLine.owner_id == current_user.id)

    lines = q.all()
    for line in lines:
        db.delete(line)

    db.commit()
    return None


@router.post("/bulk/renew", response_model=list[schemas.IptvLineOut])
def bulk_renew_lines(
    ids: list[int],
    months: int = 1,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_panel_user),
):
    """Renova várias linhas IPTV em lote, adicionando N meses à validade.

    - Debita créditos do vendedor: meses * max_connections por linha.
    - Admin pode renovar qualquer linha; vendedor só as próprias.
    """

    if not ids or months <= 0:
        return []

    role = (current_user.role or "admin").lower()
    q = db.query(models.IptvLine).filter(models.IptvLine.id.in_(ids), models.IptvLine.is_test == False)  # noqa: E712
    if role != "admin":
        q = q.filter(models.IptvLine.owner_id == current_user.id)

    lines = q.all()

    # Agrupa por dono para debitar créditos corretamente
    owners: dict[int, models.User] = {}
    for line in lines:
        owner = owners.get(line.owner_id)
        if owner is None:
            owner = db.query(models.User).filter(models.User.id == line.owner_id).first()
            if owner is None:
                continue
            owners[line.owner_id] = owner

        owner_role = (owner.role or "admin").lower()
        if owner_role == "vendor":
            max_conns = line.max_connections or 1
            if max_conns < 1:
                max_conns = 1
            credits_to_charge = months * max_conns
            if owner.panel_credits is None or owner.panel_credits < credits_to_charge:
                raise HTTPException(
                    status_code=400,
                    detail="Vendor has no credits to renew selected lines for this period",
                )
            owner.panel_credits -= credits_to_charge

        base = line.expires_at or datetime.utcnow()
        line.expires_at = base + timedelta(days=30 * months)
        db.add(line)

    for owner in owners.values():
        db.add(owner)

    db.commit()

    # Recarrega as linhas atualizadas
    return (
        db.query(models.IptvLine)
        .filter(models.IptvLine.id.in_([ln.id for ln in lines]))
        .order_by(models.IptvLine.id)
        .all()
    )


@router.post("/bulk/change-owner", response_model=list[schemas.IptvLineOut])
def bulk_change_owner(
    ids: list[int],
    new_owner_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_admin),
):
    """Altera o dono (revendedor) de várias linhas em lote.

    - Apenas admin pode executar.
    """

    if not ids:
        return []

    new_owner = db.query(models.User).filter(models.User.id == new_owner_id).first()
    if not new_owner:
        raise HTTPException(status_code=404, detail="New owner not found")

    lines = db.query(models.IptvLine).filter(models.IptvLine.id.in_(ids)).all()
    for line in lines:
        line.owner_id = new_owner.id
        db.add(line)

    db.commit()

    return (
        db.query(models.IptvLine)
        .filter(models.IptvLine.id.in_([ln.id for ln in lines]))
        .order_by(models.IptvLine.id)
        .all()
    )
