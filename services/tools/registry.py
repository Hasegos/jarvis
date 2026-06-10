from services.tools import web_search

# 등록된 도구 모듈 목록
_TOOLS = [
    web_search,
]

# LLM에 전달하는 전체 도구 스펙
TOOL_SPECS = [t.SPEC for t in _TOOLS]

# 이름 → 실행 함수 매핑 (디스패처용)
TOOL_HANDLERS = {t.SPEC["function"]["name"]: t.run for t in _TOOLS}