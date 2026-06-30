import hmac

from contextlib import asynccontextmanager
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from api.router import api_router
from core.config import settings
from core.logger import get_logger
from db.session import engine
from db.base import Base

logger = get_logger("main")

# ─────────────────────────────────────
# 1. 앱 생명주기 (lifespan)
# ─────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    앱 시작/종료 시 실행되는 생명주기 핸들러.

    시작 시 AUTO_CREATE_TABLES가 True면 테이블을 자동 생성한다.
    """
    if not settings.INTERNAL_API_TOKEN.strip():
        raise RuntimeError(
            "INTERNAL_API_TOKEN이 비어 있습니다."
        )

    if settings.AUTO_CREATE_TABLES:
        # ──────────────────────────────────────
        # 1-1. pgvector extension 활성화
        # ──────────────────────────────────────
        try:
            with engine.connect() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()

            # ──────────────────────────────────────
            # 1-2. 테이블 자동 생성
            # ──────────────────────────────────────
            Base.metadata.create_all(bind=engine)
        except Exception as e:
            logger.error("DB 초기화 실패: %s", type(e).__name__)
            raise RuntimeError(
                "데이터베이스 초기화에 실패했습니다. "
                "DB 연결 정보를 확인하세요."
            ) from None

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
# 4. CSP 보안 헤더
# ─────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' data: blob:; "
            "connect-src 'self'; "
            "media-src 'self' blob: data:;"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"]         = "DENY"
        response.headers["Referrer-Policy"]         = "no-referrer"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# ─────────────────────────────────────
# 5. 내부 API 인증 미들웨어
# ─────────────────────────────────────
class TokenAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        if request.method == "OPTIONS" or request.url.path == "/health":
            return await call_next(request)
        if not hmac.compare_digest(
            request.headers.get("X-Internal-Token", ""),
            settings.INTERNAL_API_TOKEN,
        ):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return await call_next(request)

app.add_middleware(TokenAuthMiddleware)


# ─────────────────────────────────────
# 6. CORS 미들웨어
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
    allow_headers=["Content-Type", "X-Internal-Token"],
)


# ─────────────────────────────────────
# 6. 라우터 등록
# ─────────────────────────────────────
app.include_router(api_router, prefix="/api/v1")


# ─────────────────────────────────────
# 7. 헬스체크
# ─────────────────────────────────────
@app.get("/health", tags=["health"])
def health_check():
    """서버 정상 동작 여부를 확인한다."""
    return {"status": "ok", "project": settings.PROJECT_NAME}