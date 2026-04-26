"""
간단한 TTL 기반 디스크 캐시.

용도: 매시간 실행되는 단타 모드에서, 자주 안 바뀌는 데이터(거시·공시·발굴)를
매번 새로 호출하지 않고 N시간동안 재사용.

캐시 위치: cache/ 폴더 (저장소에 포함되지 않음, .gitignore)
"""

import json
import time
from pathlib import Path
from typing import Any, Callable

from utils import logger

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)


def fetch_with_cache(name: str, fn: Callable, ttl_seconds: int, *args, **kwargs) -> Any:
    """
    name: 캐시 파일명 (예: 'macro', 'filings')
    fn: 데이터를 가져오는 함수
    ttl_seconds: 이 시간만큼은 캐시 재사용 (초 단위)

    캐시가 fresh하면 fn 호출 안 하고 캐시 반환.
    expire 됐으면 fn 호출, 결과를 캐시에 저장.
    fn이 예외 발생시키면 expired 캐시라도 stale로 반환.
    """
    path = CACHE_DIR / f"{name}.json"

    # fresh 캐시 있으면 그대로 반환
    if path.exists():
        age = time.time() - path.stat().st_mtime
        if age < ttl_seconds:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                logger.info(f"💾 [{name}] 캐시 hit ({int(age/60)}분 전)")
                return data
            except Exception as e:
                logger.warning(f"캐시 [{name}] 로드 실패 — 재호출: {e}")

    # fetch 시도
    try:
        logger.info(f"🌐 [{name}] 캐시 miss — 새로 fetch")
        result = fn(*args, **kwargs)
        # 결과 저장
        try:
            path.write_text(
                json.dumps(result, ensure_ascii=False, default=str, indent=1),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"캐시 [{name}] 저장 실패 (결과는 정상 반환): {e}")
        return result
    except Exception as e:
        logger.error(f"[{name}] fetch 실패: {e}")
        # stale 캐시라도 있으면 그거 반환
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                age = time.time() - path.stat().st_mtime
                logger.warning(f"💾 [{name}] stale 캐시 fallback ({int(age/60)}분 전)")
                return data
            except Exception:
                pass
        raise


def clear_cache(name: str = None) -> None:
    """특정 캐시 또는 전체 삭제."""
    if name:
        path = CACHE_DIR / f"{name}.json"
        if path.exists():
            path.unlink()
            logger.info(f"🗑 캐시 [{name}] 삭제")
    else:
        for p in CACHE_DIR.glob("*.json"):
            p.unlink()
        logger.info(f"🗑 모든 캐시 삭제")
