from fastapi import APIRouter

from .endpoints import chat_endpoint, voice_endpoint

# ─────────────────────────────────────────
# API 라우터 통합 등록
# ─────────────────────────────────────────
api_router = APIRouter()

api_router.include_router(chat_endpoint.router, prefix="/chat", tags=["chat"])
api_router.include_router(voice_endpoint.router, prefix="/voice", tags=["voice"])