import json

from ddgs import DDGS

from core.logger import get_logger
from core.constant import WEB_SEARCH_MAX_RESULTS, WEB_SEARCH_REGION

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
            "시세·날씨·뉴스 등 실시간 정보, 학습 데이터에 없는 최신 사실, "
            "확인이 필요한 정보에만 사용한다. "
            "일상 대화나 이미 아는 일반 지식에는 사용하지 않는다."
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
        with DDGS() as ddgs:
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
            "snippet": r.get("body", ""),
        }
        for r in rows
    ]
    logger.debug("web_search: query=%r results=%d", query, len(results))
    return json.dumps({"results": results}, ensure_ascii=False)