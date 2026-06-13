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
# 2. 메모 (vault_write)
# ─────────────────────────────────────
MEMO_TAGS_MAX = 3

MEMO_EMPTY_MARKERS = [
    "확인되지 않", "확인할 수 없", "찾지 못", "찾을 수 없",
    "정보가 없", "정보를 찾", "정보가 부족", "알 수 없",
    "검색되지 않", "결과가 없", "나오지 않", "나타나지 않"
    "직접적으로 나타나", "확인이 필요",
]

MEMO_CATEGORIES = {
    "회의록":   {"aliases": ["회의록", "회의"],          "mode": "file"},
    "아이디어": {"aliases": ["아이디어"],                "mode": "daily"},
    "할일":     {"aliases": ["할일", "할 일", "투두"],   "mode": "daily"},
    "학습":     {"aliases": ["학습", "공부"],            "mode": "daily"},
    "일반":     {"aliases": [],                          "mode": "daily"},
}
MEMO_DEFAULT_CATEGORY = "일반"
MEMO_SLUG_MAX_LEN = 50   # file 모드 파일명 슬러그 최대 길이


# ─────────────────────────────────────
# 3. 강제 도구 트리거
# ─────────────────────────────────────
FORCED_TOOL_KEYWORDS = {
    "web_search": frozenset({
        "검색", "검색해", "검색해줘", "찾아서",
        "찾아", "찾아줘", "찾아봐",
    }),
    "vault_write": frozenset({
        "메모", "메모해", "메모해줘",
        "기록해", "기록해줘",
        "적어둬", "적어줘",
    }),
}