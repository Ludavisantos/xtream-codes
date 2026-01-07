from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from fastapi.concurrency import run_in_threadpool
import asyncio

from ..database import get_db
from ..services import sync_service
from ..deps import get_current_admin
from .. import models

router = APIRouter(prefix="/admin/sync", tags=["admin-sync"])


@router.post("/channels")
async def sync_channels(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Sincroniza categorias e canais do Firestore para o banco local."""

    # Firestore client é bloqueante; roda em thread separada
    result = await run_in_threadpool(sync_service.sync_channels_and_categories_from_firestore, db)
    return result

@router.post("/vod")
async def sync_vod(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Sincroniza conteúdos VOD (filmes/séries) a partir do JSON de conteúdos."""

    vod_result = await sync_service.sync_vod_from_contents_json(db)
    # Em seguida sincroniza episódios de séries usando o endpoint externo
    episodes_result = await sync_service.sync_series_episodes_from_availability(db)
    return {
        "vod": vod_result,
        "episodes": episodes_result,
    }


@router.post("/vod/contents-only")
async def sync_vod_contents_only(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Sincroniza conteúdos VOD + episódios, mas sem buscar detalhes por episódio na TMDB.

    Útil quando você quer atualizar rapidamente filmes/séries e gerar todos os
    episódios a partir da disponibilidade externa, porém sem o custo das
    chamadas detalhadas por episódio na TMDB (títulos/capas/duração exatos).
    """

    vod_result = await sync_service.sync_vod_from_contents_json(
        db,
        track_progress=False,
        fetch_tmdb=True,
        only_type=None,
    )
    episodes_result = await sync_service.sync_series_episodes_from_availability(
        db,
        track_progress=False,
        fetch_tmdb_details=False,
    )
    return {"vod": vod_result, "episodes": episodes_result}


@router.post("/episodes")
async def sync_episodes_only(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Sincroniza apenas episódios de séries usando a disponibilidade externa + TMDB.

    Não altera filmes nem séries no VOD, apenas recria/atualiza registros na
    tabela Episode (título, capa, duração e URL final).
    """

    episodes_result = await sync_service.sync_series_episodes_from_availability(db)
    return {"episodes": episodes_result}


@router.post("/vod/movies")
async def sync_vod_movies(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Sincroniza apenas filmes VOD a partir do JSON de conteúdos.

    Não toca em séries nem em episódios.
    """

    vod_result = await sync_service.sync_vod_from_contents_json(
        db,
        track_progress=False,
        fetch_tmdb=True,
        only_type="movies",
    )
    return {"vod": vod_result}


@router.post("/vod/series")
async def sync_vod_series(
    db: Session = Depends(get_db),
    _: models.User = Depends(get_current_admin),
):
    """Sincroniza apenas séries VOD e seus episódios.

    Atualiza títulos do tipo tv/series e em seguida sincroniza episódios
    com base na disponibilidade externa.
    """

    vod_result = await sync_service.sync_vod_from_contents_json(
        db,
        track_progress=False,
        fetch_tmdb=True,
        only_type="series",
    )
    episodes_result = await sync_service.sync_series_episodes_from_availability(db)
    return {
        "vod": vod_result,
        "episodes": episodes_result,
    }


@router.post("/vod/start")
async def sync_vod_start(
    _: models.User = Depends(get_current_admin),
):
    """Inicia job assíncrono de VOD com progresso em memória."""

    # Dispara tarefa em background usando o event loop atual.
    loop = asyncio.get_event_loop()
    loop.create_task(sync_service.vod_sync_job_with_progress())
    return {"started": True}


@router.get("/vod/progress")
async def sync_vod_progress(
    _: models.User = Depends(get_current_admin),
):
    """Retorna o estado atual de progresso da sincronização de VOD."""

    return sync_service.vod_sync_progress


@router.post("/vod/start-fast")
async def sync_vod_start_fast(
    _: models.User = Depends(get_current_admin),
):
    """Inicia job assíncrono de VOD rápido (sem detalhes de episódios) com progresso."""

    loop = asyncio.get_event_loop()
    loop.create_task(sync_service.vod_sync_job_fast_with_progress())
    return {"started": True}
