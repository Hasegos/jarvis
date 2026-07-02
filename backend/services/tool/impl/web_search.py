import re, urllib.parse

from tavily import TavilyClient

from core.config import settings
from core.logger import get_logger
from core.constants.tool import (
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_RAW_MAX_CHARS,
    WEB_SEARCH_SNIPPET_MAX_CHARS,
    WEB_SEARCH_TIMEOUT,
    WEB_SEARCH_DEPTH,
)
from services.tool.tool_result import ok, err

logger = get_logger("tool.web_search")

# 위험도
RISK = "safe"

# 프롬프트 인젝션 패턴
_INJECTION_RE = re.compile(
    r"ignore\s+(previous|prior|above|all\s+instruction)|"
    r"new\s+instruction|"
    r"<\|?\s*(system|user|assistant)\s*\|?>|"
    r"(?<!\w)system\s*:",
    re.IGNORECASE,
)

_client = TavilyClient(api_key=settings.TAVILY_API_KEY)

# ─────────────────────────
# 1. 프롬프트 인젝션 제거
# ─────────────────────────
def _strip_injection(text: str) -> str:
    """프롬프트 인젝션 패턴이 포함된 줄을 제거한다."""
    return "\n".join(l for l in text.splitlines() if not _INJECTION_RE.search(l))


# ─────────────────────
# 2. 도구 스펙
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
# 3. 도구 실행
# ─────────────────────
def run(args: dict) -> str:
    """
    Tavily(LLM 최적화 검색)로 웹을 검색해 결과를 JSON 문자열로 반환한다.

    스니펫뿐 아니라 1위 결과의 페이지 본문(page_content)도 포함해,
    표·상세 데이터처럼 스니펫에 안 담기는 정보까지 모델에 전달한다.
    실패해도 예외를 올리지 않고 error 필드로 반환한다.

    Args:
        args: {"query": 검색어}
    Returns:
        {"answer": str, "results": [{title, url, snippet, page_content?}, ...],
         "open_url": 클라이언트가 열 구글 검색 URL}
        또는 {"error": ...} JSON 문자열
    """
    query = (args.get("query") or "").strip()
    if not query:
        return err("검색어가 비어 있습니다")

    try:
        response = _client.search(
            query,
            search_depth=WEB_SEARCH_DEPTH,
            max_results=WEB_SEARCH_MAX_RESULTS,
            include_answer=True,
            include_raw_content=True,
            timeout=WEB_SEARCH_TIMEOUT,
        )
    except Exception as e:
        logger.warning("web_search 실패: %s", e)
        return err("검색 중 오류가 발생했습니다.")

    # 전체 결과에 붙이면 컨텍스트가 넘치므로 가장 관련도 높은 1건만.
    results = []
    for i, r in enumerate(response.get("results", [])):
        item = {
            "title"  : r.get("title", ""),
            "url"    : r.get("url", ""),
            "snippet": (r.get("content", "") or "")[:WEB_SEARCH_SNIPPET_MAX_CHARS],
        }
        if i == 0:
            raw = (r.get("raw_content", "") or "").strip()
            if raw:
                item["page_content"] = _strip_injection(raw)[:WEB_SEARCH_RAW_MAX_CHARS]
        results.append(item)
    answer = (response.get("answer") or "").strip()

    logger.debug(
        "web_search: query=%r results=%d answer=%s page_content=%s",
        query, len(results), bool(answer),
        bool(results and "page_content" in results[0]),
    )

    # 검색 URL을 결과를 호출한 기기(클라이언트)에서 열게 한다
    payload = {
        "results": results,
        "open_url": f"https://www.google.com/search?q={urllib.parse.quote(query)}",
    }
    if answer:
        payload["answer"] = answer
    return ok(**payload)


# ─────────────────────
# 4. 도구 안내 문구
# ─────────────────────
def announce(args: dict) -> tuple[str, str]:
    """
    이 도구 실행을 (화면 표시용, 음성 안내용) 두 문구로 변환한다.

    Args:
        args: 모델이 생성한 도구 인자 dict
    Returns:
        (status_text, speech_text)
    """
    query = (args.get("query") or "").strip()
    if query:
        return (f"검색 중: {query}", f"{query}, 검색해 보겠습니다.")
    return ("검색 중...", "검색해 보겠습니다.")