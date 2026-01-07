from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from sqlalchemy.orm import Session
from datetime import datetime
import asyncio

import httpx

from ..database import get_db
from .. import models, schemas
from ..security import verify_password

router = APIRouter(tags=["xtream"])


def _xtream_response(payload: dict | list) -> JSONResponse:
    """Retorna JSONResponse com charset UTF-8 explícito para compatibilidade.

    Alguns apps (como XCIPTV) interpretam JSON sem charset como ISO-8859-1,
    corrompendo acentos. Aqui forçamos application/json; charset=utf-8.
    """

    return JSONResponse(payload, media_type="application/json; charset=utf-8")


def _auth_user(username: str, password: str, db: Session):
    """Autentica credenciais para endpoints Xtream.

    Suporta tanto usuários de painel (models.User) quanto linhas IPTV finais
    (models.IptvLine), permitindo que o cliente use o usuário/senha da linha.

    Comportamento de senha para User (painel):
    - Alguns clientes (como IPTV Smarters) fazem o login inicial com a senha
      correta, mas em chamadas subsequentes ao player_api.php enviam
      `password=undefined`. Para compatibilidade, se o password vier
      vazio/"undefined", aceitamos o usuário apenas com base em
      username + ativo + validade, SEM verificar a senha novamente.

    Para IptvLine usamos a senha em texto puro da coluna `password`.
    """

    # Primeiro tentamos autenticar como User de painel
    user = db.query(models.User).filter(models.User.username == username).first()
    if user is not None:
        if password not in (None, "", "undefined"):
            if not verify_password(password, user.password_hash):
                return None

        if not user.is_active or (user.expires_at and user.expires_at < datetime.utcnow()):
            return None
        return user

    # Se não houver User com esse username, tentamos como linha IPTV final
    line = db.query(models.IptvLine).filter(models.IptvLine.username == username).first()
    if line is None:
        return None

    # Para linhas IPTV, comparamos senha em texto puro (não há hash).
    if password not in (None, "", "undefined"):
        if password != line.password:
            return None

    if not line.is_active or (line.expires_at and line.expires_at < datetime.utcnow()):
        return None
    return line


def _xtream_error(status: str, reason: str | None = None):
    payload = {
        "user_info": {
            "auth": 0,
            "status": status,
        },
        "server_info": {},
    }
    if reason:
        payload["user_info"]["reason"] = reason
    return _xtream_response(payload)


@router.get("/player_api.php")
async def player_api(
    request: Request,
    username: str,
    password: str,
    action: str | None = None,
    db: Session = Depends(get_db),
):
    user = _auth_user(username, password, db)
    if not user:
        return _xtream_error("Blocked", "Authentication Failed")

    # get_user_info: payload compatível com Xtream Codes / xui
    if action is None or action == "get_user_info":
        exp_timestamp = int(user.expires_at.timestamp()) if user.expires_at else 0

        # user_info no formato esperado por clientes como XCIPTV
        user_info = {
            "username": user.username,
            "password": password,
            "message": "",
            "auth": 1,
            "status": "Active",
            "exp_date": str(exp_timestamp) if exp_timestamp else "0",
            "is_trial": "0",
            "active_cons": "0",
            # Criado agora; se você tiver um campo created_at no futuro, pode usar aqui.
            "created_at": str(int(datetime.utcnow().timestamp())),
            "max_connections": str(user.max_connections),
            "allowed_output_formats": ["m3u8", "ts", "rtmp"],
        }

        # server_info com campos básicos compatíveis com xui/Xtream
        base_url = str(request.base_url).rstrip("/")
        # Extrai host, porta e protocolo de base_url
        try:
            from urllib.parse import urlparse

            parsed = urlparse(base_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            scheme = parsed.scheme or "http"
        except Exception:
            host = "localhost"
            port = 80
            scheme = "http"

        server_info = {
            "xui": True,
            "version": "1.0.0",
            "revision": 1,
            "url": host,
            "port": str(port),
            "https_port": "443",
            "server_protocol": scheme,
            "rtmp_port": "8880",
            "timestamp_now": int(datetime.utcnow().timestamp()),
            "time_now": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": "America/SAO_Paulo".replace("SAO", "Sao"),
        }

        return _xtream_response({"user_info": user_info, "server_info": server_info})

    # get_live_streams: lista de canais ao vivo
    if action == "get_live_streams":
        channels = (
            db.query(models.Channel)
            .filter(models.Channel.is_available == True)
            .order_by(models.Channel.id)
            .all()
        )
        out: list[dict] = []
        for idx, ch in enumerate(channels, start=1):
            out.append(
                {
                    "num": idx,
                    "name": ch.name,
                    "stream_type": "live",
                    "stream_id": ch.id,
                    "stream_icon": ch.logo_url,
                    "category_id": ch.category_id,
                    "added": "",
                    "custom_sid": "",
                    "tv_archive": 0,
                    "tv_archive_duration": 0,
                    "direct_source": ch.stream_url,
                    "epg_channel_id": None,
                }
            )
        return _xtream_response(out)

    # get_vod_info: detalhes de um VOD específico (filme/série única)
    if action == "get_vod_info":
        vod_id_raw = request.query_params.get("vod_id")
        try:
            vod_id = int(vod_id_raw) if vod_id_raw is not None else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid vod_id")

        if vod_id is None:
            raise HTTPException(status_code=400, detail="vod_id is required")

        vod = (
            db.query(models.VodContent)
            .filter(models.VodContent.id == vod_id)
            .first()
        )
        if not vod or not vod.is_available:
            raise HTTPException(status_code=404, detail="VOD not found")

        # Metadados ricos já persistidos na tabela VodContent pela sync.
        releasedate = vod.release_date or ""
        plot = vod.overview or ""
        rating = vod.vote_average or "0.0"
        try:
            rating_5based = float(vod.rating_5based) if vod.rating_5based is not None else 0
        except Exception:
            rating_5based = 0
        duration_secs = vod.duration_secs or 0
        genres_str = vod.genres or ""
        cast_str = vod.cast or ""
        director_str = vod.director or ""

        # Resposta no estilo Xtream Codes, usando metadados já salvos.
        info = {
            "name": vod.title,
            "o_name": vod.title,
            "movie_image": vod.poster_url,
            "releasedate": releasedate,
            "plot": plot,
            "rating": rating,
            "rating_5based": rating_5based,
            "category_id": vod.category,
            "duration_secs": duration_secs,
            "genre": genres_str,
            "director": director_str,
            "cast": cast_str,
            # Campos adicionais próximos ao exemplo: usamos defaults onde não há dado específico
            "releaseDate": releasedate,
            "backdrop_path": [],
            "youtube_trailer": "",
            "episode_run_time": 0,
            "subtitles": [],
            "cover_big": vod.poster_url,
        }
        movie_data = {
            "stream_id": vod.id,
            "name": vod.title,
            "title": vod.title,
            "year": None,
            "stream_type": "movie" if vod.type.lower() in {"movie", "filme"} else vod.type,
            "stream_icon": vod.poster_url,
            "container_extension": "mp4",
            "custom_sid": "",
            "direct_source": vod.stream_url,
            "tmdb_id": vod.tmdb_id,
            "added": str(int(datetime.utcnow().timestamp())),
            "category_id": vod.category or "0",
            "category_ids": [0],
        }
        return _xtream_response({"info": info, "movie_data": movie_data})

    # get_live_categories: lista de categorias de canais
    if action == "get_live_categories":
        cats = (
            db.query(models.ChannelCategory)
            .order_by(models.ChannelCategory.id)
            .all()
        )
        out: list[dict] = []
        for cat in cats:
            out.append(
                {
                    "category_id": str(cat.id),
                    "category_name": cat.name,
                    "parent_id": 0,
                }
            )
        return _xtream_response(out)

    # get_vod_categories: categorias para filmes VOD
    if action == "get_vod_categories":
        # Usamos o campo category de VodContent para agrupar.
        rows = (
            db.query(models.VodContent.category)
            .filter(
                models.VodContent.is_available == True,
                models.VodContent.type.in_(["movie", "filme"]),
                models.VodContent.category.isnot(None),
            )
            .distinct()
            .all()
        )
        out: list[dict] = []

        # Categoria "Todos" padrão para VOD.
        out.append(
            {
                "category_id": "0",
                "category_name": "Todos",
                "parent_id": 0,
            }
        )

        for idx, (name,) in enumerate(rows, start=1):
            out.append(
                {
                    "category_id": str(idx),
                    "category_name": name or "Filmes",
                    "parent_id": 0,
                }
            )
        return _xtream_response(out)

    # get_vod_streams: lista de conteúdos VOD (filmes)
    if action == "get_vod_streams":
        vod_list = (
            db.query(models.VodContent)
            .filter(
                models.VodContent.is_available == True,
                models.VodContent.type.in_(["movie", "filme"]),
            )
            .order_by(models.VodContent.id)
            .all()
        )

        # Mapeia categorias de VOD para os mesmos IDs de get_vod_categories.
        cat_rows = (
            db.query(models.VodContent.category)
            .filter(
                models.VodContent.is_available == True,
                models.VodContent.type.in_(["movie", "filme"]),
                models.VodContent.category.isnot(None),
            )
            .distinct()
            .all()
        )
        vod_cat_map: dict[str, int] = {}
        for idx, (name,) in enumerate(cat_rows, start=1):
            key = name or "Filmes"
            vod_cat_map[key] = idx

        out: list[dict] = []
        for idx, vod in enumerate(vod_list, start=1):
            # Muitos painéis Xtream usam campos parecidos para VOD
            cat_name = vod.category or "Filmes"
            cat_id = vod_cat_map.get(cat_name, 0)
            out.append(
                {
                    "num": idx,
                    "name": vod.title,
                    "stream_type": "movie" if vod.type.lower() in {"movie", "filme"} else vod.type,
                    "stream_id": vod.id,
                    "stream_icon": vod.poster_url,
                    "rating": vod.vote_average or "0.0",
                    "rating_5based": float(vod.rating_5based) if vod.rating_5based is not None else 0,
                    "added": "",
                    "category_id": cat_id,
                    "container_extension": "mp4",
                    "custom_sid": "",
                    "direct_source": vod.stream_url,
                }
            )
        return _xtream_response(out)

    # get_series: lista de séries (tv/series)
    if action == "get_series":
        category_filter_raw = request.query_params.get("category_id")
        # Em muitos painéis, "0" ou ausência de category_id significa "Todos".
        try:
            category_filter = int(category_filter_raw) if category_filter_raw is not None else None
        except (TypeError, ValueError):
            category_filter = None

        series_list = (
            db.query(models.VodContent)
            .filter(
                models.VodContent.is_available == True,
                models.VodContent.type.in_(["tv", "series"]),
            )
            .order_by(models.VodContent.id)
            .all()
        )

        # Mapeia categorias de séries para os mesmos IDs de get_series_categories.
        cat_rows = (
            db.query(models.VodContent.category)
            .filter(
                models.VodContent.is_available == True,
                models.VodContent.type.in_(["tv", "series"]),
                models.VodContent.category.isnot(None),
            )
            .distinct()
            .all()
        )
        series_cat_map: dict[str, int] = {}
        for idx, (name,) in enumerate(cat_rows, start=1):
            key = name or "Séries"
            series_cat_map[key] = idx

        out: list[dict] = []
        for idx, vod in enumerate(series_list, start=1):
            cat_name = vod.category or "Séries"
            cat_id = series_cat_map.get(cat_name, 0)
            if category_filter not in (None, 0) and cat_id != category_filter:
                continue

            out.append(
                {
                    "num": idx,
                    "name": vod.title,
                    "title": vod.title,
                    "year": "0",
                    "stream_type": "series",
                    "series_id": vod.id,
                    "cover": vod.poster_url,
                    "plot": "",
                    "cast": "",
                    "director": "",
                    "genre": cat_name,
                    "release_date": "",
                    "releaseDate": "",
                    "last_modified": "0",
                    "rating": "0.0",
                    "rating_5based": 0,
                    "backdrop_path": [vod.backdrop_url] if vod.backdrop_url else [],
                    "youtube_trailer": "",
                    "category_id": str(cat_id),
                    "category_ids": [cat_id],
                }
            )
        return _xtream_response(out)

    # get_series_categories: categorias para séries
    if action == "get_series_categories":
        rows = (
            db.query(models.VodContent.category)
            .filter(
                models.VodContent.is_available == True,
                models.VodContent.type.in_(["tv", "series"]),
                models.VodContent.category.isnot(None),
            )
            .distinct()
            .all()
        )
        out: list[dict] = []

        # Mantemos categorias dinâmicas do banco, mas usando o formato típico
        # de painéis Xtream/xui: category_id como string e parent_id=0.
        for idx, (name,) in enumerate(rows, start=1):
            out.append(
                {
                    "category_id": str(idx),
                    "category_name": name or "Séries",
                    "parent_id": 0,
                }
            )
        return _xtream_response(out)

    if action == "get_series_info":
        series_id_raw = request.query_params.get("series_id")
        try:
            series_id = int(series_id_raw) if series_id_raw is not None else None
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid series_id")

        if series_id is None:
            raise HTTPException(status_code=400, detail="series_id is required")

        series = (
            db.query(models.VodContent)
            .filter(
                models.VodContent.id == series_id,
                models.VodContent.type.in_(["tv", "series"]),
                models.VodContent.is_available == True,
            )
            .first()
        )
        if not series:
            raise HTTPException(status_code=404, detail="Series not found")

        episodes_q = db.query(models.Episode).filter(models.Episode.is_available == True)
        # Preferimos associar por vod_id; se não houver, caímos para tmdb_id.
        if series.id is not None:
            episodes_q = episodes_q.filter(models.Episode.vod_id == series.id)
        elif series.tmdb_id is not None:
            episodes_q = episodes_q.filter(models.Episode.tmdb_id == series.tmdb_id)
        episodes = episodes_q.order_by(
            models.Episode.season, models.Episode.episode
        ).all()

        # Agrupa episódios por temporada; metadados (título, capa) já foram
        # enriquecidos na sincronização via TMDB e salvos na tabela Episode.
        seasons_map: dict[int, list[models.Episode]] = {}
        for ep in episodes:
            seasons_map.setdefault(ep.season, []).append(ep)

        seasons_out: list[dict] = []
        for snum, eps in sorted(seasons_map.items()):
            seasons_out.append(
                {
                    "air_date": "",
                    "episode_count": len(eps),
                    "id": str(snum),
                    "name": f"Season {snum}",
                    "season_number": str(snum),
                    "overview": "",
                    "cover": "",
                    "cover_big": "",
                }
            )

        episodes_out: dict[str, list[dict]] = {}
        for snum, eps in sorted(seasons_map.items()):
            key = str(snum)
            eps_list: list[dict] = []
            for ep in eps:
                poster = ep.poster_url
                duration_secs = ep.duration_secs or 0
                try:
                    h = duration_secs // 3600
                    m = (duration_secs % 3600) // 60
                    s = duration_secs % 60
                    duration_str = f"{h:02d}:{m:02d}:{s:02d}"
                except Exception:
                    duration_secs = 0
                    duration_str = "00:00:00"

                eps_list.append(
                    {
                        "id": ep.id,
                        "episode_num": str(ep.episode),
                        "title": ep.title,
                        "container_extension": "mp4",
                        "info": {
                            "movie_image": poster,
                            "releaseDate": "",
                            "youtube_trailer": "",
                            "plot": "",
                            "cast": "",
                            "rating": 0,
                            "rating_5based": 0,
                            "director": "",
                            "duration_secs": duration_secs,
                            "duration": duration_str,
                            "cover_big": poster,
                        },
                        "subtitles": [],
                        "custom_sid": "",
                        "added": str(int(datetime.utcnow().timestamp())),
                        "season": ep.season,
                        "direct_source": ep.stream_url,
                    }
                )
            episodes_out[key] = eps_list

        # Metadados ricos da TMDB já persistidos em VodContent.
        plot = series.overview or ""
        rating = series.vote_average or "0.0"
        try:
            rating_5based = float(series.rating_5based) if series.rating_5based is not None else 0
        except Exception:
            rating_5based = 0
        genres_str = series.genres or ""
        first_air = series.release_date or ""
        cast_str = series.cast or ""
        crew_str = series.director or ""

        # info no formato próximo ao painel de referência
        info = {
            "name": series.title,
            "title": series.title,
            "year": "0",
            "cover": series.poster_url,
            "plot": plot,
            "backdrop_path": [],
            "rating": rating,
            "rating_5based": rating_5based,
            "genre": genres_str,
            "release_date": first_air or None,
            "releaseDate": first_air or None,
            "last_modified": str(int(datetime.utcnow().timestamp())),
            "episode_run_time": str(series.duration_secs or 0),
            "category_id": "0",
            "category_ids": [0],
            "youtube_trailer": "",
            "cast": cast_str,
            "director": crew_str,
        }

        return _xtream_response({"info": info, "seasons": seasons_out, "episodes": episodes_out})

    # get_short_epg: muitos painéis devolvem EPG simplificado por canal.
    # Para compatibilidade básica com apps como IPTV Smarters, retornamos
    # uma lista vazia, pois ainda não temos EPG integrado.
    if action == "get_short_epg":
        return _xtream_response([])

    # Próximas actions: get_series_info, get_vod_info, etc.
    raise HTTPException(status_code=400, detail="Unsupported action yet")


@router.get("/get.php", response_class=PlainTextResponse)
async def get_php(
    request: Request,
    username: str,
    password: str,
    type: str = "m3u",
    output: str = "ts",
    db: Session = Depends(get_db),
):
    """Gera playlist M3U básica com todos os canais disponíveis.

    Muitos apps IPTV usam URLs como:
    http://server/get.php?username=U&password=P&type=m3u&output=ts
    """

    # Gera um nome de arquivo amigável contendo o username, removendo caracteres não alfanuméricos.
    safe_username = "".join(c for c in username if c.isalnum()) or "user"
    filename = f"playlist_{safe_username}.m3u"

    user = _auth_user(username, password, db)
    if not user:
        # Alguns painéis retornam texto vazio ou erro simples; aqui vamos retornar M3U vazio.
        return PlainTextResponse(
            "#EXTM3U\n",
            status_code=200,
            media_type="application/x-mpegurl",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # Só suportamos M3U por enquanto
    if type.lower() != "m3u":
        raise HTTPException(status_code=400, detail="Only type=m3u is supported currently")

    base_url = str(request.base_url).rstrip("/")

    channels = (
        db.query(models.Channel)
        .filter(models.Channel.is_available == True)
        .order_by(models.Channel.id)
        .all()
    )

    lines: list[str] = ["#EXTM3U"]
    for ch in channels:
        # group-title = categoria (se existir)
        group_title = ch.category.name if ch.category else "Canais"
        tvg_logo = ch.logo_url or ""

        # URL que o player vai chamar. No futuro podemos criar um endpoint /live/... que faça proxy/token.
        stream_url = f"{base_url}/live/{username}/{password}/{ch.id}.{output}"

        extinf = (
            f"#EXTINF:-1 tvg-id=\"{ch.id}\" tvg-logo=\"{tvg_logo}\" "
            f"group-title=\"{group_title}\",{ch.name}"
        )
        lines.append(extinf)
        lines.append(stream_url)

    # Também incluímos VOD (filmes) na M3U para compatibilidade com players
    vod_movies = (
        db.query(models.VodContent)
        .filter(
            models.VodContent.is_available == True,
            models.VodContent.type.in_(["movie", "filme"]),
        )
        .order_by(models.VodContent.id)
        .all()
    )

    for vod in vod_movies:
        group_title = vod.category or "Filmes"
        tvg_logo = vod.poster_url or ""

        # Em vez de expor a URL final do CDN, usamos o endpoint /movie/
        # compatível com Xtream, que faz o proxy/stream do conteúdo.
        stream_url = f"{base_url}/movie/{username}/{password}/{vod.id}.mp4"

        extinf = (
            f"#EXTINF:-1 tvg-id=\"vod-{vod.id}\" tvg-logo=\"{tvg_logo}\" "
            f"group-title=\"{group_title}\",{vod.title}"
        )
        lines.append(extinf)
        lines.append(stream_url)

    # Séries: usamos episódios já sincronizados na tabela Episode.
    episodes = (
        db.query(models.Episode)
        .filter(models.Episode.is_available == True)
        .order_by(models.Episode.tmdb_id, models.Episode.season, models.Episode.episode)
        .all()
    )

    for ep in episodes:
        title = ep.title
        logo = ep.poster_url or ""
        group_title = ep.category or "Series"

        # Também mascaramos o link final dos episódios usando /series/...
        ep_url = f"{base_url}/series/{username}/{password}/{ep.id}.mp4"

        extinf = (
            f"#EXTINF:-1 tvg-name=\"{title}\" tvg-logo=\"{logo}\" "
            f"group-title=\"{group_title}\",{title}"
        )
        lines.append(extinf)
        lines.append(ep_url)

    content = "\n".join(lines) + "\n"

    # Força o navegador a baixar a playlist em vez de exibir como texto.
    return PlainTextResponse(
        content,
        media_type="application/x-mpegurl",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/live/{username}/{password}/{stream_id}")
async def live_redirect(
    username: str,
    password: str,
    stream_id: str,
    db: Session = Depends(get_db),
):
    """Endpoint simples de LIVE que só faz redirect para a URL real do canal.

    Isso permite mascarar a URL original e usar o padrão
    /live/USERNAME/PASSWORD/STREAM_ID.ts
    que muitos players IPTV esperam.
    """

    user = _auth_user(username, password, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Alguns players chamam /live/.../ID.ts, então stream_id pode vir com extensão.
    try:
        numeric_id = int(str(stream_id).split(".")[0])
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid stream id")

    ch = db.query(models.Channel).filter(models.Channel.id == numeric_id).first()
    if not ch or not ch.is_available or not ch.stream_url:
        raise HTTPException(status_code=404, detail="Stream not found")

    return RedirectResponse(url=ch.stream_url, status_code=302)


@router.get("/{username}/{password}/{stream_id}")
async def live_redirect_short(
    username: str,
    password: str,
    stream_id: str,
    db: Session = Depends(get_db),
):
    """Versão curta do endpoint de LIVE.

    Alguns apps Xtream chamam diretamente /USERNAME/PASSWORD/STREAM_ID
    (sem o prefixo /live). Este handler reaproveita a mesma lógica
    de live_redirect para manter compatibilidade.
    """

    user = _auth_user(username, password, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    try:
        numeric_id = int(str(stream_id).split(".")[0])
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid stream id")

    ch = db.query(models.Channel).filter(models.Channel.id == numeric_id).first()
    if not ch or not ch.is_available or not ch.stream_url:
        raise HTTPException(status_code=404, detail="Stream not found")

    return RedirectResponse(url=ch.stream_url, status_code=302)


@router.get("/series/{username}/{password}/{stream_id}")
async def series_redirect(
    username: str,
    password: str,
    stream_id: str,
    db: Session = Depends(get_db),
):
    """Endpoint para episódios de séries compatível com Xtream.

    Apps como IPTV Smarters chamam URLs do tipo
    /series/USERNAME/PASSWORD/EPISODE_ID.mp4
    usando o id retornado em get_series_info.
    """

    user = _auth_user(username, password, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # stream_id pode vir como "1234.mp4"; extraímos apenas a parte numérica.
    try:
        numeric_id = int(str(stream_id).split(".")[0])
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid episode id")

    ep = db.query(models.Episode).filter(models.Episode.id == numeric_id).first()
    if not ep or not ep.is_available or not ep.stream_url:
        raise HTTPException(status_code=404, detail="Episode not found")

    # Apenas redireciona para a URL final do episódio.
    return RedirectResponse(url=ep.stream_url, status_code=302)


@router.get("/movie/{username}/{password}/{stream_id}")
async def movie_redirect(
    username: str,
    password: str,
    stream_id: str,
    db: Session = Depends(get_db),
):
    """Endpoint para filmes VOD compatível com Xtream.

    Apps como IPTV Smarters chamam URLs do tipo
    /movie/USERNAME/PASSWORD/MOVIE_ID.mp4
    usando o id retornado nos endpoints de VOD.
    """

    user = _auth_user(username, password, db)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # stream_id pode vir como "1.mp4"; extraímos apenas a parte numérica.
    try:
        numeric_id = int(str(stream_id).split(".")[0])
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid movie id")

    vod = (
        db.query(models.VodContent)
        .filter(
            models.VodContent.id == numeric_id,
            models.VodContent.type.in_(["movie", "filme"]),
            models.VodContent.is_available == True,
        )
        .first()
    )
    if not vod or not vod.stream_url:
        raise HTTPException(status_code=404, detail="Movie not found")

    # Apenas redireciona para a URL final do filme.
    return RedirectResponse(url=vod.stream_url, status_code=302)
