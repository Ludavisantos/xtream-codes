from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base
from datetime import datetime, timedelta


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=True)
    max_connections = Column(Integer, default=3)
    # Papel no painel: "admin" ou "vendor" (revendedor). Por padrão, admin.
    role = Column(String, default="admin")
    # Validade de acesso ao painel (usado para vendedores).
    panel_expires_at = Column(DateTime, nullable=True)
    # Créditos do vendedor: quantas linhas de 30 dias ele pode criar.
    panel_credits = Column(Integer, default=0)

    @staticmethod
    def default_expiration(days: int = 30) -> datetime:
        return datetime.utcnow() + timedelta(days=days)


class ChannelCategory(Base):
    __tablename__ = "channel_categories"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String, index=True, nullable=True)
    name = Column(String, nullable=False)
    is_adult = Column(Boolean, default=False)

    channels = relationship("Channel", back_populates="category")


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String, index=True, nullable=True)
    name = Column(String, nullable=False)
    logo_url = Column(String, nullable=True)
    stream_url = Column(String, nullable=False)
    category_id = Column(Integer, ForeignKey("channel_categories.id"), nullable=True)
    is_premium = Column(Boolean, default=False)
    is_adult = Column(Boolean, default=False)
    is_available = Column(Boolean, default=True)

    category = relationship("ChannelCategory", back_populates="channels")


class VodContent(Base):
    __tablename__ = "vod_contents"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String, index=True, nullable=True)
    tmdb_id = Column(Integer, nullable=True)
    title = Column(String, nullable=False)
    type = Column(String, nullable=False)  # movie, tv, series
    poster_url = Column(String, nullable=True)
    backdrop_url = Column(String, nullable=True)
    category = Column(String, nullable=True)
    stream_url = Column(String, nullable=True)
    is_available = Column(Boolean, default=True)

    # Metadados ricos persistidos da TMDB (para filmes e séries)
    overview = Column(String, nullable=True)
    vote_average = Column(String, nullable=True)  # armazena como string "7.8" para reutilizar direto
    rating_5based = Column(String, nullable=True)  # também como string para facilitar uso nas respostas
    release_date = Column(String, nullable=True)  # YYYY-MM-DD (release_date ou first_air_date)
    genres = Column(String, nullable=True)  # nomes separados por vírgula
    cast = Column(String, nullable=True)  # nomes separados por vírgula
    director = Column(String, nullable=True)  # nomes separados por vírgula (diretores/principais)
    duration_secs = Column(Integer, nullable=True)  # duração em segundos, quando disponível


class Episode(Base):
    """Episódios de séries, derivados de VodContent + disponibilidade externa.

    Um Episode representa um (tmdb_id, temporada, episódio) específico e já contém
    a URL final do arquivo de vídeo, além de metadados básicos para playlist.
    """

    __tablename__ = "episodes"

    id = Column(Integer, primary_key=True, index=True)
    vod_id = Column(Integer, ForeignKey("vod_contents.id"), nullable=True)
    tmdb_id = Column(Integer, index=True, nullable=False)
    season = Column(Integer, nullable=False)
    episode = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    category = Column(String, nullable=True)
    poster_url = Column(String, nullable=True)
    stream_url = Column(String, nullable=False)
    is_available = Column(Boolean, default=True)
    # Duração em segundos (vinda da TMDB, quando disponível)
    duration_secs = Column(Integer, nullable=True)


class IptvLine(Base):
    """Linha IPTV final (usuário que acessa via player Xtream).

    Separado do User de painel. Cada linha pertence a um vendedor (ou admin).
    """

    __tablename__ = "iptv_lines"

    id = Column(Integer, primary_key=True, index=True)
    # Nome do cliente (opcional, usado para controle do vendedor)
    name = Column(String, nullable=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    # Dados de contato do cliente (opcionais)
    customer_email = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    # Dono da linha: normalmente um vendedor; pode ser admin.
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # Usuário de painel que criou a linha (pode ser diferente do owner em caso de admin)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Data de expiração da linha (ex.: 30 dias).
    expires_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    max_connections = Column(Integer, default=1)
    # Indica se a linha é um TESTE IPTV (true) ou um usuário IPTV normal (false).
    is_test = Column(Boolean, default=False, index=True)

    owner = relationship("User", foreign_keys=[owner_id])

