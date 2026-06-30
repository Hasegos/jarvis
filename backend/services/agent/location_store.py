# ─────────────────────────────────────
# 1. 사용자 현재 위치 메모리 저장소
# ─────────────────────────────────────
# 브라우저가 매 요청마다 보내는 GPS 좌표를 프로세스 메모리에 보관한다.
_location = {"lat": None, "lng": None}


# ─────────────────────
# 2. 위치 갱신
# ─────────────────────
def update_location(lat: float, lng: float) -> None:
    """
    현재 위치를 최신 GPS 좌표로 갱신한다.

    Args:
        lat: 위도
        lng: 경도
    """
    _location["lat"] = lat
    _location["lng"] = lng


# ─────────────────────
# 3. 위치 조회
# ─────────────────────
def get_location() -> dict | None:
    """
    저장된 현재 위치를 반환한다.

    Returns:
        {"lat": 위도, "lng": 경도} 복사본. 아직 수신 전이면 None.
    """
    if _location["lat"] is not None and _location["lng"] is not None:
        return _location.copy()
    return None