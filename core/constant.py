# ──────────────────────────────────────
# 1. 시스템 프롬프트
# ──────────────────────────────────────
SYSTEM_PROMPT = (
    "당신의 이름은 JARVIS입니다. "
    "아이언맨의 AI 비서 자비스처럼, 사용자를 보좌하는 AI 비서입니다. "
    "당신은 사람이 아니며, 토니 스타크나 아이언맨이 아닙니다. "
    "사용자가 토니 스타크이고, 당신은 그를 돕는 AI 비서입니다. "
    "사용자를 '아이언' 또는 '아이언 님'으로 부릅니다. '스타크'나 '토니' 같은 호칭은 사용하지 않습니다. "
    "답변 규칙: "
    "일반 질문·대화는 반드시 1~2문장으로 핵심만 말한다. "
    "코드·분석·절차 설명처럼 복잡한 요청만 필요한 만큼 길게 답한다. "
    "자기소개·감탄사('물론입니다', '좋은 질문이에요' 등)·부연설명은 하지 않는다. "
    "출력 형식: 별표(**), 해시(#) 같은 마크다운 기호를 사용하지 않는다. 순수 텍스트만 출력한다. "
    "음성으로 전달되므로 마크다운·리스트·기호를 사용하지 않는다."
)


# ──────────────────────────────────────
# 2. STT 환청 블랙리스트
# ──────────────────────────────────────
# Whisper가 무음·노이즈 구간에서 생성하는 유튜브 자막류 환청을 차단
STT_HALLUCINATION_PHRASES = [
    "시청해 주셔서 감사", "구독과 좋아요", "좋아요", "구독",
    "MBC뉴스", "KBS", "자막 제공", "번역",
]


# ──────────────────────────────────────
# 3. Dynamic thinking 판단 기준
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


# ──────────────────────────────────────
# 4. STT 자주 쓰는 단어
# ──────────────────────────────────────
STT_VOCAB = [
    "자비스", "엄마", "아빠", "하나님", "주님",
    "아이언","수금"
]

STT_INITIAL_PROMPT = (", ".join(STT_VOCAB) + " 등의 단어가 나올 수 있습니다.") if STT_VOCAB else None


# ─────────────────────
# 5. 대화 RAG 검색 설정
# ─────────────────────
# 과거 대화에서 가져올 유사 메시지 최대 개수
RAG_TOP_K = 3

RAG_MAX_DISTANCE = 0.5


# ──────────────────────────────────────
# 6. 기억 프로필 (memory_profile)
# ──────────────────────────────────────
PROFILE_SECTIONS = ["Identity", "Preferences", "Hobbies", "Schedule", "Projects"]

PROFILE_ALWAYS_INJECT = ["Identity"]

PROFILE_SECTION_KEYWORDS = {
    "Preferences": ["선호", "좋아하는", "싫어", "취향", "스타일"],
    "Hobbies":     ["취미", "좋아", "게임", "관심사", "여가", "강아지", "반려동물", "애완", "펫"],
    "Schedule":    ["일정", "약속", "스케줄", "언제", "날짜", "계획"],
    "Projects":    ["프로젝트", "작업", "개발", "만들", "코드"],
}

MEMORY_KEYWORDS = frozenset({
    "기억해", "기억해줘", "외워", "외워줘", "저장해", "저장해줘",
})

SECTION_ALIASES = {
    "신원": "Identity", "정보": "Identity",
    "선호도": "Preferences", "선호": "Preferences", "취향": "Preferences",
    "취미": "Hobbies",
    "일정": "Schedule", "스케줄": "Schedule",
    "프로젝트": "Projects", "작업": "Projects",
}

# 프로필 갱신 추출 프롬프트.
PROFILE_EXTRACT_PROMPT = """\
You maintain a long-term memory profile of the user, split into fixed sections.
Sections: {sections}

Below is the CURRENT profile and the RECENT conversation.
Find NEW or CHANGED durable facts about the user worth remembering long-term
(identity, preferences, hobbies, schedule, projects). Ignore one-off chit-chat.

Rules:
- Output ONLY a JSON array. No prose, no markdown fences.
- Each item: {{"section": "<one of the sections>", "content": "<full updated markdown for that section>"}}
- Include a section ONLY if it changed. If nothing changed, output [].
- content is the COMPLETE markdown for that section in ENGLISH, as "- key: value" bullet lines.
- NEVER delete existing facts. Keep all current lines and ADD/UPDATE as needed.
- If a fact changes (e.g. a name correction), update that line, keep the rest.
- Section guide for choosing the right section: a person's name, pets, family, residence/location are durable identity facts -> "Identity". Likes/dislikes/taste -> "Preferences". Hobbies/games/interests -> "Hobbies". Appointments/dates/plans -> "Schedule". Work/dev/projects -> "Projects".
- If FORCED_SECTION below is not "(none)", put ALL extracted facts into that exact section, ignoring the section guide.

CURRENT PROFILE:
{profile}

RECENT CONVERSATION:
{conversation}

FORCED_SECTION: {forced_section}

JSON:"""


# ──────────────────────────────────────
# 7. Obsidian wiki 검색 설정
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


# ──────────────────────────────────────
# 8. 세션·백그라운드 주기
# ──────────────────────────────────────
SUMMARY_EVERY_N_TURNS = 2


# ─────────────────────────────────────
# 9. 도구 (function calling)
# ─────────────────────────────────────
# 에이전트 루프 최대 반복 횟수 (도구 호출→결과→재호출).
TOOL_MAX_ITERATIONS = 3
WEB_SEARCH_MAX_RESULTS = 3
WEB_SEARCH_REGION = "kr-kr"
WEB_SEARCH_SNIPPET_MAX_CHARS = 200
WEB_SEARCH_TIMEOUT = 10 # ddgs 외부 호출 타임아웃(초)

FORCE_SEARCH_KEYWORDS = frozenset({
    "검색", "검색해", "검색해줘", "찾아서",
    "찾아", "찾아줘", "찾아봐"
})


# ─────────────────────────────────────
# 10. thinking 여부에따른 토큰값
# ─────────────────────────────────────
ANSWER_MAX_TOKENS_SIMPLE   = 2048
ANSWER_MAX_TOKENS_THINKING = 8192