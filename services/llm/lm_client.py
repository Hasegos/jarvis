from openai import OpenAI
from core.config import settings

# ─────────────────────────────────────
# 1. LM Studio 공용 클라이언트
# ─────────────────────────────────────
lm_client = OpenAI(
    base_url=settings.LM_STUDIO_BASE_URL,
    api_key=settings.LM_STUDIO_API_KEY,
)