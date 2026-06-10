import re
from pathlib import Path

from core.config import settings
from core.logger import get_logger
from core.constant import (
    WIKI_SUBDIR, WIKI_EXCLUDE_NAMES,
    WIKI_SCORE_FILENAME_EXACT, WIKI_SCORE_FILENAME_PARTIAL,
    WIKI_SCORE_HEADING, WIKI_SCORE_BODY,
    WIKI_COUNT_WEIGHT, WIKI_COUNT_CAP,
    WIKI_SCORE_THRESHOLD, WIKI_TOP_K, WIKI_MAX_CHARS,
)

logger = get_logger("wiki_service")


# ─────────────────────────────────────
# 1. 질문에서 검색 키워드 추출
# ─────────────────────────────────────
def _extract_keywords(query: str) -> list[str]:
    """
    질문 문자열을 검색용 키워드 토큰으로 분리한다.

    2글자 미만 토큰은 노이즈가 많아 제외한다.

    Args:
        query: 사용자 입력 텍스트
    Returns:
        소문자 키워드 리스트 (중복 제거)
    """
    tokens = re.findall(r"[0-9A-Za-z가-힣]+", query.lower())
    seen   = [t for t in tokens if len(t) >= 2]
    return list(dict.fromkeys(seen))


# ─────────────────────────────────────
# 2. 노트 1개 점수 계산
# ─────────────────────────────────────
def _score_note(filename: str, text: str, keywords: list[str]) -> float:
    """
    파일명/본문에서의 키워드 매칭 위치로 노트 관련도 점수를 매긴다.

    파일명 일치 > 부분 포함 > 헤더 포함 > 본문 포함 순으로 가중하고,
    본문 등장 횟수에 가산점(상한 있음)을 준다.

    Args:
        filename: 확장자 제외 파일명 (소문자)
        text    : 노트 본문 (소문자)
        keywords: 질문 키워드 리스트
    Returns:
        누적 점수
    """
    score = 0.0
    # 본문에서 '# 헤더' 줄만 모은 텍스트 (헤더 매칭 판정용)
    headings = " ".join(re.findall(r"^#{1,6}\s+.*$", text, re.MULTILINE))

    for kw in keywords:
        if filename == kw:
            score += WIKI_SCORE_FILENAME_EXACT
        elif kw in filename:
            score += WIKI_SCORE_FILENAME_PARTIAL

        if kw in headings:
            score += WIKI_SCORE_HEADING

        count = text.count(kw)
        if count > 0:
            score += WIKI_SCORE_BODY
            score += min(count * WIKI_COUNT_WEIGHT, WIKI_COUNT_CAP)

    return score


# ─────────────────────────────────────
# 3. 위키 검색 (파일 직접 + 스코어링)
# ─────────────────────────────────────
def search_wiki(query: str) -> str | None:
    """
    마운트된 Obsidian wiki에서 질문과 관련된 노트를 찾아 주입 블록으로 만든다.

    DB를 쓰지 않고 파일을 직접 읽으므로 항상 최신 상태가 반영된다.
    wiki 하위만 대상으로 하고, 템플릿/인덱스/로그 등 메타 노트는 제외한다.
    임계값 미만은 버리고 상위 WIKI_TOP_K 개만 주입한다.

    Args:
        query: 사용자 입력 텍스트
    Returns:
        위키 참고 블록 텍스트. 관련 노트가 없거나 vault 미존재 시 None.
    """
    keywords = _extract_keywords(query)
    if not keywords:
        return None

    wiki_dir = Path(settings.WIKI_VAULT_PATH) / WIKI_SUBDIR
    if not wiki_dir.is_dir():
        logger.warning("wiki 경로 없음: %s", wiki_dir)
        return None

    # ──────────────────────────────────────
    # 3-1. 노트 순회하며 점수 계산
    # ──────────────────────────────────────
    scored: list[tuple[float, Path]] = []
    for path in wiki_dir.rglob("*.md"):
        stem = path.stem
        if stem in WIKI_EXCLUDE_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue

        score = _score_note(stem.lower(), text.lower(), keywords)
        if score >= WIKI_SCORE_THRESHOLD:
            scored.append((score, path))

    if not scored:
        return None

    # ──────────────────────────────────────
    # 3-2. 점수순 상위 K개 → 주입 블록 구성
    # ──────────────────────────────────────
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:WIKI_TOP_K]

    blocks = []
    for score, path in top:
        body = path.read_text(encoding="utf-8").strip()
        if len(body) > WIKI_MAX_CHARS:
            body = body[:WIKI_MAX_CHARS] + "\n...(생략)"
        blocks.append(f"### {path.stem}\n{body}")

    logger.debug("위키 검색: %s", [(round(s, 1), p.stem) for s, p in top])
    return "[참고: 위키 노트]\n" + "\n\n".join(blocks)