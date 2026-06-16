# ─────────────────────────────────────
# 1. 도구 (function calling)
# ─────────────────────────────────────
# 에이전트 루프 최대 반복 횟수 (도구 호출→결과→재호출).
TOOL_MAX_ITERATIONS = 3

WEB_SEARCH_MAX_RESULTS = 3
WEB_SEARCH_SNIPPET_MAX_CHARS = 300
WEB_SEARCH_RAW_MAX_CHARS = 2000     # 1위 결과 페이지 본문 상한
WEB_SEARCH_TIMEOUT = 10 # Tavily 외부 호출 타임아웃
WEB_SEARCH_DEPTH = "basic" 


# ─────────────────────────────────────
# 2. 메모 (vault_write)
# ─────────────────────────────────────
MEMO_TAGS_MAX = 3

MEMO_EMPTY_MARKERS = [
    "확인되지 않", "확인할 수 없", "찾지 못", "찾을 수 없",
    "정보가 없", "정보를 찾", "정보가 부족", "알 수 없",
    "검색되지 않", "결과가 없", "나오지 않", "나타나지 않",
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
    "web_search":  frozenset({"검색", "검색해", "검색해줘"}),
    "vault_write": frozenset({"메모해", "메모해줘", "기록해", "기록해줘"}),
    "file_ops":    frozenset({"파일"}),
    "os_control":  frozenset({"실행", "실행해", "실행해줘", "켜줘", "탐색기",
                            "틀어", "틀어줘", "재생", "재생해줘",
                            "찾아", "찾아줘", "찾아봐"}),
    "navigation":  frozenset({"길찾기", "경로", "가는길", "가는 길",
                            "어떻게 가", "얼마나 걸려"}),
}


# ─────────────────────────────────────
# 4. confirm 자동 해소 키워드
# ─────────────────────────────────────
CONFIRM_APPROVE_KEYWORDS = frozenset({
    "좋아", "해줘", "진행", "진행해", "진행해줘",
    "실행", "실행해", "실행해줘", "오케이",
})
CONFIRM_DENY_KEYWORDS = frozenset({
    "아니", "취소", "하지마", "됐어", "그만",
})

# 음성 confirm 보류 시 preview 뒤에 붙이는 질문
CONFIRM_VOICE_SUFFIX = "진행할까요? 진행 또는 취소라고 말씀해 주세요."


# ─────────────────────────────────────
# 5. 파일 조작 (file_ops)
# ─────────────────────────────────────
FILE_OPS_ACTIONS = frozenset({
    "create", "read", "list", "modify",
    "delete", "purge", "move", "restore",
})
# confirm 면제 action (읽기 전용)
FILE_OPS_SAFE_ACTIONS = frozenset({"read", "list"})
FILE_OPS_READ_MAX_CHARS = 10000   # read 결과 상한 (초과 시 truncate)
FILE_OPS_LIST_MAX = 100           # list 결과 항목 상한