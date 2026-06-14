import json

from core.logger import get_logger
from services.tool.registry import (
    TOOL_SPECS,
    TOOL_HANDLERS,
    TOOL_ANNOUNCERS,
    TOOL_RISK,
    TOOL_PREVIEWS,
    TOOL_CONFIRM_CHECKS,
    get_forced_tool_specs
)
from services.tool.result import err

logger = get_logger("tool_service")

__all__ = [
    "TOOL_SPECS",
    "execute_tool",
    "announce_tool",
    "requires_confirm",
    "preview_tool",
    "get_forced_tool_specs",
]


# ─────────────────────────────────────
# 1. 도구 실행 디스패처
# ─────────────────────────────────────
def execute_tool(name: str, arguments_json: str) -> str:
    """
    도구 이름과 인자(JSON 문자열)를 받아 레지스트리에서 찾아 실행한다.

    모든 실패는 error JSON 으로 반환한다 — 도구 오류가 대화를 죽이지 않게.

    Args:
        name          : 도구 이름 (tool/impl 레지스트리에 등록된 이름)
        arguments_json: LLM이 생성한 인자 JSON 문자열
    Returns:
        도구 실행 결과 JSON 문자열
    """
    logger.info("도구 실행: %s(%.120s)", name, arguments_json or "")

    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return err("잘못된 인자 형식")

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return err(f"알 수 없는 도구: {name}")

    try:
        return handler(args)
    except Exception as e:
        logger.warning("도구 실행 오류: %s — %s", name, e)
        return err("도구 실행 중 오류가 발생했습니다.")


# ─────────────────────────────────────
# 2. 도구 안내 디스패처
# ─────────────────────────────────────
def announce_tool(name: str, arguments_json: str) -> tuple[str, str]:
    """
    도구 호출을 (화면 표시용, 음성 안내용) 두 문구로 변환한다.

    문구는 각 도구의 announce() 가 정의하며, 미정의 도구나 인자 파싱
    실패 시 기본 문구로 폴백한다.

    Args:
        name          : 도구 이름
        arguments_json: LLM이 생성한 인자 JSON 문자열
    Returns:
        (status_text, speech_text)
    """
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}

    announcer = TOOL_ANNOUNCERS.get(name)
    if announcer is None:
        return (f"{name} 실행 중...", "잠시만요, 확인해 보겠습니다.")
    return announcer(args)


# ─────────────────────────────────────
# 3. confirm 필요 여부 판정
# ─────────────────────────────────────
def requires_confirm(name: str, args: dict | None = None) -> bool:
    """
    도구가 실행 전 사용자 확인(confirm)이 필요한지 판정한다.

    도구가 needs_confirm(args)를 정의하면 그것으로 action별 판정한다
    (예: file_ops는 read만 면제). 없으면 위험도 기반 판정:
    "destructive"는 확인 필요, "safe"/"write"는 즉시 실행, 미등록은 fail-safe.

    Args:
        name: 도구 이름
        args: 도구 인자 dict (action별 판정에 사용)
    Returns:
        확인이 필요하면 True
    """
    check = TOOL_CONFIRM_CHECKS.get(name)
    if check is not None:
        return check(args or {})
    return TOOL_RISK.get(name, "destructive") == "destructive"


# ─────────────────────────────────────
# 4. 실행 미리보기
# ─────────────────────────────────────
def preview_tool(name: str, arguments_json: str) -> str:
    """
    confirm 전, "이렇게 실행됩니다"를 부작용 없이 보여줄 문구를 만든다.

    도구가 preview(args)를 정의하면 그것을 쓰고, 없으면 일반 폴백.

    Args:
        name          : 도구 이름
        arguments_json: LLM이 생성한 인자 JSON 문자열
    Returns:
        미리보기 문구
    """
    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        args = {}

    previewer = TOOL_PREVIEWS.get(name)
    if previewer is not None:
        return previewer(args)
    return f"{name} 실행: {json.dumps(args, ensure_ascii=False)}"