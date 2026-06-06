import re
from collections.abc import Iterator

from openai import APIConnectionError, APITimeoutError

from core.config import settings
from core.constant import SYSTEM_PROMPT
from services.lm_client import lm_client


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
# 2. 문장 스트림 분할
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
        # 2-1. 문장 경계 감지 + 분할
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
    # 2-2. 스트림 종료 후 잔여 버퍼 처리
    # ──────────────────────────────────────
    tail = (pending + buffer).strip()
    if tail:
        yield tail


# ─────────────────────────────────────
# 3. 메시지 빌드 (시스템 프롬프트 주입)
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
# 4. 블로킹 호출
# ─────────────────────
def chat(history: list[dict]) -> str:
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
                "enable_thinking": True,
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
# 5. 스트리밍 호출
# ─────────────────────
def stream_chat(history: list[dict]) -> Iterator[str]:
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
                "enable_thinking": True,
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
    # 5-1. 토큰 스트리밍
    # ──────────────────────────────────────
    try:
        for chunk in stream:
            token = chunk.choices[0].delta.content or ""
            if token:
                yield token
    except Exception as e:
        raise RuntimeError(f"LLM 스트리밍 오류: {e}")