from fastapi import FastAPI, Request
import logging
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .database import Base, engine
from .routers import admin_users, xtream, admin_categories, admin_channels, admin_sync, admin_auth, admin_vod, admin_lines

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
app.include_router(xtream.router)


@app.get("/")
async def root():
    return {"message": "Xtream Codes-style server running"}


@app.get("/admin")
async def admin_panel(request: Request):
    base_url = str(request.base_url)
    return templates.TemplateResponse("admin.html", {"request": request, "base_url": base_url})
