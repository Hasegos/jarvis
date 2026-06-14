import json, re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from core.config import settings
from core.constants.prompts import MEMO_ORGANIZE_PROMPT
from core.constants.tool import (
    MEMO_TAGS_MAX,
    MEMO_CATEGORIES,
    MEMO_DEFAULT_CATEGORY,
    MEMO_SLUG_MAX_LEN,
    MEMO_EMPTY_MARKERS,
)
from core.logger import get_logger
from services.llm.lm_client import lm_client
from services.llm.text_utils import strip_thinking

logger = get_logger("tool.vault_write")

_KST = ZoneInfo("Asia/Seoul")

# 태그에 못 쓰는 문자 제거용 (한글·영문·숫자만)
_TAG_STRIP_RE = re.compile(r"[^0-9A-Za-z가-힣]+")
# 파일명에 못 쓰는 문자 제거용 (한글·영문·숫자·하이픈·공백만 허용)
_SLUG_STRIP_RE = re.compile(r"[^0-9A-Za-z가-힣\- ]+")


# ─────────────────────
# 1. 도구 스펙
# ─────────────────────
SPEC = {
    "type": "function",
    "function": {
        "name": "vault_write",
        "description": (
            "사용자가 메모·기록을 요청하면 내용을 Obsidian 데일리 노트에 저장한다. "
            "'메모해줘', '기록해줘', '적어둬' 같은 요청에 사용한다. "
            "직전 대화 내용을 메모해 달라는 요청이면 그 내용을 content에 담는다. "
            "사용자에 대한 장기 사실(이름·취향 등)을 기억하는 용도가 아니다 — "
            "그건 별도 기억 시스템이 처리한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "메모할 내용 전체. 사용자가 말한 내용 또는 메모를 요청한 직전 대화 내용.",
                },
            },
            "required": ["content"],
        },
    },
}


# ─────────────────────────────────────
# 2. 빈 메모 판정 (검색 실패 내용 차단)
# ─────────────────────────────────────
def _is_empty_memo(content: str) -> bool:
    """
    "정보를 찾지 못했다"는 내용만 담긴 메모인지 판정한다.

    검색이 실패하면 모델이 "구독자 수는 확인되지 않았습니다" 같은 빈 껍데기를
    메모하려 한다. 이를 막아 쓸모없는 메모가 쌓이는 걸 방지한다.

    Args:
        content: 메모 원문
    Returns:
        빈 메모면 True (저장 차단), 아니면 False
    """
    has_marker = any(m in content for m in MEMO_EMPTY_MARKERS)
    has_number = any(ch.isdigit() for ch in content)
    return has_marker and not has_number


# ─────────────────────────────────────
# 3. 카테고리 별칭 확정 (결정적 매칭)
# ─────────────────────────────────────
def _resolve_category_alias(text: str) -> str | None:
    """
    텍스트에 카테고리 별칭이 있으면 그 카테고리를 확정한다.

    사용자가 명시한 분류("회의록으로 메모해줘")는 LLM 재량을 거치지 않고 결정적으로 따른다.

    Args:
        text: 메모 원문
    Returns:
        확정된 카테고리명. 별칭이 없으면 None (→ LLM 자동분류).
    """
    for category, conf in MEMO_CATEGORIES.items():
        if any(alias in text for alias in conf["aliases"]):
            return category
    return None


# ───────────────────────────────────────────
# 4. LLM 정리 (원문 → 제목·카테고리·태그·본문)
# ───────────────────────────────────────────
def _organize_memo(content: str) -> dict | None:
    """
    원문을 LLM으로 정리해 {title, tags, body}를 추출한다.

    Args:
        content: 메모 원문
    Returns:
        {"title": str, "tags": [str], "body": str}. 실패 시 None.
    """
    prompt = MEMO_ORGANIZE_PROMPT.format(
        content=content,
        categories=", ".join(MEMO_CATEGORIES),
        default_category=MEMO_DEFAULT_CATEGORY,
    )
    try:
        response = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": "You organize a memo into strict JSON."},
                {"role": "user",   "content": "/no_think\n" + prompt},
            ],
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=0.1,
            max_tokens=1024,
        )
        raw = strip_thinking(response.choices[0].message.content or "").strip()

        # JSON 오브젝트만 추출 (코드펜스/잡텍스트 방어)
        start = raw.find("{")
        end   = raw.rfind("}")
        if start == -1 or end == -1 or end < start:
            return None

        data = json.loads(raw[start : end + 1])

        title    = (data.get("title") or "").strip()
        body     = (data.get("body") or "").strip()
        tags     = data.get("tags") or []
        category = (data.get("category") or "").strip()

        if not title or not body or not isinstance(tags, list):
            return None

        if category not in MEMO_CATEGORIES:
            category = MEMO_DEFAULT_CATEGORY

        tags = [_TAG_STRIP_RE.sub("", str(t)) for t in tags]
        tags = [t for t in tags if t][:MEMO_TAGS_MAX]
        return {"title": title, "tags": tags, "body": body, "category": category}

    except Exception as e:
        logger.warning("메모 정리 LLM 실패 (원문 폴백): %s", e)
        return None


# ─────────────────────────────────────────
# 5. 파일명 슬러그 + 중복 회피 (file 모드용)
# ─────────────────────────────────────────
def _slugify(title: str) -> str:
    """제목을 파일명 슬러그로 변환한다 (소문자, 공백→하이픈, 한글 유지)."""
    slug = _SLUG_STRIP_RE.sub("", title).strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:MEMO_SLUG_MAX_LEN] or "memo"


# ─────────────────────────────────────
# 6. 동명 파일 중복 회피 (file 모드용)
# ─────────────────────────────────────
def _unique_path(base_dir: Path, slug: str) -> Path:
    """동명 파일이 있으면 -2, -3 … suffix로 회피한다."""
    path = base_dir / f"{slug}.md"
    n = 2
    while path.exists():
        path = base_dir / f"{slug}-{n}.md"
        n += 1
    return path


# ─────────────────────
# 7. 도구 실행
# ─────────────────────
def run(args: dict) -> str:
    """
    메모를 정리해 날짜별 데일리 노트(YYYY-MM-DD.md)에 섹션으로 추가한다.

    파일이 없으면 헤더와 함께 생성하고, 있으면 끝에 append 한다 —
    하루치 메모가 한 파일에 시간순으로 쌓인다.

    Args:
        args: {"content": 메모 원문}
    Returns:
        {"saved": true, "file": 파일명, "title": 제목} 또는 {"error": ...} JSON 문자열
    """
    content = (args.get("content") or "").strip()
    if not content:
        return json.dumps({"error": "메모할 내용이 비어 있습니다"}, ensure_ascii=False)

    # 검색 실패로 껍데기 메모는 저장하지 않는다.
    if _is_empty_memo(content):
        logger.debug("빈 메모 차단(정보 없음): %d자", len(content))
        return json.dumps(
            {"skipped": True, "reason": "검색 결과에 저장할 정보가 없어 메모하지 않았습니다."},
            ensure_ascii=False,
        )

    base_dir = Path(settings.VAULT_WRITE_PATH)

    if not base_dir.is_dir():
        logger.warning("vault-write 경로 없음: %s", base_dir)
        return json.dumps(
            {"error": "메모 저장 경로가 없습니다. 마운트를 확인하세요."},
            ensure_ascii=False,
        )

    now = datetime.now(_KST)

    # ──────────────────────────────────────
    # 7-1. LLM 정리 (실패 시 원문 폴백)
    # ──────────────────────────────────────
    organized = _organize_memo(content)
    if organized:
        title, tags, body = organized["title"], organized["tags"], organized["body"]
        category = organized["category"]
    else:
        title    = "메모"
        tags     = []
        body     = content
        category = MEMO_DEFAULT_CATEGORY

    # 별칭 명시가 있으면 LLM 분류보다 우선한다 (결정적 > 재량)
    alias_category = _resolve_category_alias(content)

    if alias_category:
        category = alias_category

    # ──────────────────────────────────────
    # 7-2. 섹션 구성
    # ──────────────────────────────────────
    tags_line = (" ".join(f"#{t}" for t in tags) + "\n") if tags else ""
    section = (
        f"\n## {title}  ({now.strftime('%H:%M')})\n"
        f"{tags_line}"
        f"\n{body}\n"
    )

    try:
        cat_dir = base_dir / now.strftime("%Y") / now.strftime("%m") / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        mode = MEMO_CATEGORIES[category]["mode"]

        if mode == "file":
            # 건당 파일 (긴 문서형): {카테고리}/{제목슬러그}.md
            path = _unique_path(cat_dir, _slugify(title))
            tags_fm = "[" + ", ".join(tags) + "]" if tags else "[]"
            note = (
                "---\n"
                "type: memo\n"
                f"category: {category}\n"
                f"tags: {tags_fm}\n"
                f"created: {now.strftime('%Y-%m-%d')}\n"
                "source: jarvis\n"
                "---\n\n"
                f"# {title}\n\n"
                f"{body}\n"
            )
            path.write_text(note, encoding="utf-8")
        else:
            # 날짜 append (짧은 조각형): {카테고리}/YYYY-MM-DD.md
            path = cat_dir / f"{now.strftime('%Y-%m-%d')}.md"
            if not path.exists():
                header = (
                    "---\n"
                    "type: memo-daily\n"
                    f"category: {category}\n"
                    f"created: {now.strftime('%Y-%m-%d')}\n"
                    "source: jarvis\n"
                    "---\n\n"
                    f"# {now.strftime('%Y-%m-%d')} 메모\n"
                )
                path.write_text(header + section, encoding="utf-8")
            else:
                with path.open("a", encoding="utf-8") as f:
                    f.write(section)

    except Exception as e:
        logger.warning("메모 저장 실패: %s", e)
        return json.dumps({"error": f"메모 저장 실패: {e}"}, ensure_ascii=False)

    logger.debug("메모 저장: %s/%s ← %r (정리=%s)", category, path.name, title, bool(organized))
    return json.dumps(
        {"saved": True, "category": category, "file": path.name, "title": title},
        ensure_ascii=False,
    )


# ─────────────────────
# 8. 도구 안내 문구
# ─────────────────────
def announce(args: dict) -> tuple[str, str]:
    """
    이 도구 실행을 (화면 표시용, 음성 안내용) 두 문구로 변환한다.

    Args:
        args: 모델이 생성한 도구 인자 dict
    Returns:
        (status_text, speech_text)
    """
    return ("메모 정리 중...", "메모를 정리해서 저장하겠습니다.")