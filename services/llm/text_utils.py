import re

_MD_BOLD_RE     = re.compile(r'\*\*([^*\n]+)\*\*')
_MD_ITALIC_RE   = re.compile(r'\*([^*\n]+)\*|_([^_\n]+)_')
_MD_HEADER_RE   = re.compile(r'^#{1,6}\s+', re.MULTILINE)
_MD_LIST_RE     = re.compile(r'^[ \t]*[-*+]\s+', re.MULTILINE)
_MD_INLINE_RE   = re.compile(r'`([^`\n]+)`')


# ─────────────────────
# 1. thinking 블록 제거
# ─────────────────────
def strip_thinking(text: str) -> str:
    """
    <think>...</think> 블록을 제거한다.

    Args:
        text: LLM 원본 응답
    Returns:
        thinking 블록이 제거된 텍스트
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# ─────────────────────────────────────
# 2. 마크다운 강조 기호 제거
# ─────────────────────────────────────
def strip_markdown(text: str) -> str:
    """
    LLM 응답에서 **bold**, ## 헤더 기호를 제거한다.

    코드 블록은 건드리지 않는다.

    Args:
        text: LLM 응답 텍스트
    Returns:
        마크다운 기호가 제거된 텍스트
    """
    text = _MD_BOLD_RE.sub(r'\1', text)
    text = _MD_ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = _MD_HEADER_RE.sub('', text)
    text = _MD_LIST_RE.sub('', text)
    text = _MD_INLINE_RE.sub(r'\1', text)
    return text.strip()


# ─────────────────────────────────────
# 3. 스트리밍 think 필터
# ─────────────────────────────────────
class _StreamThinkFilter:
    """
    스트리밍 토큰에서 <think>...</think> 구간을 걸러내는 상태 보존 필터.

    thinking ON 시 사고 과정이 사용자에게 노출되지 않도록, </think> 가
    나올 때까지 토큰을 버퍼에 보류한다. think 블록이 아니면 즉시 통과시킨다.
    """
    def __init__(self):
        self._done = False
        self._buf  = ""

    def feed(self, token: str) -> str:
        """토큰을 받아 출력 가능한 부분만 반환한다 (보류 중이면 빈 문자열)."""
        if self._done:
            return token
        self._buf += token
        stripped = self._buf.lstrip()
        if not stripped:
            return ""
        if not stripped.startswith("<"):
            self._done = True
            out, self._buf = self._buf, ""
            return out
        if not stripped.startswith("<think"):
            if len(stripped) >= 6:
                self._done = True
                out, self._buf = self._buf, ""
                return out
            return ""
        end = self._buf.find("</think>")
        if end == -1:
            return ""
        self._done = True
        out = self._buf[end + len("</think>"):]
        self._buf = ""
        return out.lstrip("\n")

    def flush(self) -> str:
        """
        스트림 종료 시 호출. 미완성 think 블록(</think> 미도래)에 갇혀
        출력이 비는 것을 방어한다. think 태그를 제거한 잔여 텍스트를 반환한다.
        """
        if self._done or not self._buf:
            return ""
        leftover = strip_thinking(self._buf).strip()
        self._buf = ""
        self._done = True
        return leftover