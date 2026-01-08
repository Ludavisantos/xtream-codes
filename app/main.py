from fastapi import FastAPI, Request
import logging
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .database import Base, engine, SessionLocal
from . import models
from .routers import (
    admin_users,
    xtream,
    admin_categories,
    admin_channels,
    admin_sync,
    admin_auth,
    admin_vod,
    admin_lines,
    admin_settings,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Xtream Codes Python Server", debug=True)


logger = logging.getLogger("uvicorn.error")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Middleware global para logar todas as requisições HTTP."""
    logger.info("[REQUEST] %s %s", request.method, request.url.path)
    response = await call_next(request)
    logger.info("[RESPONSE] %s %s -> %s", request.method, request.url.path, response.status_code)
    return response

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.include_router(admin_auth.router)
app.include_router(admin_users.router)
app.include_router(admin_categories.router)
app.include_router(admin_channels.router)
app.include_router(admin_sync.router)
app.include_router(admin_vod.router)
app.include_router(admin_lines.router)
app.include_router(admin_settings.router)
app.include_router(xtream.router)


@app.get("/")
async def root():
    return {"message": "Xtream Codes-style server running"}


@app.get("/admin")
async def admin_panel(request: Request):
    base_url = str(request.base_url)

    # Obtém o nome do painel e o tema de login para exibir já na tela de login (antes da autenticação)
    db: Session = SessionLocal()
    try:
        settings = db.query(models.PanelSettings).first()
        panel_name = settings.panel_name if settings and settings.panel_name else "Xtream Python"
        ui = db.query(models.PanelUiSettings).first()
        login_theme = ui.login_theme if ui and ui.login_theme else "default"
    finally:
        db.close()

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "base_url": base_url,
            "panel_name": panel_name,
            "login_theme": login_theme,
        },
    )
