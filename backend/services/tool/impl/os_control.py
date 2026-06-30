import urllib.parse

import httpx

from core.config import settings
from core.constants.tool import OS_CONTROL_TIMEOUT
from core.logger import get_logger
from services.tool.tool_result import ok, err

logger = get_logger("tool.os_control")

# 위험도 
RISK = "safe"

# STT 음성 오인식 보정
TARGET_ALIASES = {
    "크롬":           "chrome",
    "엘엠스튜디오":     "lmstudio",
    "탐색기":         "explorer",
    "파일탐색기":      "explorer",
    "파일 탐색기":     "explorer",
    "vscode":         "code",
    "vs code":        "code",
    "브이에스코드":     "code",
    "비주얼스튜디오코드": "code",
    "메모장":         "notepad",
    "계산기":         "calc",
}

# 별칭 → 화면 표시용 한글 라벨
_APP_LABELS = {
    "notepad":  "메모장",
    "calc":     "계산기",
    "chrome":   "크롬",
    "explorer": "파일 탐색기",
    "code":     "VS Code",
    "obsidian": "옵시디언",
    "lmstudio": "LM Studio",
}

# browse 사이트별 검색 URL 템플릿
SITE_TEMPLATES = {
    "youtube":   "https://www.youtube.com/results?search_query={query}",
    "google":    "https://www.google.com/search?q={query}",
    "coupang":   "https://www.coupang.com/np/search?component=&q={query}&channel=user",
    "naver":     "https://search.naver.com/search.naver?query={query}",
    "naver_map": "https://map.naver.com/p/search/{query}",
    "instagram": "https://www.instagram.com",
}


# ─────────────────────
# 1. 도구 스펙
# ─────────────────────
SPEC = {
    "type": "function",
    "function": {
        "name": "os_control",
        "description": (
            "호스트 PC의 OS를 조작한다. "
            "사용자가 앱 실행을 요청하면(action='launch') 화이트리스트 안의 앱을 켠다 — "
            "메모장(notepad), 계산기(calc), 크롬(chrome), 파일 탐색기(explorer), "
            "VS Code(code), 옵시디언(obsidian), LM Studio(lmstudio). "
            "시스템 상태(CPU·메모리·디스크)를 물으면 action='system_info'로 조회한다. "
            "화이트리스트에 없는 앱은 실행할 수 없다. "
            "browse는 브라우저를 연다. site+query를 지정하면 코드가 URL을 조립한다. "
            "검색어(query)는 사용자가 말한 그대로 넣는다. 절대 번역하거나 변환하지 마. "
            "site 목록: youtube, google, coupang, naver, naver_map, instagram. "
            "site 없이 url만 지정하면 해당 URL을 직접 연다."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["launch", "system_info", "browse"],
                    "description": (
                        "launch=앱 실행, system_info=시스템 정보 조회, "
                        "browse=URL을 기본 브라우저로 열기."
                    ),
                },
                "target": {
                    "type": "string",
                    "description": (
                        "실행할 앱 별칭 (launch에서 사용). "
                        "notepad, calc, chrome, explorer, code, obsidian, lmstudio 중 하나."
                    ),
                },
                "site": {
                    "type": "string",
                    "description": (
                        "열 사이트 별칭 (browse에서 사용). "
                        "youtube, google, coupang, naver, naver_map, instagram 중 하나."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "검색어 (browse에서 site와 함께 사용). "
                        "사용자가 말한 그대로 넣는다. 절대 번역하거나 변환하지 마."
                    ),
                },
                "url": {
                    "type": "string",
                    "description": (
                        "열 페이지 주소 (browse에서 site/query로 처리 안 되는 경우). "
                        "http:// 또는 https:// 로 시작하는 완전한 URL."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}


# ─────────────────────
# 2. 도구 실행
# ─────────────────────
def run(args: dict) -> str:
    """
    호스트 서버(stt_server)에 OS 조작을 위임하고 결과를 JSON 문자열로 반환한다.

    Args:
        args: {"action": "launch"|"system_info", "target"?: 앱 별칭}
    Returns:
        launch     → {"ok": true, "pid": int, "label": str}
        system_info→ {"cpu_percent", "memory", "disk"}
        또는 {"error": ...} JSON 문자열
    """
    action = (args.get("action") or "").strip()

    try:
        with httpx.Client(timeout=OS_CONTROL_TIMEOUT) as client:
            # ──────────────────────────────────────
            # 2-1. launch — 앱 실행 위임
            # ──────────────────────────────────────
            if action == "launch":
                target = (args.get("target") or "").strip()
                if not target:
                    return err("실행할 앱을 지정해 주세요.")
                target = TARGET_ALIASES.get(target, target)
                response = client.post(
                    f"{settings.STT_SERVER_URL}/action",
                    json={"action": "launch", "target": target},
                )
                response.raise_for_status()
                data = response.json()
                return ok(launched=True, pid=data.get("pid"), label=data.get("label"))

            # ──────────────────────────────────────
            # 2-2. system_info — 시스템 정보 조회
            # ──────────────────────────────────────
            if action == "system_info":
                response = client.get(f"{settings.STT_SERVER_URL}/system-info")
                response.raise_for_status()
                data = response.json()
                return ok(
                    cpu_percent=data.get("cpu_percent"),
                    memory=data.get("memory"),
                    disk=data.get("disk"),
                )

            # ──────────────────────────────────────
            # 2-3. browse — URL을 기본 브라우저로 열기
            # ──────────────────────────────────────
            if action == "browse":
                site  = (args.get("site") or "").strip().lower()
                query = (args.get("query") or "").strip()
                url   = (args.get("url") or "").strip()
                # ──────────────────────────────────────
                # 2-3-1. site+query → 코드가 URL 조립.
                # ──────────────────────────────────────
                if site in SITE_TEMPLATES:
                    target_url = SITE_TEMPLATES[site].format(
                        query=urllib.parse.quote(query)
                    )
                # ──────────────────────────────────────
                # 2-3-2. site 없이 url만 → 그대로 연다.
                # ──────────────────────────────────────
                elif url:
                    target_url = url
                else:
                    return err("열 사이트나 URL을 지정해 주세요.")

                response = client.post(
                    f"{settings.STT_SERVER_URL}/browse",
                    json={"url": target_url},
                )
                response.raise_for_status()
                data = response.json()
                return ok(opened=True, url=data.get("url"))

        return err("지원하지 않는 작업입니다.")

    except httpx.HTTPStatusError as e:
        logger.warning("os_control HTTP 오류: %s", e)
        return err("요청을 처리할 수 없습니다. 허용되지 않은 앱이거나 호스트 오류입니다.")
    except httpx.ConnectError:
        logger.warning("os_control 호스트 연결 실패: %s", settings.STT_SERVER_URL)
        return err("호스트 서버에 연결할 수 없습니다. stt_server 실행 여부를 확인하세요.")
    except httpx.TimeoutException:
        logger.warning("os_control 호스트 응답 타임아웃")
        return err("호스트 서버 응답이 지연됩니다.")
    except Exception as e:
        logger.warning("os_control 실패: %s", e)
        return err("OS 조작 중 오류가 발생했습니다.")


# ─────────────────────
# 3. 실행 미리보기
# ─────────────────────
def preview(args: dict) -> str:
    """
    confirm 전 "이렇게 됩니다"를 부작용 없이 보여준다.

    Args:
        args: 도구 인자 dict
    Returns:
        미리보기 문구
    """
    action = (args.get("action") or "").strip()
    if action == "launch":
        target = (args.get("target") or "").strip()
        label = _APP_LABELS.get(target, target or "앱")
        return f"{label} 앱을 실행합니다."
    if action == "system_info":
        return "시스템 정보를 조회합니다."
    if action == "browse":
        site  = (args.get("site") or "").strip().lower()
        query = (args.get("query") or "").strip()
        url   = (args.get("url") or "").strip()
        if site in SITE_TEMPLATES and query:
            return f"{site}에서 '{query}' 검색 페이지를 엽니다."
        return f"{url or site or '웹'} 페이지를 엽니다."
    return "OS 작업을 진행합니다."


# ─────────────────────
# 4. 도구 안내 문구
# ─────────────────────
def announce(args: dict) -> tuple[str, str]:
    """
    이 도구 실행을 (화면 표시용, 음성 안내용) 두 문구로 변환한다.

    Args:
        args: 모델이 생성한 도구 인자 dict
    Returns:
        (status_text, speech_text)
    """
    action = (args.get("action") or "").strip()
    if action == "system_info":
        return ("시스템 조회 중...", "시스템 정보를 확인하겠습니다.")
    if action == "browse":
        return ("페이지 여는 중...", "페이지를 열겠습니다.")
    return ("앱 실행 중...", "앱을 실행하겠습니다.")