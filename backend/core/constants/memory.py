# ─────────────────────
# 1. 대화 RAG 검색 설정
# ─────────────────────
# 과거 대화에서 가져올 유사 메시지 최대 개수
RAG_TOP_K = 3

RAG_MAX_DISTANCE = 0.5


# ──────────────────────────────────────
# 2. 기억 프로필 (memory_profile)
# ──────────────────────────────────────
PROFILE_SECTIONS = ["Identity", "Preferences", "Hobbies", "Schedule", "Projects"]

PROFILE_ALWAYS_INJECT = ["Identity"]

PROFILE_SECTION_KEYWORDS = {
    "Preferences": ["선호", "좋아하는", "싫어", "취향", "스타일"],
    "Hobbies":     ["취미", "좋아", "게임", "관심사", "여가", "강아지", "반려동물", "애완", "펫"],
    "Schedule":    ["일정", "약속", "스케줄", "언제", "날짜", "계획"],
    "Projects":    ["프로젝트", "작업", "개발", "만들", "코드"],
}

# 기억 강제 트리거
MEMORY_KEYWORDS = frozenset({
    "기억해", "기억해줘", "외워", "외워줘", "저장해", "저장해줘",
})

# 한국어 섹션 별칭
SECTION_ALIASES = {
    "신원": "Identity", "정보": "Identity",
    "선호도": "Preferences", "선호": "Preferences", "취향": "Preferences",
    "취미": "Hobbies",
    "일정": "Schedule", "스케줄": "Schedule",
    "프로젝트": "Projects", "작업": "Projects",
}


# ──────────────────────────────────────
# 3. 세션·백그라운드 주기
# ──────────────────────────────────────
SUMMARY_EVERY_N_TURNS = 5