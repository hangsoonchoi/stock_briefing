"""
공통 유틸 — 재시도, 로깅, 환경변수 검증
"""

import os
import sys
import time
import logging
from functools import wraps
from typing import Callable, List

logger = logging.getLogger("briefing")


def setup_logging(level: str = "INFO"):
    """루트 로거 설정. 콘솔에 깔끔하게 출력."""
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S")


def retry(max_attempts: int = 3, base_delay: float = 1.0):
    """
    데코레이터. 함수가 예외 발생하면 backoff로 재시도.
    yfinance 같은 자주 끊기는 API용.
    """
    def deco(fn: Callable):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            for i in range(max_attempts):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    delay = base_delay * (2 ** i)
                    logger.warning(
                        f"{fn.__name__} 시도 {i+1}/{max_attempts} 실패: {e} → {delay:.1f}초 후 재시도"
                    )
                    time.sleep(delay)
            logger.error(f"{fn.__name__} 최종 실패: {last_exc}")
            raise last_exc
        return wrapper
    return deco


def validate_env(required_keys: List[str], optional_keys: List[str] = None) -> dict:
    """
    필수 환경변수가 다 있는지 확인. 없으면 종료.
    optional은 경고만.
    """
    missing = [k for k in required_keys if not os.environ.get(k)]
    if missing:
        logger.error(f"필수 환경변수 누락: {', '.join(missing)}")
        logger.error("'.env' 파일 또는 시스템 환경변수에 설정해주세요.")
        sys.exit(1)

    status = {k: bool(os.environ.get(k)) for k in required_keys}
    if optional_keys:
        for k in optional_keys:
            present = bool(os.environ.get(k))
            status[k] = present
            if not present:
                logger.warning(f"선택 환경변수 {k} 없음 — 해당 기능 스킵됨")

    return status


def safe_get(d: dict, *keys, default=None):
    """중첩 dict 안전하게 꺼내기."""
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k)
        if d is None:
            return default
    return d


def fmt_pct(v) -> str:
    """+1.23% 형식. None이면 '—'."""
    if v is None:
        return "—"
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "—"


def fmt_num(v, places: int = 2) -> str:
    """천단위 콤마 + 소수자리. None이면 '—'."""
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{places}f}"
    except Exception:
        return "—"
