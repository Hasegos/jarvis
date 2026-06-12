import time

from sqlalchemy.orm import Session
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from core.config import settings
from core.logger import get_logger
from crud.chat_crud import (
    create_message,
    get_all_messages_by_session,
    get_messages_by_session,
    get_or_create_session,
    search_similar_messages,
    update_session_summary
)
from crud.memory_crud import (
    get_all_sections,
    get_sections_by_names,
    upsert_section
)
from db.session import SessionLocal
from models.session_model import Session as ChatSession
from services.embedding_service import embed_text
from services.wiki_service import search_wiki
from services.llm_service import (
    chat_with_tools,
    stream_chat_with_tools,
    generate_summary,
    strip_markdown,
    extract_profile_updates 
)
from core.constant import (
    SYSTEM_PROMPT,
    THINKING_KEYWORDS,
    THINKING_LENGTH_THRESHOLD,
    PROFILE_ALWAYS_INJECT,
    PROFILE_SECTION_KEYWORDS,
    SUMMARY_EVERY_N_TURNS,
    FORCE_SEARCH_KEYWORDS,
    MEMORY_KEYWORDS,
    SECTION_ALIASES
)

logger = get_logger("chat_service")


# ─────────────────────────────────────
# 1. 세션 요약 백그라운드 실행
# ─────────────────────────────────────
def run_summary_background(
        session_id: int,
        immediate_profile: bool = False,
        forced_section: str | None = None,
) -> None:
    """
    세션의 전체 대화를 한 단어로 요약하고, 기억 프로필을 갱신한다.

    Args:
        session_id: 요약할 세션 PK
    immediate_profile: True 면 2턴 주기 게이트와 무관하게 프로필을 즉시 갱신
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
        # 1-2. 세션 요약
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

        # ──────────────────────────────────────
        # 1-3. 기억 프로필 갱신 (요약과 같은 주기)
        # ──────────────────────────────────────
        if gate_open or immediate_profile:
            try:
                _update_memory_profile(db, history, forced_section)
            except Exception as e:
                logger.warning("프로필 갱신 실패 (무시): %s", e)
    except Exception as e:
        logger.warning("백그라운드 태스크 실패 (무시): %s", e)
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
# 3. web_search 강제 여부 판단
# ─────────────────────────────────────
def _should_force_search(user_text: str) -> bool:
    """
    입력에 검색 명령 키워드(검색/찾아 등)가 있으면 web_search 를 강제한다.

    모델 자율 판단에 맡기면 stale 한 history 를 보고 검색을 건너뛰는 경우가
    있어, 명시적 검색 요청 시에는 도구 호출을 강제하기 위한 플래그를 만든다.
    (부분 문자열 매칭 — "검색엔진" 같은 단어에도 걸릴 수 있음)

    Args:
        user_text: 사용자 입력 텍스트
    Returns:
        web_search 강제 여부
    """
    lowered = user_text.lower()
    return any(kw in lowered for kw in FORCE_SEARCH_KEYWORDS)


# ─────────────────────────────────────
# 4. 기억(프로필 저장) 요청 판단
# ─────────────────────────────────────
def _parse_memory_request(user_text: str) -> tuple[bool, str | None]:
    """
    입력이 명시적 기억 요청('기억해줘' 등)인지, 특정 섹션을 찍었는지 판단한다.

    - MEMORY_KEYWORDS 가 있으면 즉시 저장 대상(2턴 게이트 우회).
    - SECTION_ALIASES 의 한국어 별칭이 같이 있으면 그 섹션으로 강제 저장.
        (없으면 forced_section=None → LLM 자동 분류)

    Args:
        user_text: 사용자 입력 텍스트
    Returns:
        (is_memory_request, forced_section)
        - is_memory_request: 명시적 기억 요청 여부
        - forced_section   : 강제 저장할 영어 섹션명. 없으면 None.
    """
    lowered = user_text.lower()

    is_memory = any(kw in lowered for kw in MEMORY_KEYWORDS)
    if not is_memory:
        return False, None

    forced_section = None
    for alias, section in SECTION_ALIASES.items():
        if alias in lowered:
            forced_section = section
            break

    return True, forced_section


# ─────────────────────────────────────
# 5. 과거 대화 검색 (RAG 컨텍스트 구성)
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


# ─────────────────────────────────────
# 6. 기억 프로필 주입 (필수 + 키워드 매칭)
# ─────────────────────────────────────
def _select_profile_sections(user_text: str) -> list[str]:
    """
    입력에 따라 주입할 프로필 섹션명을 결정한다.

    필수 섹션은 항상 포함하고, 비필수는 키워드가 입력에 있으면 추가한다.

    Args:
        user_text: 사용자 입력 텍스트
    Returns:
        주입할 섹션명 리스트 (중복 없음)
    """
    selected = list(PROFILE_ALWAYS_INJECT)
    lowered  = user_text.lower()
    for section, keywords in PROFILE_SECTION_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            selected.append(section)
    # 중복 제거 (순서 유지)
    return list(dict.fromkeys(selected))


# ─────────────────────────────────────
# 7. 프로필 컨텍스트 블록 구성
# ─────────────────────────────────────
def _build_profile_context(db: Session, user_text: str) -> str | None:
    """
    선택된 프로필 섹션을 조회해 LLM 주입용 텍스트 블록으로 만든다.

    내용이 빈 섹션은 제외한다. 주입할 게 없으면 None을 반환한다.

    Args:
        db       : SQLAlchemy 세션
        user_text: 사용자 입력 텍스트
    Returns:
        프로필 참고 블록 텍스트. 없으면 None.
    """
    names    = _select_profile_sections(user_text)
    sections = get_sections_by_names(db, names)

    blocks = [
        f"## {s.section}\n{s.content.strip()}"
        for s in sections
        if s.content and s.content.strip()
    ]
    if not blocks:
        return None

    logger.debug("프로필 주입: %s", [s.section for s in sections if s.content and s.content.strip()])
    return "[사용자 기억 프로필]\n" + "\n\n".join(blocks)


# ─────────────────────────────────────
# 8. 기억 프로필 갱신 (백그라운드)
# ─────────────────────────────────────
def _update_memory_profile(
        db: Session,
        history: list[dict],
        forced_section: str | None = None
) -> None:
    """
    대화에서 장기 기억할 사실을 추출해 프로필 섹션을 갱신한다.

    LLM이 '변경된 섹션만' 반환하며, 안전장치로 기존보다 줄 수가 줄어드는
    갱신은 거부한다(사실 삭제 방지). 실패는 무시한다.

    Args:
        db     : SQLAlchemy 세션
        history: 요약에 쓰인 전체 대화 히스토리
        forced_section: 강제 저장 섹션명. None이면 LLM 자동 분류.
    """
    # 현재 프로필을 섹션별 텍스트로 합본
    sections = get_all_sections(db)
    current  = {s.section: (s.content or "") for s in sections}
    profile_text = "\n\n".join(
        f"## {name}\n{content}" for name, content in current.items()
    )
    conversation = "\n".join(f"{m['role']}: {m['content']}" for m in history)

    updates = extract_profile_updates(profile_text, conversation, forced_section)
    if not updates:
        logger.debug("프로필 갱신 없음")
        return

    # ──────────────────────────────────────
    # 8-1. 줄 수 가드 후 섹션별 저장 (삭제 방지)
    # ──────────────────────────────────────
    for upd in updates:
        section  = upd["section"]
        new_body = upd["content"]
        old_body = current.get(section, "")

        old_lines = len([ln for ln in old_body.splitlines() if ln.strip()])
        new_lines = len([ln for ln in new_body.splitlines() if ln.strip()])

        if new_lines < old_lines:
            logger.warning(
                "프로필 갱신 거부(줄 감소): section=%s %d→%d", section, old_lines, new_lines
            )
            continue

        upsert_section(db, section, new_body)
        logger.debug("프로필 갱신: section=%s lines=%d", section, new_lines)


# ─────────────────────────────────────
# 9. 메시지 처리 (공통 파이프라인)
# ─────────────────────────────────────
async def process_message(
    db        : Session,
    session_id: int | None,
    user_text : str,
) -> tuple[ChatSession, str, dict]:
    """
    텍스트 입력을 받아 세션 판단 → 프로필/RAG 주입 → LLM → 임베딩 → DB 저장까지 처리한다.

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
    # 9-1. 세션 판단
    # ──────────────────────────────────────
    session = await run_in_threadpool(get_or_create_session, db, session_id)

    # ──────────────────────────────────────
    # 9-2. 대화 히스토리 구성
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
    # 9-3. user 임베딩 + RAG/프로필 컨텍스트 구성
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    user_embedding = await run_in_threadpool(embed_text, user_text)
    timings["embedding"] = round(time.perf_counter() - t0, 2)

    rag_context     = await run_in_threadpool(
        _build_rag_context, db, user_embedding, session.session_id
    )
    profile_context = await run_in_threadpool(
        _build_profile_context, db, user_text
    )
    wiki_context = await run_in_threadpool(search_wiki, user_text)

    # 프로필(항상/관련) + 위키 노트 + 과거 대화(RAG)를 하나의 컨텍스트로 합친다.
    context = "\n\n".join(c for c in (profile_context, wiki_context, rag_context) if c) or None

    # ──────────────────────────────────────
    # 9-4. LLM 호출
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    use_thinking = _should_think(user_text)
    force_search = _should_force_search(user_text)
    logger.debug(
        "thinking=%s force_search=%s | input_len=%d",
        "on" if use_thinking else "off", force_search, len(user_text),
    )
    # 도구(web_search 등) 사용 가능한 에이전트 루프.
    answer = await run_in_threadpool(chat_with_tools, history, use_thinking, context, force_search)
    answer = strip_markdown(answer)
    timings["llm"] = round(time.perf_counter() - t0, 2)

    # ──────────────────────────────────────
    # 9-5. assistant 임베딩
    # ──────────────────────────────────────
    t0 = time.perf_counter()
    assistant_embedding = await run_in_threadpool(embed_text, answer)
    timings["embedding"] = round(timings["embedding"] + (time.perf_counter() - t0), 2)

    # ──────────────────────────────────────
    # 9-6. 메시지 저장
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


# ─────────────────────────────────────
# 10. 메시지 처리 (스트리밍 파이프라인, SSE용)
# ─────────────────────────────────────
async def process_message_stream(
    db        : Session,
    session_id: int | None,
    user_text : str,
):
    """
    텍스트 입력을 받아 토큰/상태 이벤트를 실시간으로 yield 하는 스트리밍 파이프라인.

    Yields:
        {"type": "token",  "text": str}                          — 답변 조각
        {"type": "status", "text": str}                          — 도구 실행 상태
        {"type": "answer_complete", "session_id", "answer"}      — 저장 완료 후 마지막 이벤트
    Raises:
        RuntimeError: LLM 또는 임베딩 오류
    """
    # ──────────────────────────────────────
    # 10-1. 세션 + 히스토리 + 컨텍스트
    # ──────────────────────────────────────
    session = await run_in_threadpool(get_or_create_session, db, session_id)

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

    user_embedding = await run_in_threadpool(embed_text, user_text)

    rag_context     = await run_in_threadpool(
        _build_rag_context, db, user_embedding, session.session_id
    )
    profile_context = await run_in_threadpool(
        _build_profile_context, db, user_text
    )
    wiki_context = await run_in_threadpool(search_wiki, user_text)

    context = "\n\n".join(c for c in (profile_context, wiki_context, rag_context) if c) or None

    # ──────────────────────────────────────
    # 10-2. 스트리밍 LLM — 토큰을 즉시 중계하며 누적
    # ──────────────────────────────────────
    use_thinking = _should_think(user_text)
    force_search = _should_force_search(user_text)
    logger.debug(
        "thinking=%s force_search=%s | input_len=%d | stream",
        "on" if use_thinking else "off", force_search, len(user_text),
    )

    answer_parts: list[str] = []
    gen = stream_chat_with_tools(history, use_thinking, context, force_search)
    async for event in iterate_in_threadpool(gen):
        if event["type"] == "token":
            answer_parts.append(event["text"])
        yield event

    answer = strip_markdown("".join(answer_parts).strip())

    # ──────────────────────────────────────
    # 10-3. 임베딩 + 저장 (스트림 종료 후)
    # ──────────────────────────────────────
    assistant_embedding = await run_in_threadpool(embed_text, answer)
    await run_in_threadpool(
        create_message, db, session.session_id, "user", user_text, user_embedding
    )
    await run_in_threadpool(
        create_message, db, session.session_id, "assistant", answer, assistant_embedding
    )

    yield {"type": "answer_complete", "session_id": session.session_id, "answer": answer}