from openai import APIConnectionError, APITimeoutError

from core.config import settings
from core.logger import get_logger
from services.llm.lm_client import lm_client

logger = get_logger("embedding")


# ─────────────────────
# 1. 텍스트 임베딩
# ─────────────────────
def embed_text(text: str) -> list[float]:
    """
    텍스트를 bge-m3로 임베딩해 1024차원 벡터를 반환한다.

    Args:
        text: 임베딩할 텍스트
    Returns:
        1024차원 float 리스트
    Raises:
        RuntimeError: 연결 실패, 타임아웃, API 오류
    """
    try:
        response = lm_client.embeddings.create(
            model=settings.LM_STUDIO_EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding
    except APIConnectionError:
        raise RuntimeError(
            "LM Studio에 연결할 수 없습니다. LM Studio가 실행 중인지 확인하세요."
        )
    except APITimeoutError:
        raise RuntimeError(
            f"임베딩 타임아웃 ({settings.LM_STUDIO_TIMEOUT}초 초과)."
        )
    except Exception as e:
        logger.error("임베딩 오류: %s", e)
        raise RuntimeError("임베딩 처리 중 오류가 발생했습니다.")