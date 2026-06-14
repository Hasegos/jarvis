import json


# ─────────────────────────────────────
# 1. 성공 결과 JSON
# ─────────────────────────────────────
def ok(**fields) -> str:
    """
    도구 성공 결과를 JSON 문자열로 만든다.

    Args:
        **fields: 결과 키/값 (예: created=True, path="...")
    Returns:
        JSON 문자열
    """
    return json.dumps(fields, ensure_ascii=False)


# ─────────────────────────────────────
# 2. 오류 결과 JSON
# ─────────────────────────────────────
def err(message: str) -> str:
    """
    도구 오류 결과를 JSON 문자열로 만든다.

    원본 예외(내부 경로 등)는 호출부 logger로만 남기고, 여기엔 일반 문구만 넣는다.

    Args:
        message: 사용자/LLM에 보일 오류 문구
    Returns:
        {"error": message} JSON 문자열
    """
    return json.dumps({"error": message}, ensure_ascii=False)