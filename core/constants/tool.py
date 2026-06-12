# ─────────────────────────────────────
# 1. 도구 (function calling)
# ─────────────────────────────────────
# 에이전트 루프 최대 반복 횟수 (도구 호출→결과→재호출).
TOOL_MAX_ITERATIONS = 3

WEB_SEARCH_MAX_RESULTS = 3
WEB_SEARCH_REGION = "kr-kr"
WEB_SEARCH_SNIPPET_MAX_CHARS = 200
WEB_SEARCH_TIMEOUT = 10 # ddgs 외부 호출 타임아웃(초)


# ─────────────────────────────────────
# 2. 검색 강제 트리거
# ─────────────────────────────────────
FORCE_SEARCH_KEYWORDS = frozenset({
    "검색", "검색해", "검색해줘", "찾아서",
    "찾아", "찾아줘", "찾아봐"
})