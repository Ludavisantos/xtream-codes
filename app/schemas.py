from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class UserBase(BaseModel):
    username: str
    is_active: bool = True
    is_admin: bool = False
    max_connections: int = 3
    # Papel no painel: "admin" ou "vendor" (revendedor).
    role: str = "admin"
    # Validade de acesso ao painel (para vendedores).
    panel_expires_at: Optional[datetime] = None
    # Créditos de painel (para vendedores).
    panel_credits: int = 0


class UserCreate(UserBase):
    password: str
    expires_at: Optional[datetime] = None


class UserOut(UserBase):
    id: int
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True


class IntegrationCreateLine(BaseModel):
    """Payload para criação de linha IPTV via integrações externas.

    Este schema é usado pelo endpoint /integration/lines, chamado pelas Cloud Functions
    após aprovação de pagamento (ex: Mercado Pago).
    """

    external_user_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    # Meses de validade (fallback quando expires_at não é fornecido)
    months: Optional[int] = 1
    # Data de expiração exata (usada quando fornecida pela integração)
    expires_at: Optional[datetime] = None
    max_connections: int = 1


class UserInfoXtream(BaseModel):
    username: str
    status: str
    exp_date: Optional[int] = None
    max_connections: int


class ChannelXtream(BaseModel):
    # Campos básicos compatíveis com muitos apps Xtream
    num: Optional[int] = None
    name: str
    stream_type: str = "live"
    stream_id: int
    stream_icon: Optional[str] = None
    category_id: Optional[int] = None
    added: Optional[str] = None
    custom_sid: Optional[str] = None
    tv_archive: int = 0
    tv_archive_duration: int = 0
    direct_source: Optional[str] = None
    epg_channel_id: Optional[str] = None


class CategoryBase(BaseModel):
    name: str
    is_adult: bool = False


class CategoryCreate(CategoryBase):
    external_id: Optional[str] = None


class CategoryOut(CategoryBase):
    id: int
    external_id: Optional[str] = None

    class Config:
        from_attributes = True


class ChannelBase(BaseModel):
    name: str
    logo_url: Optional[str] = None
    stream_url: str
    category_id: Optional[int] = None
    is_premium: bool = False
    is_adult: bool = False
    is_available: bool = True


class ChannelCreate(ChannelBase):
    external_id: Optional[str] = None


class ChannelOut(ChannelBase):
    id: int
    external_id: Optional[str] = None

    class Config:
        from_attributes = True


class IptvLineBase(BaseModel):
    name: Optional[str] = None
    username: str
    password: str
    # Dados de contato opcionais do cliente, usados apenas para controle do vendedor
    customer_email: Optional[str] = None
    customer_phone: Optional[str] = None
    is_active: bool = True
    max_connections: int = 1
    is_test: bool = False


class IptvLineCreate(IptvLineBase):
    # Opcional: permitir que o admin escolha o dono da linha.
    owner_id: Optional[int] = None
    # Para criação via painel, normalmente usamos meses de validade em vez de data exata.
    # Se "months" for informado (>0), o backend calcula expires_at com base nisso.
    months: Optional[int] = None
    expires_at: Optional[datetime] = None


class IptvLineOut(IptvLineBase):
    id: int
    owner_id: int
    created_by: int
    created_at: datetime
    expires_at: Optional[datetime]

    class Config:
        from_attributes = True

