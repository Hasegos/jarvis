import time

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from core.config import settings
from core.logger import get_logger
from crud.chat_crud import (
    create_message,
    get_all_messages_by_session,
    get_messages_by_session,
    get_or_create_session,
    update_session_summary
)
from db.session import SessionLocal
from models.session_model import Session as ChatSession
from services.embedding_service import embed_text
from services.llm_service import chat, generate_summary, stream_chat, strip_thinking,strip_markdown
from core.constant import THINKING_KEYWORDS, THINKING_LENGTH_THRESHOLD

logger = get_logger("chat_service")


# ─────────────────────────────────────
# 1. 세션 요약 백그라운드 실행
# ─────────────────────────────────────
def run_summary_background(session_id: int) -> None:
    """
    세션의 전체 대화를 한 단어로 요약해 DB에 저장한다.

    자체 DB 세션을 생성하므로 BackgroundTasks에서 안전하게 실행된다.

    Args:
        session_id: 요약할 세션 PK
    """

    logger.debug("요약 태스크 시작: session=%d", session_id)
    db = SessionLocal()
    try:
        messages = get_all_messages_by_session(db, session_id)
        logger.debug("메시지 조회: session=%d count=%d", session_id, len(messages))
        if not messages:
            return
        
        history = [{"role": m.role, "content": m.content} for m in messages]
        summary = generate_summary(history)
        logger.debug("summary 생성 결과: session=%d summary=%r", session_id, summary)

        if summary:
            update_session_summary(db, session_id, summary)
            logger.debug("session=%d summary=%s", session_id, summary)
        else:
            logger.warning("summary 빈 문자열: session=%d", session_id)
    except Exception as e:
        logger.warning("요약 생성 실패 (무시): %s", e)
    finally:
        db.close()


# ─────────────────────────────────────
# 2. thinking 사용 여부 판단
# ─────────────────────────────────────
def _should_think(user_text: str) -> bool:
    """
    입력 텍스트와 모드 설정으로 thinking 활성화 여부를 결정한다.

    - off : 항상 비활성화
    - on  : 항상 활성화
    - auto: 복잡한 키워드 포함 또는 긴 입력이면 활성화

    Args:
        user_text: 사용자 입력 텍스트
    Returns:
        thinking 활성화 여부
    """
    mode = settings.LLM_THINKING_MODE.lower()
    if mode == "on":
        return True
    if mode == "off":
        return False

    # ──────────────────────────────────────
    # 2-1. auto 모드 — 복잡도 판단
    # ──────────────────────────────────────
    if len(user_text) >= THINKING_LENGTH_THRESHOLD:
        return True
    return any(kw in user_text.lower() for kw in THINKING_KEYWORDS)


# ─────────────────────────────────────
# 3. 메시지 처리 (공통 파이프라인)
# ─────────────────────────────────────
async def process_message(
    db        : Session,
    session_id: int | None,
    user_text : str,
) -> tuple[ChatSession, str, dict]:
    """
    텍스트 입력을 받아 세션 판단 → LLM → 임베딩 → DB 저장까지 처리한다.

    Args:
        db        : SQLAlchemy 세션
        session_id: 클라이언트가 넘긴 세션 ID
        user_text : STT 또는 텍스트 입력
    Returns:
        (session, answer, timings)
        - session: 현재 세션 객체
        - answer : LLM 답변 텍스트
        - timings: 단계별 소요 시간 딕셔너리
    Raises:
        RuntimeError: LLM 또는 임베딩 오류
    """
    timings = {}

    # ──────────────────────────────────────
    # 3-1. 세션 판단
    # ──────────────────────────────────────
    session = await run_in_threadpool(get_or_create_session, db, session_id)

    # ──────────────────────────────────────
    # 3-2. 대화 히스토리 구성
    # ──────────────────────────────────────
    messages = await run_in_threadpool(
        get_messages_by_session,
        db,
        session.session_id,
        settings.HISTORY_LIMIT,
    )
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in messages
    ]
    history.append({"role": "user", "content": user_text})

    # ──────────────────────────────────────
    # 3-3. LLM 호출
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    use_thinking = _should_think(user_text)
    logger.debug("thinking=%s | input_len=%d", "on" if use_thinking else "off", len(user_text))
    if settings.LLM_STREAMING:
        tokens = await run_in_threadpool(lambda: list(stream_chat(history, use_thinking)))
        answer = strip_thinking("".join(tokens))
    else:
        answer = await run_in_threadpool(chat, history, use_thinking)
    answer = strip_markdown(answer)
    timings["llm"] = round(time.perf_counter() - t0, 2)

    # ──────────────────────────────────────
    # 3-4. 임베딩 생성
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    user_embedding      = await run_in_threadpool(embed_text, user_text)
    assistant_embedding = await run_in_threadpool(embed_text, answer)
    timings["embedding"] = round(time.perf_counter() - t0, 2)

    # ──────────────────────────────────────
    # 3-5. 메시지 저장
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    await run_in_threadpool(
        create_message, db, session.session_id, "user", user_text, user_embedding
    )
    await run_in_threadpool(
        create_message, db, session.session_id, "assistant", answer, assistant_embedding
    )
    timings["db"] = round(time.perf_counter() - t0, 2)

    return session, answer, timings