import re
from collections.abc import Iterator

from openai import APIConnectionError, APITimeoutError

from core.config import settings
from core.constant import SYSTEM_PROMPT
from services.lm_client import lm_client

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
# 3. 문장 스트림 분할
# ─────────────────────────────────────
def sentence_stream(tokens: Iterator[str]) -> Iterator[str]:
    """
    토큰 스트림을 문장 단위로 분할한다.

    파편(3자 미만)은 다음 문장에 합쳐 TTS 낭비를 방지한다.

    Args:
        tokens: LLM 토큰 스트림
    Yields:
        문장 단위 텍스트
    """
    buffer  = ""
    pending = ""

    for token in tokens:
        buffer += token

        # ──────────────────────────────────────
        # 3-1. 문장 경계 감지 + 분할
        # ──────────────────────────────────────
        while True:
            m = re.search(r"[.!?。~]+\s+|\n+", buffer)
            if not m:
                break
            sentence = (pending + buffer[: m.end()]).strip()
            buffer   = buffer[m.end():]

            # 3자 미만 파편은 다음 문장에 합침 — 짧은 TTS 호출 방지
            if len(sentence) < 3:
                pending = sentence + " "
            else:
                pending = ""
                yield sentence

    # ──────────────────────────────────────
    # 3-2. 스트림 종료 후 잔여 버퍼 처리
    # ──────────────────────────────────────
    tail = (pending + buffer).strip()
    if tail:
        yield tail


# ─────────────────────────────────────
# 4. 메시지 빌드 (시스템 프롬프트 주입)
# ─────────────────────────────────────
def _build_messages(history: list[dict]) -> list[dict]:
    """
    대화 히스토리 앞에 시스템 프롬프트를 prepend한다.

    Args:
        history: user/assistant 대화 히스토리
    Returns:
        시스템 프롬프트 포함 메시지 리스트
    """
    return [{"role": "system", "content": SYSTEM_PROMPT}] + history


# ─────────────────────
# 5. 블로킹 호출
# ─────────────────────
def chat(history: list[dict], use_thinking: bool = False) -> str:
    """
    블로킹 LLM 호출. 완성된 응답 텍스트를 반환한다.

    Args:
        history: user/assistant 대화 히스토리
    Returns:
        thinking 블록이 제거된 응답 텍스트
    Raises:
        RuntimeError: 연결 실패, 타임아웃, API 오류
    """
    try:
        response = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=_build_messages(history),
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=settings.LLM_TEMPERATURE,
            top_p=settings.LLM_TOP_P,
            max_tokens=settings.LLM_MAX_TOKENS,
            extra_body={
                "chat_template_kwargs" : {"enable_thinking": use_thinking },
                "top_k"          : settings.LLM_TOP_K,
                "repeat_penalty" : settings.LLM_REPEAT_PENALTY,
            },
        )
    except APIConnectionError:
        raise RuntimeError(
            "LM Studio에 연결할 수 없습니다. LM Studio가 실행 중인지 확인하세요."
        )
    except APITimeoutError:
        raise RuntimeError(
            f"LM Studio 응답 타임아웃 ({settings.LM_STUDIO_TIMEOUT}초 초과)."
        )
    except Exception as e:
        raise RuntimeError(f"LLM 호출 오류: {e}")

    content = response.choices[0].message.content or ""
    return strip_thinking(content)


# ─────────────────────
# 6. 스트리밍 호출
# ─────────────────────
def stream_chat(history: list[dict], use_thinking: bool  = False) -> Iterator[str]:
    """
    스트리밍 LLM 호출. 토큰을 순서대로 yield한다.

    Args:
        history: user/assistant 대화 히스토리
    Yields:
        LLM 응답 토큰 (thinking 블록 포함 원문)
    Raises:
        RuntimeError: 연결 실패, 타임아웃, 스트리밍 오류
    """
    try:
        stream = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=_build_messages(history),
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=settings.LLM_TEMPERATURE,
            top_p=settings.LLM_TOP_P,
            max_tokens=settings.LLM_MAX_TOKENS,
            extra_body={
                "chat_template_kwargs" : {"enable_thinking": use_thinking},
                "top_k"          : settings.LLM_TOP_K,
                "repeat_penalty" : settings.LLM_REPEAT_PENALTY,
            },
            stream=True,
        )
    except APIConnectionError:
        raise RuntimeError(
            "LM Studio에 연결할 수 없습니다. LM Studio가 실행 중인지 확인하세요."
        )
    except APITimeoutError:
        raise RuntimeError(
            f"LM Studio 응답 타임아웃 ({settings.LM_STUDIO_TIMEOUT}초 초과)."
        )
    except Exception as e:
        raise RuntimeError(f"LLM 호출 오류: {e}")

    # ──────────────────────────────────────
    # 6-1. 토큰 스트리밍
    # ──────────────────────────────────────
    try:
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                yield token
    except Exception as e:
        raise RuntimeError(f"LLM 스트리밍 오류: {e}")

# ─────────────────────
# 7. 세션 한 단어 요약
# ─────────────────────
def generate_summary(history: list[dict]) -> str:
    """
    대화 내용을 주제를 나타내는 한 단어로 요약한다.

    thinking 없이 max_tokens=20으로 빠르게 호출한다.

    Args:
        history: user/assistant 대화 히스토리
    Returns:
        한 단어 요약. 실패 시 빈 문자열.
    """
    conversation = "\n".join(
        f"{m['role']}: {m['content']}" for m in history
    )
    prompt = (
        "/no_think\n"
        "다음 대화의 핵심 주제를 한국어 명사 한 단어로만 답해. "
        "예시: 코딩, 날씨, 요리, 역사\n"
        "단어 하나만 출력해. 문장 금지. 설명 금지.\n\n"
        f"{conversation}"
    )
    try:
        response = lm_client.chat.completions.create(
            model=settings.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": "너는 대화 주제를 한 단어로 분류하는 분류기야."},
                {"role": "user",   "content": prompt},
            ],
            timeout=settings.LM_STUDIO_TIMEOUT,
            temperature=0.1,
            max_tokens=20,
        )
        content = response.choices[0].message.content or ""
        word = strip_thinking(content).strip().split()[0] if content.strip() else ""
        return word
    except Exception as e:
        raise RuntimeError(f"요약 생성 오류: {e}")