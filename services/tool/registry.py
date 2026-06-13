from services.tool.impl import web_search
from services.tool.impl import vault_write

# 등록된 도구 모듈 목록
_TOOLS = [
    web_search,
    vault_write
]

# LLM에 전달하는 전체 도구 스펙
TOOL_SPECS = [t.SPEC for t in _TOOLS]

# 이름 → 실행 함수 매핑 (디스패처용)
TOOL_HANDLERS = {t.SPEC["function"]["name"]: t.run for t in _TOOLS}

# 이름 → 전체 SPEC 매핑 (강제 도구 단일 노출용)
TOOL_SPEC_BY_NAME = {t.SPEC["function"]["name"]: t.SPEC for t in _TOOLS}

# 이름 → 안내 문구 함수 매핑
TOOL_ANNOUNCERS = {
    t.SPEC["function"]["name"]: t.announce
    for t in _TOOLS
    if hasattr(t, "announce")
}


# ─────────────────────────────────────
# 1. 도구명으로 단일 SPEC 리스트 조회
# ─────────────────────────────────────
def get_forced_tool_specs(name: str) -> list[dict]:
    """
    강제 도구 1개만 LLM에 노출하기 위한 SPEC 리스트를 만든다.

    Args:
        name: 강제할 도구 이름
    Returns:
        해당 도구 SPEC 한 개를 담은 리스트. 이름이 없으면 빈 리스트.
    """
    spec = TOOL_SPEC_BY_NAME.get(name)
    return [spec] if spec else []