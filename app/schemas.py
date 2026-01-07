from datetime import datetime
from pydantic import BaseModel


class UserBase(BaseModel):
    username: str
    is_active: bool = True
    is_admin: bool = False
    max_connections: int = 3
    # Papel no painel: "admin" ou "vendor" (revendedor).
    role: str = "admin"
    # Validade de acesso ao painel (para vendedores).
    panel_expires_at: datetime | None = None
    # Créditos de painel (para vendedores).
    panel_credits: int = 0


class UserCreate(UserBase):
    password: str
    expires_at: datetime | None = None


class UserOut(UserBase):
    id: int
    expires_at: datetime | None

    class Config:
        from_attributes = True


class UserInfoXtream(BaseModel):
    username: str
    status: str
    exp_date: int | None = None
    max_connections: int


class ChannelXtream(BaseModel):
    # Campos básicos compatíveis com muitos apps Xtream
    num: int | None = None
    name: str
    stream_type: str = "live"
    stream_id: int
    stream_icon: str | None = None
    category_id: int | None = None
    added: str | None = None
    custom_sid: str | None = None
    tv_archive: int = 0
    tv_archive_duration: int = 0
    direct_source: str | None = None
    epg_channel_id: str | None = None


class CategoryBase(BaseModel):
    name: str
    is_adult: bool = False


class CategoryCreate(CategoryBase):
    external_id: str | None = None


class CategoryOut(CategoryBase):
    id: int
    external_id: str | None = None

    class Config:
        from_attributes = True


class ChannelBase(BaseModel):
    name: str
    logo_url: str | None = None
    stream_url: str
    category_id: int | None = None
    is_premium: bool = False
    is_adult: bool = False
    is_available: bool = True


class ChannelCreate(ChannelBase):
    external_id: str | None = None


class ChannelOut(ChannelBase):
    id: int
    external_id: str | None = None

    class Config:
        from_attributes = True


class IptvLineBase(BaseModel):
    name: str | None = None
    username: str
    password: str
    # Dados de contato opcionais do cliente, usados apenas para controle do vendedor
    customer_email: str | None = None
    customer_phone: str | None = None
    is_active: bool = True
    max_connections: int = 1
    is_test: bool = False


class IptvLineCreate(IptvLineBase):
    # Opcional: permitir que o admin escolha o dono da linha.
    owner_id: int | None = None
    # Para criação via painel, normalmente usamos meses de validade em vez de data exata.
    # Se "months" for informado (>0), o backend calcula expires_at com base nisso.
    months: int | None = None
    expires_at: datetime | None = None


class IptvLineOut(IptvLineBase):
    id: int
    owner_id: int
    created_by: int
    created_at: datetime
    expires_at: datetime | None

    class Config:
        from_attributes = True

