# ──────────────────────────────────────
# 1. 시스템 프롬프트
# ──────────────────────────────────────
SYSTEM_PROMPT = (
    "Your name is JARVIS, an AI assistant dedicated to serving the user, modeled after Iron Man's JARVIS. "
    "Do not roleplay or create other personas. Address the user strictly as 'Iron' or 'Iron-nim'. Never use 'Stark' or 'Tony'.\n\n"
    "Response Rules:\n"
    "- General conversation: Answer naturally in 1-2 sentences. Focus only on the core message.\n"
    "- Complex requests (code, analysis, procedures): Provide detailed explanations as needed.\n"
    "- Prohibited: Self-introductions, filler words (e.g., 'Of course', 'Great question'), and meta-commentary.\n"
    "- Honesty: Say 'I don't know' if unsure. Never hallucinate or assume unrequested details.\n"
    "- Tool usage: State execution results naturally (e.g., 'Opened Notepad', 'Here are the search results').\n"
    "- Formatting: Output raw text only. Strictly NO markdown (*, #, lists), emojis, or symbols, as outputs are read aloud.\n"
    "- Image input: Identify user activity and offer concise, practical advice only when genuinely helpful. Avoid obvious remarks."
)

# ──────────────────────────────────────
# 2. 기억 프로필 갱신 추출 프롬프트
# ──────────────────────────────────────
PROFILE_EXTRACT_PROMPT = """\
Update the user's long-term memory profile based on the recent conversation.
Sections: {sections}

Identify NEW or CHANGED durable facts (identity, preferences, hobbies, schedule, projects). Ignore transient chit-chat.

Rules:
- Output ONLY a raw JSON array. No prose, no markdown fences.
- Format: {{"section": "<section_name>", "content": "<COMPLETE updated markdown for the section>"}}
- Only include CHANGED sections. If no changes, return [].
- "content" must be the ENTIRE updated section in ENGLISH, using "- key: value" bullet format.
- NEVER delete existing facts. Retain all current lines; only ADD or UPDATE.
- If FORCED_SECTION is not "(none)", force ALL updates into that exact section.
- Otherwise, map to:
  * Identity: Name, pets, family, location.
  * Preferences: Likes, dislikes, taste.
  * Hobbies: Games, interests, leisure.
  * Schedule: Appointments, dates, plans.
  * Projects: Work, development, tasks.

CURRENT PROFILE:
{profile}

RECENT CONVERSATION:
{conversation}

FORCED_SECTION: {forced_section}

JSON:"""


# ──────────────────────────────────────
# 3. 메모 정리 프롬프트 (vault_write)
# ──────────────────────────────────────
MEMO_ORGANIZE_PROMPT = """\
Organize the raw memo into a clean Obsidian note format.

Rules:
- Output ONLY a raw JSON object. No prose, no markdown fences.
- Format: {{"title": "<Korean noun phrase, under 30 chars>", "category": "<one of: {categories}>", "tags": ["1-3 Korean keywords"], "body": "<Korean '- ' bullet lines>"}}
- category: Use "{default_category}" if unsure.
- body: Preserve ALL facts, numbers, and names from the memo. Do not invent information.
- Strictly exclude any request phrases like "메모해줘" from the output.

MEMO:
{content}

JSON:"""


# ──────────────────────────────────────
# 4. 이미지 분석 프롬프트 (vlm)
# ──────────────────────────────────────
SCREEN_ANALYSIS_PROMPT = (
    "Analyze this screenshot, identify the user's current activity, and provide brief advice.\n\n"
    "Criteria:\n"
    "- Error/Exception: Explain cause and fix in 1-2 sentences.\n"
    "- Coding: Suggest improvements, potential bugs, or better approaches in 1-2 sentences.\n"
    "- Browsing/Reading: Provide 1 helpful tip/insight in 1 sentence.\n"
    "- Desktop/Idle or No change from previous screen: Return an empty string.\n\n"
    "Output: 1-2 sentences in Korean if advice applies; otherwise, strictly return an empty string."
)