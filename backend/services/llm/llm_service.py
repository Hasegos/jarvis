from core.config import settings
from core.constants.prompts import SYSTEM_PROMPT, SCREEN_ANALYSIS_PROMPT
from core.logger import get_logger
from services.llm.lm_client import lm_client
from services.llm.text_utils import strip_thinking

logger = get_logger("llm_service")


# ─────────────────────────────────────
# 1. 메시지 빌드 (시스템 프롬프트 + 컨텍스트 주입)
# ─────────────────────────────────────
def _build_messages(
    history: list[dict],
    context: str | None = None,
    use_thinking: bool = False,
    force_search: bool = False,
    system_prompt: str | None = None,
) -> list[dict]:
    """
    대화 히스토리 앞에 시스템 프롬프트를 prepend한다.

    컨텍스트(프로필+위키+RAG 합본)가 있으면 시스템 프롬프트 뒤
    별도 system 메시지로 주입한다. 강제검색 지시는 stale history 에
    묻히지 않도록 메시지 맨 끝(user 턴 뒤)에 붙인다.

    Args:
        history      : user/assistant 대화 히스토리
        context      : 프로필/위키/RAG 참고 블록. None이면 주입 안 함.
        use_thinking : thinking 활성화 여부 (호환용 인자, 현재 메시지 구성엔 미반영).
        force_search : True 면 web_search 강제 지시를 맨 끝에 주입.
        system_prompt: Agent별 시스템 프롬프트. None이면 기본 SYSTEM_PROMPT 사용.
    Returns:
        시스템 프롬프트(+컨텍스트, +강제검색 지시) 포함 메시지 리스트
    """
    base_prompt = system_prompt or SYSTEM_PROMPT
    messages = [{"role": "system", "content": base_prompt}]
    if context:
        messages.append({"role": "system", "content": context})
    messages = messages + history
    if force_search:
        messages.append({
            "role": "system",
            "content": (
                "사용자가 검색을 명시적으로 요청했습니다. "
                "과거 대화나 이전 답변에 비슷한 내용이 있더라도 신뢰하지 말고, "
                "반드시 web_search 도구를 먼저 호출해 최신 정보를 확인한 뒤 답하세요."
            ),
        })
    return messages


# ─────────────────────────────────────
# 2. LLM 공통 호출 파라미터
# ─────────────────────────────────────
def build_llm_kwargs(use_thinking: bool, max_tokens: int) -> dict:
    """
    채팅 LLM 호출에 공통으로 들어가는 kwargs 를 한곳에서 만든다.

    에이전트 루프 4곳(블로킹/스트리밍 × 본루프/폴백)에 중복돼 있던
    파라미터를 통합해, 값 변경 시 한 곳만 고치면 되게 한다.

    Args:
        use_thinking: thinking 활성화 여부
        max_tokens  : 답변 토큰 상한
    Returns:
        chat.completions.create 에 펼쳐 넣을 kwargs dict
    """
    return {
        "model": settings.LM_STUDIO_MODEL,
        "timeout": settings.LM_STUDIO_TIMEOUT,
        "temperature": settings.LLM_TEMPERATURE,
        "top_p": settings.LLM_TOP_P,
        "max_tokens": max_tokens,
        "extra_body": {
            "chat_template_kwargs": {"enable_thinking": use_thinking},
            "top_k": settings.LLM_TOP_K,
            "repeat_penalty": settings.LLM_REPEAT_PENALTY,
        },
    }


# ─────────────────────
# 3. 세션 한 단어 요약
# ─────────────────────
def generate_summary(history: list[dict]) -> str:
    """
    대화 내용을 주제를 나타내는 한 단어로 요약한다.

    Args:
        history: user/assistant 대화 히스토리
    Returns:
        한 단어 요약. 실패 시 빈 문자열.
    Raises:
        RuntimeError: 요약 생성 실패 (원본 예외는 로그에만 남김)
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
        if not response.choices:
            raise RuntimeError("요약 응답이 비어 있습니다.")
        content = response.choices[0].message.content or ""
        word = strip_thinking(content).strip().split()[0] if content.strip() else ""
        return word
    except RuntimeError:
        raise
    except Exception as e:
        logger.warning("요약 생성 오류: %s", e)
        raise RuntimeError("요약 생성 중 오류가 발생했습니다.") from None


# ──────────────────────────────────────
# 4. VLM 멀티모달 메시지 빌드
# ──────────────────────────────────────
def build_vlm_messages(
    user_text : str,
    image_b64 : str,
    context   : str | None = None,
    system_prompt: str | None = None,
) -> list[dict]:
    """
    이미지 + 텍스트를 OpenAI Vision 형식 메시지로 빌드한다.
    Qwen2.5-VL은 content를 list[dict] 형태로 받는다.

    Args:
        user_text    : 사용자 입력 텍스트
        image_b64    : base64 인코딩 이미지
        context      : 프로필/위키/RAG 참고 블록. None이면 주입 안 함.
        system_prompt: Agent별 시스템 프롬프트. None이면 기본 SYSTEM_PROMPT 사용.
    """
    base_prompt = system_prompt or SYSTEM_PROMPT
    messages = [{"role": "system", "content": base_prompt}]
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({
        "role": "user",
        "content": [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_b64}"},
            },
            {"type": "text", "text": user_text},
        ],
    })
    return messages


# ──────────────────────────────────────
# 5. 화면 분석 단독 호출
# ──────────────────────────────────────
def analyze_screen(image_b64: str) -> str:
    """
    스크린샷을 VLM에 보내 화면 상태를 분석한다. 비스트리밍.
    할 말 없으면 빈 문자열 반환.
    """
    if not settings.VLM_ENABLED:
        return ""
    try:
        messages = build_vlm_messages(SCREEN_ANALYSIS_PROMPT, image_b64)
        response = lm_client.chat.completions.create(
            model       = settings.LM_STUDIO_MODEL,
            messages    = messages,
            timeout     = settings.LM_STUDIO_TIMEOUT,
            temperature = 0.3,
            max_tokens  = 150,
        )
        if not response.choices:
            return ""
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("화면 분석 오류: %s", e)
        return ""