import logging, sys


# ─────────────────────────────────────
# 1. 공용 로거 설정
# ─────────────────────────────────────
def get_logger(name: str) -> logging.Logger:
    """
    구조화된 로거를 반환한다.

    uvicorn 로그 포맷과 맞추기 위해 StreamHandler + 동일 포맷 사용.

    Args:
        name: 로거 이름 (보통 모듈명)
    Returns:
        설정된 Logger 인스턴스
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(levelname)s: %(name)s | %(message)s")
    )
    logger.addHandler(handler)
    logger.propagate = False

    return logger