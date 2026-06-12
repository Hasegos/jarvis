import json

from sqlalchemy.orm import Session

from core.config import settings
from core.constants.memory import (
    PROFILE_SECTIONS,
    PROFILE_ALWAYS_INJECT,
    PROFILE_SECTION_KEYWORDS,
    MEMORY_KEYWORDS,
    SECTION_ALIASES,
)
from core.constants.prompts import PROFILE_EXTRACT_PROMPT
from core.logger import get_logger
from crud.memory_crud import (
    get_all_sections,
    get_sections_by_names,
    upsert_section
)
from services.llm.lm_client import lm_client
from services.llm.text_utils import strip_thinking

logger = get_logger("profile_service")


# ─────────────────────────────────────
# 1. 기억(프로필 저장) 요청 판단
# ─────────────────────────────────────
def _parse_memory_request(user_text: str) -> tuple[bool, str | None]:
    """
    입력이 명시적 기억 요청('기억해줘' 등)인지, 특정 섹션을 찍었는지 판단한다.

    - MEMORY_KEYWORDS 가 있으면 즉시 저장 대상(주기 게이트 우회).
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
# 2. 주입 섹션 선택 (필수 + 키워드 매칭)
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
# 3. 프로필 컨텍스트 블록 구성
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
# 4. 기억 프로필 갱신 추출 (LLM)
# ─────────────────────────────────────
def extract_profile_updates(
        profile_text: str,
        conversation: str,
        forced_section: str | None = None,
) -> list[dict]:
    """
    현재 프로필과 대화를 보고, 갱신할 섹션만 JSON 배열로 추출한다.

    thinking 없이 호출한다. 변경이 없거나 파싱 실패 시 빈 리스트를 반환해
    호출부가 안전하게 스킵하도록 한다.

    Args:
        profile_text  : 현재 전체 프로필 텍스트 (섹션별 마크다운 합본)
        conversation  : 최근 대화 텍스트
        forced_section: 지정 시 추출된 모든 사실을 이 섹션에 강제 저장. None이면 LLM 자동 분류.
    Returns:
        [{"section": str, "content": str}, ...]. 변경 없음/실패 시 [].
    """
    prompt = PROFILE_EXTRACT_PROMPT.format(
        sections=", ".join(PROFILE_SECTIONS),
        profile=profile_text or "(empty)",
        conversation=conversation,
        forced_section=forced_section or "(none)",
    )
    try:
        response = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": "You extract durable user facts as strict JSON."},
                {"role": "user",   "content": "/no_think\n" + prompt},
            ],
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=0.1,
            max_tokens=settings.LLM_MAX_TOKENS,
        )
        raw = response.choices[0].message.content or ""
        raw = strip_thinking(raw).strip()

        # ──────────────────────────────────────
        # 4-1. JSON 파싱 (코드펜스/잡텍스트 방어)
        # ──────────────────────────────────────
        start = raw.find("[")
        end   = raw.rfind("]")
        if start == -1 or end == -1 or end < start:
            return []
        items = json.loads(raw[start : end + 1])

        # 형식 검증: 정해진 섹션 + 비어있지 않은 content 문자열만 통과
        result = []
        for it in items:
            if (
                isinstance(it, dict)
                and it.get("section") in PROFILE_SECTIONS
                and isinstance(it.get("content"), str)
                and it["content"].strip()
            ):
                result.append({"section": it["section"], "content": it["content"].strip()})
        return result
    except Exception:
        return []


# ─────────────────────────────────────
# 5. 기억 프로필 갱신 (저장)
# ─────────────────────────────────────
def _update_memory_profile(
        db: Session,
        history: list[dict],
        forced_section: str | None = None,
) -> None:
    """
    대화에서 장기 기억할 사실을 추출해 프로필 섹션을 갱신한다.

    LLM이 '변경된 섹션만' 반환하며, 안전장치로 기존보다 줄 수가 줄어드는
    갱신은 거부한다(사실 삭제 방지). 실패는 무시한다.

    Args:
        db            : SQLAlchemy 세션
        history       : 요약에 쓰인 전체 대화 히스토리
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
    # 5-1. 줄 수 가드 후 섹션별 저장 (삭제 방지)
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