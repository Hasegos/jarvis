from typing import Literal

from core.constants.prompts import SYSTEM_PROMPT


# ──────────────────────────────────────
# 1. Agent 타입
# ──────────────────────────────────────
AgentType = Literal[
    "search", "memo", "file",
    "system", "nav", "screen", "general"
]


# ──────────────────────────────────────
# 2. 도구 → Agent 라우팅
# ──────────────────────────────────────
# _resolve_forced_tools 가 감지한 강제 도구 중 첫 도구로 Agent 를 결정한다.
AGENT_ROUTES: dict[str, AgentType] = {
    "web_search":  "search",
    "vault_write": "memo",
    "file_ops":    "file",
    "os_control":  "system",
    "navigation":  "nav",
}


# ──────────────────────────────────────
# 3. Agent별 역할 addendum
# ──────────────────────────────────────
# 각 Agent 프롬프트는 SYSTEM_PROMPT를 베이스로 두고 역할 지시만 덧붙인다.
_SEARCH_ADDENDUM = (
    "\n\nCurrent role: Search Agent. "
    "The user requested a web search. Call the web_search tool first, then state "
    "the key findings concisely. Do not answer from memory or past turns alone."
)
_MEMO_ADDENDUM = (
    "\n\nCurrent role: Memo Agent. "
    "The user wants to save a note. Call the vault_write tool, then briefly "
    "confirm what was saved."
)
_FILE_ADDENDUM = (
    "\n\nCurrent role: File Agent. "
    "The user requested a file operation. Call the file_ops tool, then state the "
    "result. Destructive actions are confirmed separately before running."
)
_SYSTEM_ADDENDUM = (
    "\n\nCurrent role: System Agent. "
    "The user wants to control the OS (launch an app, open a site, or check "
    "system info). Call the os_control tool, then state what was done."
)
_NAV_ADDENDUM = (
    "\n\nCurrent role: Navigation Agent. "
    "The user asked for directions or travel info. Call the navigation tool, then "
    "state distance, duration, and cost concisely."
)
_SCREEN_ADDENDUM = (
    "\n\nCurrent role: Screen Agent. "
    "An image of the user's screen is attached. Identify the activity and offer "
    "brief, practical advice only when genuinely helpful. Avoid obvious remarks."
)


# ──────────────────────────────────────
# 4. Agent → 시스템 프롬프트
# ──────────────────────────────────────
AGENT_PROMPTS: dict[AgentType, str] = {
    "search":  SYSTEM_PROMPT + _SEARCH_ADDENDUM,
    "memo":    SYSTEM_PROMPT + _MEMO_ADDENDUM,
    "file":    SYSTEM_PROMPT + _FILE_ADDENDUM,
    "system":  SYSTEM_PROMPT + _SYSTEM_ADDENDUM,
    "nav":     SYSTEM_PROMPT + _NAV_ADDENDUM,
    "screen":  SYSTEM_PROMPT + _SCREEN_ADDENDUM,
    "general": SYSTEM_PROMPT,
}