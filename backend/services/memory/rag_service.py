from sqlalchemy.orm import Session

from core.logger import get_logger
from crud.chat_crud import search_similar_messages

logger = get_logger("rag_service")


# ─────────────────────────────────────
# 1. 과거 대화 검색 (RAG 컨텍스트 구성)
# ─────────────────────────────────────
def _build_rag_context(db: Session, query_embedding: list[float], current_session_id: int) -> str | None:
    """
    현재 입력과 유사한 과거 대화를 검색해 LLM 주입용 텍스트 블록으로 만든다.

    현재 세션은 이미 히스토리로 들어가므로 제외한다. 관련 결과가 없으면
    None을 반환해 불필요한 토큰 주입을 막는다.

    Args:
        db                 : SQLAlchemy 세션
        query_embedding    : 현재 user 입력 임베딩
        current_session_id : 검색에서 제외할 현재 세션 PK
    Returns:
        과거 대화 참고 블록 텍스트. 관련 결과가 없으면 None.
    """
    results = search_similar_messages(db, query_embedding, exclude_session_id=current_session_id)
    if not results:
        return None

    lines = [f"- {msg.role}: {msg.content}" for msg, _dist in results]
    logger.debug("RAG 검색: %d건 주입", len(results))
    return "[참고: 과거 대화에서 관련된 내용]\n" + "\n".join(lines)