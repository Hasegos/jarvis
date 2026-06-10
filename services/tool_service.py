import json

from core.logger import get_logger
from services.tools.registry import TOOL_SPECS, TOOL_HANDLERS

logger = get_logger("tool_service")

__all__ = ["TOOL_SPECS", "execute_tool"]


# ─────────────────────────────────────
# 1. 도구 실행 디스패처
# ─────────────────────────────────────
def execute_tool(name: str, arguments_json: str) -> str:
    """
    도구 이름과 인자(JSON 문자열)를 받아 레지스트리에서 찾아 실행한다.

    모든 실패는 error JSON 으로 반환한다 — 도구 오류가 대화를 죽이지 않게.

    Args:
        name          : 도구 이름 (services/tools 레지스트리에 등록된 이름)
        arguments_json: LLM이 생성한 인자 JSON 문자열
    Returns:
        도구 실행 결과 JSON 문자열
    """
    logger.debug("도구 실행: %s(%s)", name, arguments_json)

    try:
        args = json.loads(arguments_json or "{}")
    except json.JSONDecodeError:
        return json.dumps({"error": "잘못된 인자 형식"}, ensure_ascii=False)

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"알 수 없는 도구: {name}"}, ensure_ascii=False)

    try:
        return handler(args)
    except Exception as e:
        logger.warning("도구 실행 오류: %s — %s", name, e)
        return json.dumps({"error": f"도구 실행 오류: {e}"}, ensure_ascii=False)