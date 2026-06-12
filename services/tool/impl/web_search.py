import json

from ddgs import DDGS

from core.logger import get_logger
from core.constants.tool import (
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_REGION,
    WEB_SEARCH_SNIPPET_MAX_CHARS,
    WEB_SEARCH_TIMEOUT,
)

logger = get_logger("tool.web_search")


# ─────────────────────
# 1. 도구 스펙
# ─────────────────────
SPEC = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "웹에서 최신 정보를 검색한다. "
            "날씨·시세·뉴스·환율 등 시간에 따라 변하는 실시간 정보는 "
            "과거 대화나 이전 답변에 비슷한 내용이 있더라도 "
            "반드시 이 도구로 다시 검색해 최신 값을 확인한다. "
            "학습 데이터에 없는 최신 사실, 확인이 필요한 정보에도 사용한다. "
            "단순 인사나 일반 상식에는 사용하지 않는다. "
            "검색은 한 번만 수행하고, 결과를 받은 뒤 1~3문장으로 간결히 답한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "검색어. 문장이 아니라 핵심 키워드로 작성 (예: '비트코인 시세', 'RTX 5090 가격')",
                },
            },
            "required": ["query"],
        },
    },
}


# ─────────────────────
# 2. 도구 실행
# ─────────────────────
def run(args: dict) -> str:
    """
    DuckDuckGo(ddgs)로 웹을 검색해 상위 결과를 JSON 문자열로 반환한다.

    실패해도 예외를 올리지 않고 error 필드로 반환해, 모델이
    "검색에 실패했다"고 자연스럽게 답하게 한다.

    Args:
        args: {"query": 검색어}
    Returns:
        {"results": [{title, url, snippet}, ...]} 또는 {"error": ...} JSON 문자열
    """
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "검색어가 비어 있습니다"}, ensure_ascii=False)

    try:
        with DDGS(timeout=WEB_SEARCH_TIMEOUT) as ddgs:
            rows = list(ddgs.text(
                query,
                region=WEB_SEARCH_REGION,
                max_results=WEB_SEARCH_MAX_RESULTS,
            ))
    except Exception as e:
        logger.warning("web_search 실패: %s", e)
        return json.dumps({"error": f"검색 실패: {e}"}, ensure_ascii=False)

    results = [
        {
            "title"  : r.get("title", ""),
            "url"    : r.get("href", ""),
            "snippet": (r.get("body", "") or "")[:WEB_SEARCH_SNIPPET_MAX_CHARS],
        }
        for r in rows
    ]
    logger.debug("web_search: query=%r results=%d", query, len(results))
    return json.dumps({"results": results}, ensure_ascii=False)


# ─────────────────────
# 3. 도구 안내 문구
# ─────────────────────
def announce(args: dict) -> tuple[str, str]:
    """
    이 도구 실행을 (화면 표시용, 음성 안내용) 두 문구로 변환한다.

    도구의 안내는 도구 자신이 정의한다 — 도구 추가 시 이 파일 하나로 끝.

    Args:
        args: 모델이 생성한 도구 인자 dict
    Returns:
        (status_text, speech_text)
    """
    query = (args.get("query") or "").strip()
    if query:
        return (f"검색 중: {query}", f"{query}, 검색해 보겠습니다.")
    return ("검색 중...", "검색해 보겠습니다.")