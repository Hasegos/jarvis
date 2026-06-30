from contextlib import asynccontextmanager
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from api.router import api_router
from core.config import settings
from core.templates import templates
from db.session import engine
from db.base import Base

# ─────────────────────────────────────
# 1. 앱 생명주기 (lifespan)
# ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    앱 시작/종료 시 실행되는 생명주기 핸들러.

    시작 시 AUTO_CREATE_TABLES가 True면 테이블을 자동 생성한다.
    """
    if settings.AUTO_CREATE_TABLES:
        # ──────────────────────────────────────
        # 1-1. pgvector extension 활성화
        # ──────────────────────────────────────
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()

        # ──────────────────────────────────────
        # 1-2. 테이블 자동 생성
        # ──────────────────────────────────────
        Base.metadata.create_all(bind=engine)

    yield


# ─────────────────────────────────────
# 2. FastAPI 앱 초기화
# ─────────────────────────────────────
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    lifespan=lifespan,
)


# ─────────────────────────────────────
# 3. 정적 파일 + 템플릿
# ─────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' "
            "https://cdnjs.cloudflare.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' http://localhost:8000; "
            "media-src 'self' blob: data:;"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"]         = "DENY"
        response.headers["Referrer-Policy"]         = "no-referrer"
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ─────────────────────────────────────
# 4. CORS 미들웨어
# ─────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


# ─────────────────────────────────────
# 5. 라우터 등록
# ─────────────────────────────────────
app.include_router(api_router, prefix="/api/v1")


# ─────────────────────────────────────
# 6. 웹 페이지
# ─────────────────────────────────────
@app.get("/", include_in_schema=False)
async def index(request: Request):
    """자비스 홀로그램 메인 UI 서빙."""
    return templates.TemplateResponse(request, "hologram.html")


# ─────────────────────────────────────
# 7. 헬스체크
# ─────────────────────────────────────
@app.get("/health", tags=["health"])
def health_check():
    """서버 정상 동작 여부를 확인한다."""
    return {"status": "ok", "project": settings.PROJECT_NAME}