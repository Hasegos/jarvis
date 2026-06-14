# ──────────────────────────────────────
# 1. Dynamic thinking 판단 기준
# ──────────────────────────────────────
THINKING_LENGTH_THRESHOLD = 150
THINKING_KEYWORDS = frozenset({
    # 코드·프로그래밍
    "코드", "함수", "클래스", "알고리즘", "구현", "짜줘", "작성해",
    "python", "java", "javascript", "typescript", "sql", "api",
    "버그", "오류", "에러", "디버그", "수정해",
    # 분석·설계
    "설계", "아키텍처", "최적화", "리팩터링", "분석해", "비교해",
    "장단점", "차이점",
})


# ─────────────────────────────────────
# 2. thinking 여부에따른 토큰값
# ─────────────────────────────────────
ANSWER_MAX_TOKENS_SIMPLE   = 2048
ANSWER_MAX_TOKENS_THINKING = 32768