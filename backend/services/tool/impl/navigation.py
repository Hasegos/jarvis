import urllib.parse, httpx

from core.config import settings
from core.constants.tool import NAVIGATION_TIMEOUT, NAVIGATION_DEFAULT_ORIGIN
from core.logger import get_logger
from services.agent.location_store import get_location
from services.tool.tool_result import ok, err

logger = get_logger("tool.navigation")

# 위험도
RISK = "safe"

# 네이버 클라우드 플랫폼 지도 API 엔드포인트
_GEOCODE_URL = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
_DIRECTION_URL = "https://maps.apigw.ntruss.com/map-direction/v1/driving"
_REVERSE_GEOCODE_URL = "https://maps.apigw.ntruss.com/map-reversegeocode/v2/gc"

# GPS 지명을 못 구했을 때 출발지 표시용 기본 이름
_CURRENT_LOCATION_NAME = "현재 위치"


# ─────────────────────
# 1. 도구 스펙
# ─────────────────────
SPEC = {
    "type": "function",
    "function": {
        "name": "navigation",
        "description": (
            "두 지점 사이의 자동차 경로(거리·소요시간·통행료·유류비)를 네이버 지도로 "
            "조회하고, 브라우저에 길찾기 지도를 띄운다. "
            "'길찾기', '가는 길', '얼마나 걸려' 같은 요청에 사용한다. "
            "도착지(destination)는 사용자가 말한 그대로 넣는다. 절대 번역하거나 변환하지 마. "
            "출발지(origin)를 말하지 않으면 비워 둔다(기본 출발지가 적용된다)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "description": "도착지. 사용자가 말한 주소나 장소 이름 그대로.",
                },
                "origin": {
                    "type": "string",
                    "description": "출발지. 사용자가 말하지 않으면 비워 둔다.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["car"],
                    "description": "이동 수단. 현재 car(자동차)만 지원한다.",
                },
            },
            "required": ["destination"],
        },
    },
}


# ─────────────────────
# 2. 지오코딩 헬퍼
# ─────────────────────
def _geocode(client: httpx.Client, query: str, headers: dict) -> tuple[str, str] | None:
    """
    주소/장소 이름을 네이버 Geocoding API로 좌표(경도, 위도)로 변환한다.

    Args:
        client: 재사용할 httpx 동기 클라이언트
        query: 변환할 주소/장소 이름
        headers: 네이버 클라우드 인증 헤더
    Returns:
        (x, y) = (경도, 위도) 문자열 튜플. 결과가 없으면 None.
    """
    response = client.get(_GEOCODE_URL, params={"query": query}, headers=headers)
    response.raise_for_status()
    addresses = response.json().get("addresses") or []
    if not addresses:
        return None
    first = addresses[0]
    return first.get("x"), first.get("y")


# ─────────────────────────────────────
# 3. 역지오코딩 헬퍼 (좌표 → 지명)
# ─────────────────────────────────────
def _reverse_geocode(client: httpx.Client, lat, lng, headers: dict) -> str | None:
    """
    GPS 좌표를 네이버 Reverse Geocoding API로 도로명 주소(시·도 + 시·군·구 +
    읍·면·동 + 도로명 + 건물번호)로 바꾼다.

    Args:
        client: 재사용할 httpx 동기 클라이언트
        lat: 위도
        lng: 경도
        headers: 네이버 클라우드 인증 헤더
    Returns:
        "울산광역시 동구 일산동 봉수로 123" 형태의 주소. 결과가 없으면 None.
    """
    response = client.get(
        _REVERSE_GEOCODE_URL,
        params={"coords": f"{lng},{lat}", "output": "json", "orders": "roadaddr,legalcode"},
        headers=headers,
    )
    response.raise_for_status()
    results = response.json().get("results") or []
    by_name = {r.get("name"): r for r in results}

    # ────────────────────────
    # 3-1. 도로명 주소 우선
    # ────────────────────────
    road = by_name.get("roadaddr")
    if road:
        region = road.get("region") or {}
        land = road.get("land") or {}
        parts = [
            (region.get("area1") or {}).get("name") or "",
            (region.get("area2") or {}).get("name") or "",
            (region.get("area3") or {}).get("name") or "",
            land.get("name") or "",
            land.get("number1") or "",
        ]
        name = " ".join(p for p in parts if p)
        if name:
            return name

    # ────────────────────────
    # 3-2. 법정동 폴백
    # ────────────────────────
    legal = by_name.get("legalcode")
    if legal:
        region = legal.get("region") or {}
        parts = [
            (region.get("area1") or {}).get("name") or "",
            (region.get("area2") or {}).get("name") or "",
            (region.get("area3") or {}).get("name") or "",
        ]
        name = " ".join(p for p in parts if p)
        if name:
            return name

    return None


# ─────────────────────
# 4. 도구 실행
# ─────────────────────
def run(args: dict) -> str:
    """
    네이버 지도 API로 경로를 조회하고 결과를 JSON 문자열로 반환한다.

    Geocoding(주소→좌표) 2회 + Directions 5(좌표→경로) 1회를 호출한다.
    경로 조회 성공 시 네이버 지도 길찾기 페이지를 브라우저에 띄운다.

    Args:
        args: {"destination": 도착지, "origin"?: 출발지, "mode"?: "car"}
    Returns:
        {"origin", "destination", "distance_km", "duration_min",
        "toll_fare", "fuel_price"} 또는 {"error": ...} JSON 문자열
    """
    destination = (args.get("destination") or "").strip()
    if not destination:
        return err("도착지를 지정해 주세요.")
    
    origin_arg = (args.get("origin") or "").strip()

    if not settings.NAVER_MAP_CLIENT_ID or not settings.NAVER_MAP_CLIENT_SECRET:
        return err("네이버 지도 API 키가 설정되지 않았습니다.")

    headers = {
        "X-NCP-APIGW-API-KEY-ID": settings.NAVER_MAP_CLIENT_ID,
        "X-NCP-APIGW-API-KEY": settings.NAVER_MAP_CLIENT_SECRET,
    }

    try:
        with httpx.Client(timeout=NAVIGATION_TIMEOUT) as client:
            # ──────────────────────────────────────
            # 4-1. 출발지 결정 (명시 > GPS > 기본 출발지)
            # ──────────────────────────────────────
            location = None if origin_arg else get_location()
            if origin_arg:
                # ──────────────────────────────────────
                # 4-2. 명시 출발지 — Geocoding
                # ──────────────────────────────────────
                origin_coord = _geocode(client, origin_arg, headers)
                if origin_coord is None:
                    return err(f"'{origin_arg}'의 위치를 찾을 수 없습니다.")
                start_x, start_y = origin_coord
                origin_name = origin_arg
            elif location is not None:
                # ──────────────────────────────────────────────────
                # 4-3. GPS 좌표 — Geocoding 생략, 지명만 역지오코딩
                # ──────────────────────────────────────────────────
                start_x = str(location["lng"])
                start_y = str(location["lat"])
                try:
                    origin_name = _reverse_geocode(
                        client, location["lat"], location["lng"], headers
                    ) or _CURRENT_LOCATION_NAME
                except Exception as e:
                    logger.debug("navigation 역지오코딩 실패(무시): %s", e)
                    origin_name = _CURRENT_LOCATION_NAME
            else:
                # ──────────────────────────────────────────────────
                # 4-4. GPS 없음 — 기본 출발지 Geocoding
                # ──────────────────────────────────────────────────
                origin_coord = _geocode(client, NAVIGATION_DEFAULT_ORIGIN, headers)
                if origin_coord is None:
                    return err(f"'{NAVIGATION_DEFAULT_ORIGIN}'의 위치를 찾을 수 없습니다.")
                start_x, start_y = origin_coord
                origin_name = NAVIGATION_DEFAULT_ORIGIN

            # ──────────────────────────────────────
            # 4-5. 도착지 좌표 변환
            # ──────────────────────────────────────
            dest_coord = _geocode(client, destination, headers)
            if dest_coord is None:
                return err(f"'{destination}'의 위치를 찾을 수 없습니다.")
            goal_x, goal_y = dest_coord

            # ──────────────────────────────────────
            # 4-6. 경로 조회 (Directions 5, 실시간 빠른길)
            # ──────────────────────────────────────
            response = client.get(
                _DIRECTION_URL,
                params={
                    "start": f"{start_x},{start_y}",
                    "goal": f"{goal_x},{goal_y}",
                    "option": "trafast",
                },
                headers=headers,
            )
            response.raise_for_status()
            routes = (response.json().get("route") or {}).get("trafast") or []
            if not routes:
                return err("경로를 찾을 수 없습니다.")
            summary = routes[0].get("summary") or {}

            # ──────────────────────────────────────────────────
            # 4-7. 네이버 지도 길찾기 URL —  호출한 기기에서 연다
            # ──────────────────────────────────────────────────
            o_name = urllib.parse.quote(origin_name)
            d_name = urllib.parse.quote(destination)
            browse_url = (
                f"https://map.naver.com/v5/directions/"
                f"{start_x},{start_y},{o_name}/"
                f"{goal_x},{goal_y},{d_name}/-/car"
            )

            # ──────────────────────────────────────
            # 4-8. 결과 반환 (m→km, ms→분 변환)
            # ──────────────────────────────────────
            distance = summary.get("distance") or 0
            duration = summary.get("duration") or 0
            return ok(
                origin=origin_name,
                destination=destination,
                distance_km=round(distance / 1000, 1),
                duration_min=round(duration / 1000 / 60),
                toll_fare=summary.get("tollFare"),
                fuel_price=summary.get("fuelPrice"),
                open_url=browse_url,
            )

    except httpx.HTTPStatusError as e:
        logger.warning("navigation HTTP 오류: %s", e)
        return err("경로 검색 중 오류가 발생했습니다.")
    except httpx.ConnectError:
        logger.warning("navigation 네이버 지도 API 연결 실패")
        return err("네이버 지도 서버에 연결할 수 없습니다.")
    except httpx.TimeoutException:
        logger.warning("navigation 응답 타임아웃")
        return err("네이버 지도 응답이 지연됩니다.")
    except Exception as e:
        logger.warning("navigation 실패: %s", e)
        return err("경로 검색 중 오류가 발생했습니다.")


# ─────────────────────
# 5. 실행 미리보기
# ─────────────────────
def preview(args: dict) -> str:
    """
    confirm 전 "이렇게 됩니다"를 부작용 없이 보여준다.

    RISK=safe라 confirm은 면제되지만, 안내 일관성을 위해 제공한다.

    Args:
        args: 도구 인자 dict
    Returns:
        미리보기 문구
    """
    destination = (args.get("destination") or "").strip() or "도착지"
    origin = (args.get("origin") or "").strip()
    if not origin:
        origin = _CURRENT_LOCATION_NAME if get_location() else NAVIGATION_DEFAULT_ORIGIN
    return f"{origin}에서 {destination}까지 경로를 검색합니다."


# ─────────────────────
# 6. 도구 안내 문구
# ─────────────────────
def announce(args: dict) -> tuple[str, str]:
    """
    이 도구 실행을 (화면 표시용, 음성 안내용) 두 문구로 변환한다.

    Args:
        args: 모델이 생성한 도구 인자 dict
    Returns:
        (status_text, speech_text)
    """
    return ("경로 검색 중...", "경로를 검색하겠습니다.")