from core.constants.memory import SUMMARY_EVERY_N_TURNS
from core.logger import get_logger
from crud.chat_crud import get_all_messages_by_session, update_session_summary
from db.session import SessionLocal
from services.llm.llm_service import generate_summary
from services.memory.profile_service import _update_memory_profile

logger = get_logger("background_service")


# ─────────────────────────────────────
# 1. 세션 요약 + 프로필 갱신 백그라운드 실행
# ─────────────────────────────────────
def run_summary_background(
        session_id: int,
        immediate_profile: bool = False,
        forced_section: str | None = None,
) -> None:
    """
    세션의 전체 대화를 한 단어로 요약하고, 기억 프로필을 갱신한다.

    Args:
        session_id       : 요약할 세션 PK
        immediate_profile: True 면 주기 게이트와 무관하게 프로필을 즉시 갱신
                            ("기억해줘" 등 명시적 기억 요청 시)
        forced_section   : 강제 저장할 영어 섹션명. None이면 LLM 자동 분류.
    """
    logger.debug("요약 태스크 시작: session=%d", session_id)
    db = SessionLocal()
    try:
        messages = get_all_messages_by_session(db, session_id)
        logger.debug("메시지 조회: session=%d count=%d", session_id, len(messages))
        if not messages:
            return

        # ──────────────────────────────────────
        # 1-1. 요약 주기 게이트 (비용 절감)
        # ──────────────────────────────────────
        assistant_turns = sum(1 for m in messages if m.role == "assistant")
        gate_open = (assistant_turns % SUMMARY_EVERY_N_TURNS == 1)

        history = [{"role": m.role, "content": m.content} for m in messages]

        # ──────────────────────────────────────
        # 1-2. 세션 요약 (주기 게이트에만 걸림)
        # ──────────────────────────────────────
        if gate_open:
            try:
                summary = generate_summary(history)
                logger.debug("summary 생성 결과: session=%d summary=%r", session_id, summary)
                if summary:
                    update_session_summary(db, session_id, summary)
                    logger.debug("session=%d summary=%s", session_id, summary)
                else:
                    logger.warning("summary 빈 문자열: session=%d", session_id)
            except Exception as e:
                logger.warning("요약 생성 실패 (무시): %s", e)
        else:
            logger.debug("요약 스킵(주기): session=%d turns=%d", session_id, assistant_turns)

        # ──────────────────────────────────────────────────
        # 1-3. 기억 프로필 갱신 (주기 게이트 OR 즉시저장 요청)
        # ──────────────────────────────────────────────────
        if gate_open or immediate_profile:
            try:
                _update_memory_profile(db, history, forced_section)
            except Exception as e:
                logger.warning("프로필 갱신 실패 (무시): %s", e)
    except Exception as e:
        logger.warning("백그라운드 태스크 실패 (무시): %s", e)
    finally:
        db.close()