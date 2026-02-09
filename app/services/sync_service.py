from typing import Iterable, List, Dict, Optional
from datetime import datetime
import asyncio
import logging

from sqlalchemy.orm import Session
from google.cloud import firestore
from google.oauth2 import service_account
import httpx
import os

from .. import models
from ..database import SessionLocal


# Usamos o logger do uvicorn para que as mensagens apareçam no terminal padrão
logger = logging.getLogger("uvicorn.error")


def _get_firestore_client() -> firestore.Client:
    """Retorna um cliente Firestore usando o arquivo de credenciais local.

    Se o arquivo não existir, cai no comportamento padrão do SDK
    (Application Default Credentials), para não quebrar em outros ambientes.
    """
    # Caminho direto informado pelo usuário
    credentials_path = r"C:\Users\luizd\Downloads\firebase-service-account.json"

    if os.path.exists(credentials_path):
        creds = service_account.Credentials.from_service_account_file(credentials_path)
        # Usa o project_id embutido no JSON
        return firestore.Client(project=creds.project_id, credentials=creds)

    # Fallback: usa ADC se o arquivo não estiver presente
    return firestore.Client()


# Estado simples de progresso de sincronização de VOD em memória.
vod_sync_progress: Dict = {
    "running": False,
    "current": 0,
    "total": 0,
    "tmdb_attempts": 0,
    "tmdb_success": 0,
    "step": "idle",
    "error": None,
}


def sync_channels_and_categories_from_firestore(db: Session) -> Dict:
    """Sincroniza categorias e canais do Firestore para o SQLite.

    Coleções/Docs esperados (mesmo padrão do app Android):
      - config/channel_categories  (campo: categoriesData)
      - config/channels           (campo: channelsData)
    """

    client = _get_firestore_client()

    # --- Categorias ---
    cat_doc = client.collection("config").document("channel_categories").get()
    categories_data = cat_doc.to_dict() or {}
    raw_categories: List[Dict] = categories_data.get("categoriesData") or []

    external_id_to_category_id: Dict[str, int] = {}
    cat_created = 0
    cat_updated = 0

    for item in raw_categories:
        if not isinstance(item, Dict):
            continue
        ext_id = item.get("id")
        if not ext_id:
            continue
        name = item.get("name") or ext_id
        is_adult = bool(
            item.get("isAdult")
            or item.get("adult")
            or False
        )

        cat = (
            db.query(models.ChannelCategory)
            .filter(models.ChannelCategory.external_id == ext_id)
            .first()
        )
        if not cat:
            cat = models.ChannelCategory(
                external_id=ext_id,
                name=name,
                is_adult=is_adult,
            )
            db.add(cat)
            db.flush()  # Para gerar ID
            cat_created += 1
        else:
            cat.name = name
            cat.is_adult = is_adult
            cat_updated += 1
        external_id_to_category_id[ext_id] = cat.id

    # --- Canais ---
    ch_doc = client.collection("config").document("channels").get()
    channels_data = ch_doc.to_dict() or {}
    raw_channels: Iterable[Dict] = channels_data.get("channelsData") or []

    ch_created = 0
    ch_updated = 0

    for item in raw_channels:
        if not isinstance(item, Dict):
            continue
        ext_id = item.get("id")
        if not ext_id:
            continue

        name = item.get("name") or ext_id
        logo_url = item.get("logoUrl") or ""
        category_id_ext = item.get("categoryId") or ""
        category_name = item.get("categoryName") or ""
        is_premium = bool(
            item.get("isPremium")
            or item.get("premium")
            or False
        )
        is_available = bool(
            item.get("isAvailable")
            or item.get("available")
            or True
        )
        is_adult = bool(
            item.get("isAdult")
            or item.get("adult")
            or False
        )

        # Campo de streams: pode ser lista ou string com separadores
        stream_field = (
            item.get("streamUrls")
            or item.get("urls")
            or item.get("streams")
            or item.get("stream")
        )
        stream_urls: List[str] = []
        if isinstance(stream_field, List):
            stream_urls = [
                s.strip() for s in stream_field if isinstance(s, str) and s.strip()
            ]
        elif isinstance(stream_field, str):
            parts = [p.strip() for p in stream_field.split("\n")]
            stream_urls = [p for p in parts if p]

        primary_url = stream_urls[0] if stream_urls else ""

        # Garante categoria correspondente se vier só categoryName
        cat_fk_id = None
        if category_id_ext and category_id_ext in external_id_to_category_id:
            cat_fk_id = external_id_to_category_id[category_id_ext]
        elif category_name:
            # tenta achar categoria pelo nome se não tiver external_id
            cat = (
                db.query(models.ChannelCategory)
                .filter(models.ChannelCategory.name == category_name)
                .first()
            )
            if cat:
                cat_fk_id = cat.id

        ch = (
            db.query(models.Channel)
            .filter(models.Channel.external_id == ext_id)
            .first()
        )
        if not ch:
            ch = models.Channel(
                external_id=ext_id,
                name=name,
                logo_url=logo_url,
                stream_url=primary_url,
                category_id=cat_fk_id,
                is_premium=is_premium,
                is_adult=is_adult,
                is_available=is_available,
            )
            db.add(ch)
            ch_created += 1
        else:
            ch.name = name
            ch.logo_url = logo_url
            ch.stream_url = primary_url or ch.stream_url
            ch.category_id = cat_fk_id
            ch.is_premium = is_premium
            ch.is_adult = is_adult
            ch.is_available = is_available
            ch_updated += 1

    db.commit()

    logger.info(
        "[sync_channels] done - categories_created=%d categories_updated=%d channels_created=%d channels_updated=%d",
        cat_created,
        cat_updated,
        ch_created,
        ch_updated,
    )

    return {
        "categories_created": cat_created,
        "categories_updated": cat_updated,
        "channels_created": ch_created,
        "channels_updated": ch_updated,
    }


async def _sync_episodes_from_xtream_origin(
    db: Session,
    host: str,
    username: str,
    password: str,
    track_progress: bool,
    fetch_tmdb_details: bool,
) -> Dict:
    """Sincroniza episódios de séries copiando do painel Xtream de origem.

    Usa o endpoint padrão do Xtream Codes:
      - action=get_series_info&series_id=...

    Para cada série em VodContent (type tv/series), tenta recuperar o series_id a
    partir de external_id (formato "series:{id}") e popula a tabela Episode com
    os episódios retornados.
    """

    base = host.strip()
    if not base:
        return {"error": "origin host is blank (episodes)"}
    if "/player_api.php" not in base:
        base = base.rstrip("/") + "/player_api.php"

    params_base = {"username": username, "password": password}

    logger.info("[sync_episodes_xtream_origin] starting episodes sync from %s", base)

    # Todas as séries conhecidas no VOD (independente de tmdb_id neste modo)
    vod_series = (
        db.query(models.VodContent)
        .filter(
            models.VodContent.is_available == True,
            models.VodContent.type.in_(["tv", "series"]),
        )
        .all()
    )

    total_series = len(vod_series)
    created = 0
    deleted = 0

    if track_progress:
        vod_sync_progress.update(
            {
                "step": "sync_episodes_xtream_origin",
                "episodes_series_total": total_series,
                "episodes_series_current": 0,
            }
        )

    async with httpx.AsyncClient(timeout=40) as http:
        for idx, vod in enumerate(vod_series, start=1):
            # Extrai series_id do external_id no formato "series:{id}"
            series_id = None
            if vod.external_id and vod.external_id.startswith("series:"):
                series_id = vod.external_id.split(":", 1)[1]

            if not series_id:
                logger.warning(
                    "[sync_episodes_xtream_origin] skipping series without external_id series: vod_id=%s title=%s",
                    vod.id,
                    vod.title,
                )
                continue

            try:
                logger.info(
                    "[sync_episodes_xtream_origin] fetching get_series_info for series_id=%s title=%s",
                    series_id,
                    vod.title,
                )
                r = await http.get(
                    base,
                    params={**params_base, "action": "get_series_info", "series_id": series_id},
                )
                r.raise_for_status()
                payload = r.json() or {}
            except Exception:  # noqa: BLE001
                logger.exception(
                    "[sync_episodes_xtream_origin] get_series_info failed for series_id=%s title=%s",
                    series_id,
                    vod.title,
                )
                continue

            episodes_obj = payload.get("episodes") or {}
            if not isinstance(episodes_obj, Dict):
                logger.error(
                    "[sync_episodes_xtream_origin] episodes payload is not a dict for series_id=%s type=%r",
                    series_id,
                    type(episodes_obj),
                )
                continue

            # Remove episódios antigos desta série
            deleted += (
                db.query(models.Episode)
                .filter(models.Episode.vod_id == vod.id)
                .delete(synchronize_session=False)
            )

            base_title = vod.title
            base_category = vod.category
            base_poster = vod.poster_url

            for season_key, eps_list in episodes_obj.items():
                try:
                    season_num = int(season_key)
                except (TypeError, ValueError):
                    continue

                if not isinstance(eps_list, List):
                    logger.warning(
                        "[sync_episodes_xtream_origin] episodes list for series_id=%s season=%s is not a list (type=%r)",
                        series_id,
                        season_key,
                        type(eps_list),
                    )
                    continue

                for ep in eps_list:
                    if not isinstance(ep, Dict):
                        continue

                    # Número do episódio
                    ep_num = ep.get("episode_num") or ep.get("episode_number") or ep.get("id")
                    try:
                        ep_num_int = int(ep_num)
                    except (TypeError, ValueError):
                        ep_num_int = 0

                    # Título
                    title = ep.get("title") or ep.get("name") or f"{base_title} S{season_num:02d}E{ep_num_int:02d}"

                    # Poster
                    poster = (
                        ep.get("movie_image")
                        or ep.get("stream_icon")
                        or base_poster
                    )

                    # Duração (alguns painéis retornam duration_secs ou duration)
                    duration_secs = ep.get("duration_secs") or ep.get("duration") or None
                    try:
                        if duration_secs is not None:
                            duration_secs = int(duration_secs)
                    except Exception:  # noqa: BLE001
                        duration_secs = None

                    # Stream id + extensão/container
                    stream_id = ep.get("id") or ep.get("stream_id") or ep.get("episode_id")
                    container_ext = ep.get("container_extension") or "mp4"
                    direct_source = ep.get("direct_source")
                    if not direct_source and stream_id is not None:
                        # Padrão Xtream para séries
                        direct_source = (
                            f"{host.rstrip('/')}/series/{username}/{password}/{stream_id}.{container_ext}"
                        )

                    episode = models.Episode(
                        vod_id=vod.id,
                        tmdb_id=vod.tmdb_id or 0,
                        season=season_num,
                        episode=ep_num_int,
                        title=title,
                        category=base_category,
                        poster_url=poster,
                        duration_secs=duration_secs,
                        stream_url=direct_source,
                        is_available=True,
                    )
                    db.add(episode)
                    created += 1

            if track_progress:
                vod_sync_progress["episodes_series_current"] = idx

    db.commit()

    logger.info(
        "[sync_episodes_xtream_origin] done - episodes_created=%d episodes_deleted=%d",
        created,
        deleted,
    )

    return {"episodes_created": created, "episodes_deleted": deleted}


async def _sync_vod_from_xtream_origin(
    db: Session,
    host: str,
    username: str,
    password: str,
    track_progress: bool,
    fetch_tmdb: bool,
    only_type: Optional[str],
) -> Dict:
    """Sincroniza VOD (filmes/séries) copiando do painel Xtream de origem.

    Usa os endpoints padrão do Xtream Codes:
      - action=get_vod_streams   -> filmes
      - action=get_series        -> séries

    Copia o catálogo para a tabela VodContent. Episódios de séries continuam sendo
    gerados pela rotina existente de disponibilidade externa.
    """

    # Normaliza base do player_api.php
    base = host.strip()
    if not base:
        return {"error": "origin host is blank"}
    if "/player_api.php" not in base:
        base = base.rstrip("/") + "/player_api.php"

    logger.info(
        "[sync_vod_xtream_origin] starting sync from %s (user=%s)",
        base,
        username,
    )

    params_base = {
        "username": username,
        "password": password,
    }

    async with httpx.AsyncClient(timeout=40) as http:
        movies_data: List[Dict] = []
        series_data: List[Dict] = []

        # --- Filmes ---
        if only_type in (None, "movies"):
            try:
                logger.info("[sync_vod_xtream_origin] fetching get_vod_streams")
                r = await http.get(base, params={**params_base, "action": "get_vod_streams"})
                r.raise_for_status()
                payload = r.json()
                if isinstance(payload, List):
                    movies_data = [x for x in payload if isinstance(x, Dict)]
                else:
                    logger.error("[sync_vod_xtream_origin] get_vod_streams payload is not a list: %r", type(payload))
            except Exception:  # noqa: BLE001
                logger.exception("[sync_vod_xtream_origin] get_vod_streams failed")
                return {"error": "get_vod_streams failed"}

        # --- Séries ---
        if only_type in (None, "series"):
            try:
                logger.info("[sync_vod_xtream_origin] fetching get_series")
                r = await http.get(base, params={**params_base, "action": "get_series"})
                r.raise_for_status()
                payload = r.json()
                if isinstance(payload, List):
                    series_data = [x for x in payload if isinstance(x, Dict)]
                else:
                    logger.error("[sync_vod_xtream_origin] get_series payload is not a list: %r", type(payload))
            except Exception:  # noqa: BLE001
                logger.exception("[sync_vod_xtream_origin] get_series failed")
                return {"error": "get_series failed"}

    total_items = len(movies_data) + len(series_data)
    created = 0
    updated = 0

    if track_progress:
        vod_sync_progress.update(
            {
                "running": True,
                "current": 0,
                "total": total_items,
                "tmdb_attempts": 0,
                "tmdb_success": 0,
                "step": "processing_xtream_origin",
                "error": None,
            }
        )

    logger.info(
        "[sync_vod_xtream_origin] loaded movies=%d series=%d (total=%d)",
        len(movies_data),
        len(series_data),
        total_items,
    )

    # Helper para upsert de VodContent a partir de um dict genérico
    def upsert_vod(
        *,
        external_id: Optional[str],
        title: str,
        vtype: str,
        poster_url: Optional[str],
        backdrop_url: Optional[str],
        category: Optional[str],
        stream_url: Optional[str],
    ) -> None:
        nonlocal created, updated

        if not title:
            return

        q = db.query(models.VodContent)
        vod = None
        if external_id:
            vod = q.filter(models.VodContent.external_id == external_id).first()

        if not vod:
            vod = models.VodContent(
                external_id=external_id,
                tmdb_id=None,
                title=title,
                type=vtype,
                poster_url=poster_url,
                backdrop_url=backdrop_url,
                category=category,
                stream_url=stream_url,
                is_available=True,
            )
            db.add(vod)
            created += 1
        else:
            vod.title = title
            vod.type = vtype
            vod.poster_url = poster_url or vod.poster_url
            vod.backdrop_url = backdrop_url or vod.backdrop_url
            vod.category = category or vod.category
            vod.stream_url = stream_url or vod.stream_url
            vod.is_available = True
            updated += 1

    # Processa filmes
    for idx, item in enumerate(movies_data, start=1):
        try:
            stream_id = item.get("stream_id") or item.get("id")
            ext_id = str(stream_id) if stream_id is not None else None
            title = item.get("name") or item.get("title") or ""
            poster = item.get("stream_icon") or None
            category_id = item.get("category_id")
            # Tenta usar direct_source se existir; caso contrário, monta URL padrão Xtream
            direct_source = item.get("direct_source") or None
            if not direct_source and stream_id is not None:
                # Padrão típico: /movie/username/password/stream_id.ext
                container_ext = item.get("container_extension") or "mp4"
                direct_source = f"{host.rstrip('/')}/movie/{username}/{password}/{stream_id}.{container_ext}"

            upsert_vod(
                external_id=f"movie:{ext_id}" if ext_id else None,
                title=title,
                vtype="movie",
                poster_url=poster,
                backdrop_url=None,
                category=str(category_id) if category_id is not None else None,
                stream_url=direct_source,
            )
        except Exception:  # noqa: BLE001
            logger.exception("[sync_vod_xtream_origin] failed to process movie item: %r", item)

        if track_progress and (idx % 50 == 0 or idx == total_items):
            vod_sync_progress["current"] = idx

    # Processa séries (apenas cadastro básico; episódios continuam via disponibilidade externa)
    offset = len(movies_data)
    for i, item in enumerate(series_data, start=1):
        idx = offset + i
        try:
            series_id = item.get("series_id") or item.get("id")
            ext_id = str(series_id) if series_id is not None else None
            title = item.get("name") or item.get("title") or ""
            poster = item.get("cover") or item.get("cover_big") or None
            genre = item.get("genre") or None

            upsert_vod(
                external_id=f"series:{ext_id}" if ext_id else None,
                title=title,
                vtype="series",
                poster_url=poster,
                backdrop_url=None,
                category=genre,
                stream_url=None,
            )
        except Exception:  # noqa: BLE001
            logger.exception("[sync_vod_xtream_origin] failed to process series item: %r", item)

        if track_progress and (idx % 50 == 0 or idx == total_items):
            vod_sync_progress["current"] = idx

    db.commit()

    logger.info(
        "[sync_vod_xtream_origin] done - vod_created=%d vod_updated=%d total=%d",
        created,
        updated,
        total_items,
    )

    return {
        "vod_created": created,
        "vod_updated": updated,
        "vod_total_items": total_items,
        "source": "xtream_origin",
    }


async def sync_vod_from_contents_json(
    db: Session,
    track_progress: bool = False,
    fetch_tmdb: bool = True,
    only_type: Optional[str] = None,
) -> Dict:
    """Sincroniza conteúdos VOD (filmes/séries).

    Modo configurável via PanelSettings.sync_mode:
      - "contents_json" (legado): lê Firestore app_config/contents e baixa o JSON.
      - "xtream_origin": usa painel Xtream de origem configurado no PanelSettings.
    """

    # Lê modo de sync e, se necessário, as credenciais do painel de origem.
    settings = db.query(models.PanelSettings).first()
    sync_mode = (settings.sync_mode if settings and settings.sync_mode else "contents_json").strip()

    if sync_mode == "xtream_origin":
        origin_host = (settings.origin_host or "").strip()
        origin_username = (settings.origin_username or "").strip()
        origin_password = (settings.origin_password or "").strip()
        if not origin_host or not origin_username or not origin_password:
            return {"error": "origin_host/origin_username/origin_password not configured for xtream_origin"}

        # Aqui delegamos para a rotina específica que irá copiar o catálogo
        # completo do painel Xtream de origem.
        return await _sync_vod_from_xtream_origin(
            db=db,
            host=origin_host,
            username=origin_username,
            password=origin_password,
            track_progress=track_progress,
            fetch_tmdb=fetch_tmdb,
            only_type=only_type,
        )

    # Modo legado: contents.json a partir do Firestore
    client = _get_firestore_client()
    url = _resolve_contents_url_from_firestore(client)
    if not url:
        return {"error": "No contents URL configured in Firestore"}

    logger.info("[sync_vod] starting fetch of contents.json")
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(url)
        resp.raise_for_status()
        items = resp.json()

    if not isinstance(items, List):
        return {"error": "Contents JSON is not a list"}

    created = 0
    updated = 0
    total_items = len(items)
    tmdb_attempts = 0
    tmdb_success = 0

    logger.info("[sync_vod] loaded %d items from contents.json", total_items)

    if track_progress:
        vod_sync_progress.update(
            {
                "running": True,
                "current": 0,
                "total": total_items,
                "tmdb_attempts": 0,
                "tmdb_success": 0,
                "step": "processing_contents",
                "error": None,
            }
        )

    # Primeiro, identificamos quais tmdb_ids precisam de dados TMDB
    # (poster, backdrop e metadados ricos) e, opcionalmente, buscamos
    # essas informações em paralelo na TMDB.
    tmdb_results: Dict[int, Dict] = {}

    if fetch_tmdb:
        tmdb_jobs: Dict[tuple[int, str], None] = {}

        logger.info("[sync_vod] scanning items to build TMDB jobs (incremental)")

        for item in items:
            if not isinstance(item, Dict):
                continue
            tmdb_id = item.get("tmdbId") or item.get("tmdb_id")
            if not tmdb_id:
                continue
            ctype = (item.get("type") or "").lower() or "movie"
            # Filtra por tipo, se solicitado.
            if only_type == "movies" and ctype not in {"movie", "filme"}:
                continue
            if only_type == "series" and ctype not in {"tv", "series"}:
                continue
            poster_url = item.get("poster") or item.get("posterUrl")
            backdrop_url = item.get("backdrop") or item.get("backdropUrl")
            # Se o próprio JSON já traz poster/backdrop completos, ainda assim podemos
            # querer metadados (overview, rating etc.), então não pulamos aqui.

            # Evita rebuscar posters na TMDB se o VOD já tem capas gravadas no banco
            # de uma sync anterior.
            try:
                tid_int = int(tmdb_id)
            except (TypeError, ValueError):
                tid_int = None
            if tid_int is not None:
                existing = (
                    db.query(models.VodContent)
                    .filter(models.VodContent.tmdb_id == tid_int)
                    .first()
                )
                # Se já temos pelo menos uma capa (poster ou backdrop) no banco,
                # assumimos que não precisamos mais chamar a TMDB para esse título.
                if existing and (existing.poster_url or existing.backdrop_url):
                    continue

            tmdb_jobs[(int(tmdb_id), "movie" if ctype in {"movie", "filme"} else "tv")] = None

        logger.info("[sync_vod] TMDB jobs scheduled: %d", len(tmdb_jobs))

        if tmdb_jobs:
            # Até 25 requisições TMDB em paralelo para acelerar o preenchimento de posters.
            sem = asyncio.Semaphore(50)

            if track_progress:
                vod_sync_progress["step"] = "fetch_tmdb"
                vod_sync_progress["tmdb_total_jobs"] = len(tmdb_jobs)

            async def fetch_tmdb_task(tid: int, tmdb_type: str):
                nonlocal tmdb_attempts, tmdb_success
                api_key = "5173c8066086fe7c406c959303bd6cbf"
                url_tmdb = f"https://api.themoviedb.org/3/{tmdb_type}/{tid}"
                async with sem:
                    try:
                        tmdb_attempts += 1
                        async with httpx.AsyncClient(timeout=20) as tmdb_http:
                            # Pedimos também "credits" para ter elenco/direção completos
                            r = await tmdb_http.get(
                                url_tmdb,
                                params={
                                    "api_key": api_key,
                                    "language": "pt-BR",
                                    "append_to_response": "credits",
                                },
                            )
                            r.raise_for_status()
                            tdata = r.json() or {}
                        poster_path = tdata.get("poster_path")
                        backdrop_path = tdata.get("backdrop_path")
                        poster = (
                            f"https://image.tmdb.org/t/p/w300{poster_path}"
                            if poster_path
                            else None
                        )
                        backdrop = (
                            f"https://image.tmdb.org/t/p/w780{backdrop_path}"
                            if backdrop_path
                            else None
                        )

                        overview = tdata.get("overview") or ""
                        vote = tdata.get("vote_average") or 0
                        try:
                            rating_str = f"{float(vote):.1f}"
                            rating_5 = f"{round(float(vote) / 2, 1):.1f}"
                        except Exception:
                            rating_str = "0.0"
                            rating_5 = "0.0"

                        # Datas: filmes usam release_date, séries usam first_air_date
                        release_date = (
                            tdata.get("release_date")
                            or tdata.get("first_air_date")
                            or ""
                        )

                        # Gêneros como string única
                        genres_list = tdata.get("genres") or []
                        genres_str = ""
                        if isinstance(genres_list, List):
                            genres_str = ", ".join(
                                [g.get("name", "") for g in genres_list if g.get("name")]
                            )

                        # Duração: runtime (filmes) ou primeiro de episode_run_time (séries)
                        runtime = tdata.get("runtime") or 0
                        if not runtime and isinstance(tdata.get("episode_run_time"), List):
                            rt_list = tdata.get("episode_run_time") or []
                            runtime = rt_list[0] if rt_list else 0
                        try:
                            duration_secs = int(runtime) * 60
                        except Exception:
                            duration_secs = 0

                        # Créditos: cast e diretor(es)
                        credits = (
                            tdata.get("credits") or {}
                            if isinstance(tdata.get("credits"), Dict)
                            else {}
                        )
                        cast_list = credits.get("cast") or []
                        crew_list = credits.get("crew") or []
                        cast_str = ""
                        director_str = ""
                        if isinstance(cast_list, List) and cast_list:
                            cast_str = ", ".join(
                                [c.get("name", "") for c in cast_list[:10] if c.get("name")]
                            )
                        if isinstance(crew_list, List):
                            directors = [
                                m.get("name", "")
                                for m in crew_list
                                if m.get("job") == "Director" and m.get("name")
                            ]
                            if directors:
                                director_str = ", ".join(directors)

                        tmdb_results[tid] = {
                            "poster": poster,
                            "backdrop": backdrop,
                            "overview": overview,
                            "vote_average": rating_str,
                            "rating_5based": rating_5,
                            "release_date": release_date,
                            "genres": genres_str,
                            "cast": cast_str,
                            "director": director_str,
                            "duration_secs": duration_secs,
                        }
                        tmdb_success += 1
                        if track_progress:
                            vod_sync_progress["tmdb_attempts"] = tmdb_attempts
                            vod_sync_progress["tmdb_success"] = tmdb_success
                    except Exception:
                        # Segue sem dados adicionais para esse título.
                        tmdb_results[tid] = {}

            await asyncio.gather(
                *(fetch_tmdb_task(tid, ttype) for (tid, ttype) in tmdb_jobs.keys())
            )

        # Ao terminar a fase TMDB, voltamos a marcar a etapa como processamento de conteúdos.
        if track_progress:
            vod_sync_progress["step"] = "processing_contents"

    # Agora processamos os itens sequencialmente, aplicando posters já buscados (se houver).
    logger.info("[sync_vod] applying items to DB (total=%d)", total_items)
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, Dict):
            continue

        ext_id = str(item.get("id") or "") or None
        tmdb_id = item.get("tmdbId") or item.get("tmdb_id")
        title = item.get("title") or item.get("name")
        if not title:
            continue
        ctype = (item.get("type") or "").lower() or "movie"
        poster_url = item.get("poster") or item.get("posterUrl")
        backdrop_url = item.get("backdrop") or item.get("backdropUrl")
        # Categoria básica usada para agrupar VOD no painel/Xtream.
        # Preferimos o primeiro item de "genres" (lista), depois "category" ou "genre" simples.
        category = item.get("category") or item.get("genre")
        genres = item.get("genres")
        if (not category) and isinstance(genres, List) and genres:
            category = genres[0]
        stream_url = (
            item.get("streamUrl")
            or item.get("fileUrl")
            or item.get("url")
            or item.get("iframeUrl")
        )
        # Para filmes VOD, se não vier URL explícita, usamos o padrão do CDN
        # https://secure.webcontent03.fun/movie/{tmdb_id}.mp4?token=...
        if not stream_url and ctype in {"movie", "filme"} and tmdb_id:
            stream_url = (
                f"https://secure.webcontent03.fun/movie/{tmdb_id}.mp4"
                "?token=iptv1221908123kldkhfoithmvssjiruifhbjhfugynnd"
            )
        is_available = bool(item.get("isAvailable", True))

        vod = None
        if tmdb_id is not None:
            vod = (
                db.query(models.VodContent)
                .filter(models.VodContent.tmdb_id == tmdb_id)
                .first()
            )
        if not vod and ext_id:
            vod = (
                db.query(models.VodContent)
                .filter(models.VodContent.external_id == ext_id)
                .first()
            )

        # Se temos tmdb_id e resultados TMDB, aplicamos tanto poster/backdrop
        # quanto metadados ricos no VOD.
        tmdb_meta_for_item: Optional[Dict] = None
        if tmdb_id:
            try:
                tid_int = int(tmdb_id)
            except (TypeError, ValueError):
                tid_int = None
            if tid_int is not None and tid_int in tmdb_results:
                tmdb_meta_for_item = tmdb_results.get(tid_int) or {}
                poster_fetched = tmdb_meta_for_item.get("poster")
                backdrop_fetched = tmdb_meta_for_item.get("backdrop")
                if poster_fetched and not poster_url:
                    poster_url = poster_fetched
                if backdrop_fetched and not backdrop_url:
                    backdrop_url = backdrop_fetched

        # Campos de metadados TMDB opcionais
        overview_val: Optional[str] = None
        vote_avg_val: Optional[str] = None
        rating_5_val: Optional[str] = None
        release_date_val: Optional[str] = None
        genres_val: Optional[str] = None
        cast_val: Optional[str] = None
        director_val: Optional[str] = None
        duration_secs_val: Optional[int] = None

        if tmdb_meta_for_item:
            overview_val = tmdb_meta_for_item.get("overview") or None
            vote_avg_val = tmdb_meta_for_item.get("vote_average") or None
            rating_5_val = tmdb_meta_for_item.get("rating_5based") or None
            release_date_val = tmdb_meta_for_item.get("release_date") or None
            genres_val = tmdb_meta_for_item.get("genres") or None
            cast_val = tmdb_meta_for_item.get("cast") or None
            director_val = tmdb_meta_for_item.get("director") or None
            duration_secs_val = tmdb_meta_for_item.get("duration_secs") or None

        if not vod:
            vod = models.VodContent(
                external_id=ext_id,
                tmdb_id=tmdb_id,
                title=title,
                type=ctype,
                poster_url=poster_url,
                backdrop_url=backdrop_url,
                category=category,
                stream_url=stream_url,
                is_available=is_available,
                overview=overview_val,
                vote_average=vote_avg_val,
                rating_5based=rating_5_val,
                release_date=release_date_val,
                genres=genres_val,
                cast=cast_val,
                director=director_val,
                duration_secs=duration_secs_val,
            )
            db.add(vod)
            created += 1
        else:
            vod.title = title
            vod.type = ctype
            vod.poster_url = poster_url
            vod.backdrop_url = backdrop_url
            vod.category = category
            vod.stream_url = stream_url or vod.stream_url
            vod.is_available = is_available
            # Apenas sobrescreve metadados se vierem da TMDB nesta sync
            if overview_val is not None:
                vod.overview = overview_val
            if vote_avg_val is not None:
                vod.vote_average = vote_avg_val
            if rating_5_val is not None:
                vod.rating_5based = rating_5_val
            if release_date_val is not None:
                vod.release_date = release_date_val
            if genres_val is not None:
                vod.genres = genres_val
            if cast_val is not None:
                vod.cast = cast_val
            if director_val is not None:
                vod.director = director_val
            if duration_secs_val is not None:
                vod.duration_secs = duration_secs_val
            updated += 1

        # Atualiza progresso em lotes para evitar excesso de updates (por ex., 50 em 50).
        if track_progress and (idx % 50 == 0 or idx == total_items):
            vod_sync_progress["current"] = idx
            vod_sync_progress["tmdb_attempts"] = tmdb_attempts
            vod_sync_progress["tmdb_success"] = tmdb_success

    db.commit()

    return {
        "vod_created": created,
        "vod_updated": updated,
        "vod_total_items": total_items,
        "tmdb_poster_attempts": tmdb_attempts,
        "tmdb_poster_success": tmdb_success,
    }


async def sync_vod_posters_only(
    db: Session,
    track_progress: bool = False,
) -> Dict:
    """Atualiza apenas posters/backdrops de VOD existentes usando TMDB.

    Não lê Firestore nem contents.json. Apenas consulta a tabela VodContent,
    encontra registros com tmdb_id preenchido e poster/backdrop ausentes e
    chama a TMDB para preencher as capas e alguns metadados básicos.
    """

    vods = (
        db.query(models.VodContent)
        .filter(
            models.VodContent.tmdb_id.isnot(None),
            (models.VodContent.poster_url.is_(None))
            | (models.VodContent.backdrop_url.is_(None)),
        )
        .all()
    )

    total_items = len(vods)
    if total_items == 0:
        return {
            "vod_total_items": 0,
            "tmdb_poster_attempts": 0,
            "tmdb_poster_success": 0,
            "updated": 0,
        }

    logger.info("[sync_vod_posters_only] found %d VODs without full posters", total_items)

    if track_progress:
        vod_sync_progress.update(
            {
                "running": True,
                "current": 0,
                "total": total_items,
                "tmdb_attempts": 0,
                "tmdb_success": 0,
                "step": "fetch_tmdb_posters_only",
                "error": None,
            }
        )

    tmdb_jobs: Dict[tuple[int, str], models.VodContent] = {}
    for vod in vods:
        if not vod.tmdb_id:
            continue
        tmdb_type = "movie" if vod.type in {"movie", "filme"} else "tv"
        tmdb_jobs[(int(vod.tmdb_id), tmdb_type)] = vod

    if not tmdb_jobs:
        return {
            "vod_total_items": total_items,
            "tmdb_poster_attempts": 0,
            "tmdb_poster_success": 0,
            "updated": 0,
        }

    logger.info("[sync_vod_posters_only] TMDB jobs scheduled: %d", len(tmdb_jobs))

    sem = asyncio.Semaphore(50)
    tmdb_attempts = 0
    tmdb_success = 0
    updated = 0

    async def fetch_tmdb_for_vod(tid: int, tmdb_type: str, vod_obj: models.VodContent):
        nonlocal tmdb_attempts, tmdb_success, updated
        api_key = "5173c8066086fe7c406c959303bd6cbf"
        url_tmdb = f"https://api.themoviedb.org/3/{tmdb_type}/{tid}"
        async with sem:
            try:
                tmdb_attempts += 1
                async with httpx.AsyncClient(timeout=20) as tmdb_http:
                    r = await tmdb_http.get(
                        url_tmdb,
                        params={
                            "api_key": api_key,
                            "language": "pt-BR",
                        },
                    )
                    r.raise_for_status()
                    tdata = r.json() or {}

                poster_path = tdata.get("poster_path")
                backdrop_path = tdata.get("backdrop_path")
                poster = (
                    f"https://image.tmdb.org/t/p/w300{poster_path}"
                    if poster_path
                    else None
                )
                backdrop = (
                    f"https://image.tmdb.org/t/p/w780{backdrop_path}"
                    if backdrop_path
                    else None
                )

                if poster and not vod_obj.poster_url:
                    vod_obj.poster_url = poster
                if backdrop and not vod_obj.backdrop_url:
                    vod_obj.backdrop_url = backdrop

                # Metadados básicos opcionais
                overview = tdata.get("overview") or None
                vote = tdata.get("vote_average") or 0
                try:
                    rating_str = f"{float(vote):.1f}"
                    rating_5 = f"{round(float(vote) / 2, 1):.1f}"
                except Exception:
                    rating_str = None
                    rating_5 = None

                release_date = (
                    tdata.get("release_date")
                    or tdata.get("first_air_date")
                    or None
                )

                genres_list = tdata.get("genres") or []
                genres_str = None
                if isinstance(genres_list, List):
                    genres_str = ", ".join(
                        [g.get("name", "") for g in genres_list if g.get("name")]
                    )

                if overview is not None:
                    vod_obj.overview = overview
                if rating_str is not None:
                    vod_obj.vote_average = rating_str
                if rating_5 is not None:
                    vod_obj.rating_5based = rating_5
                if release_date is not None:
                    vod_obj.release_date = release_date
                if genres_str is not None:
                    vod_obj.genres = genres_str

                tmdb_success += 1
                updated += 1
                if track_progress:
                    vod_sync_progress["tmdb_attempts"] = tmdb_attempts
                    vod_sync_progress["tmdb_success"] = tmdb_success
            except Exception:
                # Em caso de falha para este título, apenas seguir para o próximo.
                return

    await asyncio.gather(
        *(fetch_tmdb_for_vod(tid, ttype, vod) for (tid, ttype), vod in tmdb_jobs.items())
    )

    db.commit()

    if track_progress:
        vod_sync_progress["running"] = False

    return {
        "vod_total_items": total_items,
        "tmdb_poster_attempts": tmdb_attempts,
        "tmdb_poster_success": tmdb_success,
        "updated": updated,
    }


async def sync_series_episodes_from_availability(
    db: Session,
    track_progress: bool = False,
    fetch_tmdb_details: bool = True,
) -> Dict:
    """Sincroniza episódios de séries.

    Comportamento depende de PanelSettings.sync_mode:
      - "contents_json" (legado): usa endpoint externo de disponibilidade.
      - "xtream_origin": usa get_series_info do painel Xtream de origem.
    """

    settings = db.query(models.PanelSettings).first()
    sync_mode = (settings.sync_mode if settings and settings.sync_mode else "contents_json").strip()

    if sync_mode == "xtream_origin":
        origin_host = (settings.origin_host or "").strip()
        origin_username = (settings.origin_username or "").strip()
        origin_password = (settings.origin_password or "").strip()
        if not origin_host or not origin_username or not origin_password:
            return {
                "error": "origin_host/origin_username/origin_password not configured for xtream_origin (episodes)",
            }

        return await _sync_episodes_from_xtream_origin(
            db=db,
            host=origin_host,
            username=origin_username,
            password=origin_password,
            track_progress=track_progress,
            fetch_tmdb_details=fetch_tmdb_details,
        )

    # --- Modo legado: disponibilidade externa ---

    availability_url = "https://getalltvavailability-hlrg3wz4pq-uc.a.run.app/"

    logger.info("[sync_episodes] fetching availability from %s", availability_url)
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.get(availability_url)
        resp.raise_for_status()
        data = resp.json() or {}

    if not isinstance(data, Dict):
        logger.error("[sync_episodes] availability payload is not a dict: %r", type(data))
        return {"error": "availability payload is not a dict"}

    series_map = data.get("series") or {}
    if not isinstance(series_map, Dict):
        logger.error("[sync_episodes] availability.series is not a dict: %r", type(series_map))
        return {"error": "availability.series is not a dict"}

    logger.info("[sync_episodes] availability has %d series keys", len(series_map))

    created = 0
    deleted = 0

    if track_progress:
        vod_sync_progress["step"] = "sync_episodes"

    # Todas as séries conhecidas no VOD
    vod_series = (
        db.query(models.VodContent)
        .filter(
            models.VodContent.is_available == True,
            models.VodContent.type.in_(["tv", "series"]),
            models.VodContent.tmdb_id.isnot(None),
        )
        .all()
    )

    for vod in vod_series:
        tmdb_id = vod.tmdb_id
        key = str(tmdb_id)
        seasons = series_map.get(key)
        logger.info(
            "[sync_episodes] processing series tmdb_id=%s title=%s - found seasons: %s",
            tmdb_id,
            vod.title,
            list(seasons.keys()) if isinstance(seasons, Dict) else None,
        )
        if not isinstance(seasons, Dict):
            # Se não houver info de disponibilidade para essa série, removemos episódios antigos.
            deleted += (
                db.query(models.Episode)
                .filter(models.Episode.tmdb_id == tmdb_id)
                .delete(synchronize_session=False)
            )
            continue

        # Limpa episódios anteriores dessa série para recriar conforme disponibilidade atual.
        deleted += (
            db.query(models.Episode)
            .filter(models.Episode.tmdb_id == tmdb_id)
            .delete(synchronize_session=False)
        )

        base_title = vod.title
        base_category = vod.category
        base_poster = vod.poster_url

        for season_str, episodes in seasons.items():
            try:
                season_num = int(season_str)
            except (TypeError, ValueError):
                continue

            if not isinstance(episodes, List):
                logger.warning(
                    "[sync_episodes] episodes for tmdb_id=%s season=%s is not a list (type=%r)",
                    tmdb_id,
                    season_str,
                    type(episodes),
                )
                continue

            # Normaliza a lista de números de episódios desta temporada
            ep_numbers: List[int] = []
            for ep in episodes:
                try:
                    ep_numbers.append(int(ep))
                except (TypeError, ValueError):
                    continue

            # Busca metadados na TMDB em paralelo para esta temporada, com limite de
            # concorrência para não sobrecarregar a API.
            ep_meta: Dict[int, Dict] = {}
            if fetch_tmdb_details and tmdb_id and ep_numbers:
                sem = asyncio.Semaphore(25)

                async def fetch_ep_meta(ep_num: int) -> None:
                    tmdb_url = (
                        f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season_num}/episode/{ep_num}"
                    )
                    try:
                        async with sem:
                            logger.info(
                                "[sync_episodes] TMDB fetch episode tmdb_id=%s S%02dE%02d url=%s",
                                tmdb_id,
                                season_num,
                                ep_num,
                                tmdb_url,
                            )
                            async with httpx.AsyncClient(timeout=20) as tmdb_http:
                                r = await tmdb_http.get(
                                    tmdb_url,
                                    params={
                                        "api_key": "5173c8066086fe7c406c959303bd6cbf",
                                        "language": "pt-BR",
                                    },
                                )
                            logger.info(
                                "[sync_episodes] TMDB episode response status=%s",
                                r.status_code,
                            )
                            r.raise_for_status()
                            tdata = r.json() or {}
                            ep_meta[ep_num] = tdata
                            logger.info(
                                "[sync_episodes] TMDB episode payload keys=%s",
                                list(tdata.keys()),
                            )
                    except Exception:
                        logger.exception(
                            "[sync_episodes] TMDB episode fetch failed for tmdb_id=%s S%02dE%02d",
                            tmdb_id,
                            season_num,
                            ep_num,
                        )

                # Dispara requisições TMDB em paralelo (limitadas pelo semáforo)
                await asyncio.gather(*(fetch_ep_meta(n) for n in ep_numbers))

            # Agora, cria/atualiza episódios no banco usando os metadados (se houver)
            for ep_num in ep_numbers:
                meta = ep_meta.get(ep_num) or {}

                # Título, capa e duração padrão
                title = f"{base_title} S{season_num:02d}E{ep_num:02d}"
                poster = base_poster
                duration_secs = None

                if meta:
                    t_name = meta.get("name")
                    if t_name:
                        title = t_name
                    still_path = meta.get("still_path")
                    if still_path:
                        poster = f"https://image.tmdb.org/t/p/w300{still_path}"
                    runtime = meta.get("runtime") or 0
                    try:
                        duration_secs = int(runtime) * 60
                    except Exception:
                        duration_secs = None
                    logger.info(
                        "[sync_episodes] TMDB episode parsed tmdb_id=%s S%02dE%02d title=%r runtime_min=%r duration_secs=%r",
                        tmdb_id,
                        season_num,
                        ep_num,
                        title,
                        runtime,
                        duration_secs,
                    )

                stream_url = (
                    f"https://secure.webcontent03.fun/tv/{tmdb_id}/{season_num}/{ep_num}.mp4"
                    "?token=iptv1221908123kldkhfoithmvssjiruifhbjhfugynnd"
                )

                episode = models.Episode(
                    vod_id=vod.id,
                    tmdb_id=tmdb_id,
                    season=season_num,
                    episode=ep_num,
                    title=title,
                    category=base_category,
                    poster_url=poster,
                    duration_secs=duration_secs,
                    stream_url=stream_url,
                    is_available=True,
                )
                db.add(episode)
                created += 1

    db.commit()

    logger.info(
        "[sync_episodes] done - episodes_created=%d episodes_deleted=%d",
        created,
        deleted,
    )

    return {"episodes_created": created, "episodes_deleted": deleted}


async def vod_sync_job_with_progress() -> dict:
    """Job completo de sincronização de VOD + episódios, com progresso global.

    Cria sua própria sessão de banco para não depender do request atual.
    """

    vod_sync_progress.update(
        {
            "running": True,
            "current": 0,
            "total": 0,
            "tmdb_attempts": 0,
            "tmdb_success": 0,
            "step": "starting",
            "error": None,
        }
    )

    db: Session = SessionLocal()
    try:
        vod_sync_progress["step"] = "sync_vod"
        # Nesta rotina completa, buscamos novamente dados na TMDB para
        # preencher capas e metadados de VOD.
        vod_result = await sync_vod_from_contents_json(
            db,
            track_progress=True,
            fetch_tmdb=True,
            only_type=None,
        )
        vod_sync_progress["step"] = "sync_episodes"
        episodes_result = await sync_series_episodes_from_availability(db, track_progress=True)
        vod_sync_progress["step"] = "done"
        return {"vod": vod_result, "episodes": episodes_result}
    except Exception as exc:  # noqa: BLE001
        vod_sync_progress["error"] = str(exc)
        vod_sync_progress["step"] = "error"
        raise
    finally:
        vod_sync_progress["running"] = False
        db.close()


async def vod_sync_job_fast_with_progress() -> dict:
    """Job de sincronização de VOD + episódios, pulando detalhes por episódio na TMDB.

    Atualiza normalmente os conteúdos VOD (incluindo metadados TMDB para filmes/séries),
    mas na etapa de episódios usa ``fetch_tmdb_details=False`` para criar todos os
    episódios a partir da disponibilidade externa sem chamar a TMDB para cada um.
    """

    vod_sync_progress.update(
        {
            "running": True,
            "current": 0,
            "total": 0,
            "tmdb_attempts": 0,
            "tmdb_success": 0,
            "step": "starting_fast",
            "error": None,
        }
    )

    db: Session = SessionLocal()
    try:
        vod_sync_progress["step"] = "sync_vod_fast"
        vod_result = await sync_vod_from_contents_json(
            db,
            track_progress=True,
            fetch_tmdb=True,
            only_type=None,
        )
        vod_sync_progress["step"] = "sync_episodes_fast"
        episodes_result = await sync_series_episodes_from_availability(
            db,
            track_progress=True,
            fetch_tmdb_details=False,
        )
        vod_sync_progress["step"] = "done_fast"
        return {"vod": vod_result, "episodes": episodes_result}
    except Exception as exc:  # noqa: BLE001
        vod_sync_progress["error"] = str(exc)
        vod_sync_progress["step"] = "error_fast"
        raise
    finally:
        vod_sync_progress["running"] = False
        db.close()
