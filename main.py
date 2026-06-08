from contextlib import asynccontextmanager

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


# ─────────────────────────────────────
# 4. CORS 미들웨어
# ─────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_methods=["*"],
    allow_headers=["*"],
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
    """자비스 웹 UI 서빙."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/chat", include_in_schema=False)
async def chat_page(request: Request):
    """자비스 채팅 페이지 서빙."""
    return templates.TemplateResponse(request, "chat.html")

# ─────────────────────────────────────
# 7. 헬스체크
# ─────────────────────────────────────
@app.get("/health", tags=["health"])
def health_check():
    """서버 정상 동작 여부를 확인한다."""
    return {"status": "ok", "project": settings.PROJECT_NAME}