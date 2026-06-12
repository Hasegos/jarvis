# ──────────────────────────────────────
# 1. Obsidian wiki 검색 설정
# ──────────────────────────────────────
WIKI_SUBDIR = "wiki"

WIKI_EXCLUDE_NAMES = {"_template", "index", "log"}

# 스코어링 가중치
WIKI_SCORE_FILENAME_EXACT   = 10.0   # 파일명 완전 일치
WIKI_SCORE_FILENAME_PARTIAL = 7.0    # 파일명 부분 포함
WIKI_SCORE_HEADING          = 4.0    # 본문 헤더(#)에 포함
WIKI_SCORE_BODY             = 2.0    # 본문에 포함

# 본문 등장 횟수 가산점 (횟수 × WEIGHT, 단 CAP 까지만)
WIKI_COUNT_WEIGHT = 0.5
WIKI_COUNT_CAP    = 3.0

WIKI_SCORE_THRESHOLD = 3.0

WIKI_TOP_K = 3

WIKI_MAX_CHARS = 1500