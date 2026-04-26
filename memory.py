"""
시그널 / 리포트 아카이브 + 재주입 (Agent Memory)

매일 리포트를 archive/ 폴더에 JSON으로 저장.
다음 리포트 작성 시 지난 N일치 시그널을 프롬프트에 같이 넣어서
Claude가 자기 과거 판단을 보고 self-correct 할 수 있게 함.

진짜 fine-tuning은 아니지만 functional하게는 학습 효과.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from config import MEMORY_LOOKBACK_DAYS
from utils import logger


ARCHIVE_DIR = Path(__file__).parent / "archive"
ARCHIVE_DIR.mkdir(exist_ok=True)


def save_today(record: Dict) -> Path:
    """
    오늘 리포트를 저장.
    record는 다음 키들 포함 권장:
      - data_summary: 그날 핵심 수치 (시장 지표, 거시 등)
      - signals: 그날 강조한 신호/판단들 (텍스트 리스트)
      - watchlist_snapshot: 관심 종목 그날 가격
      - generated_at: ISO 시각
    """
    today = datetime.now().strftime("%Y-%m-%d")
    path = ARCHIVE_DIR / f"{today}.json"

    record["saved_at"] = datetime.now().isoformat()

    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2, default=str)

    logger.info(f"📁 리포트 archive 저장: {path.name}")
    return path


def load_recent(days: int = MEMORY_LOOKBACK_DAYS) -> List[Dict]:
    """지난 N일치 archive 불러오기 (최신 → 과거 순)."""
    import re as _re
    cutoff = datetime.now().date() - timedelta(days=days)
    out = []
    for p in sorted(ARCHIVE_DIR.glob("*.json"), reverse=True):
        # YYYY-MM-DD 형식 파일만 처리. today_positions.json 같은 거 무시.
        if not _re.match(r"^\d{4}-\d{2}-\d{2}$", p.stem):
            continue
        try:
            file_date = datetime.strptime(p.stem, "%Y-%m-%d").date()
            if file_date < cutoff:
                break
            with open(p, "r", encoding="utf-8") as f:
                rec = json.load(f)
            rec["_file_date"] = p.stem
            out.append(rec)
        except Exception as e:
            logger.warning(f"archive {p.name} 로드 실패: {e}")
    return out


def build_memory_prompt(current_watchlist_prices: Dict[str, float] = None) -> Optional[str]:
    """
    프롬프트에 주입할 메모리 텍스트 생성.

    포맷:
      - 지난 N일 동안 발행한 주요 시그널
      - (가능하면) 그때 가격 vs 현재 가격으로 결과 검증

    아무것도 없으면 None 반환.
    """
    history = load_recent(days=MEMORY_LOOKBACK_DAYS)
    if not history:
        return None

    parts = [
        f"# 지난 {MEMORY_LOOKBACK_DAYS}일 너의 시그널 이력 (자기 검증용)",
        "이 데이터를 보고 너 자신의 판단 패턴이 잘 맞았는지 점검해라.",
        "특히 자주 틀린 패턴이 있으면 오늘은 더 보수적으로 다뤄라.",
        "",
    ]

    for rec in history[:MEMORY_LOOKBACK_DAYS]:
        date = rec.get("_file_date", "?")
        signals = rec.get("signals", [])
        snap = rec.get("watchlist_snapshot", {})

        parts.append(f"## {date}")
        if signals:
            for s in signals[:5]:  # 너무 길어지지 않게
                parts.append(f"- {s}")

        # 그날 가격 vs 현재 가격 비교 (있으면)
        if snap and current_watchlist_prices:
            comp_lines = []
            for ticker, then_price in snap.items():
                now_price = current_watchlist_prices.get(ticker)
                if now_price and then_price:
                    pct = (now_price - then_price) / then_price * 100
                    comp_lines.append(f"  · {ticker}: {then_price:.2f} → {now_price:.2f} ({pct:+.1f}%)")
            if comp_lines:
                parts.append("그날 → 오늘 가격:")
                parts.extend(comp_lines)
        parts.append("")

    return "\n".join(parts)


def extract_signals_from_html(html: str, max_signals: int = 8) -> List[str]:
    """
    생성된 리포트 HTML에서 핵심 시그널만 추출 (저장용).
    완전 정확할 필요 없음 — 대략 핵심만 텍스트로.
    """
    import re

    # 가장 단순한 방법: <li>, <h3>, <strong> 태그 텍스트 뽑기
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # h3, h4, li, strong 안의 텍스트
    candidates = re.findall(
        r"<(?:h3|h4|li|strong|b)[^>]*>(.*?)</(?:h3|h4|li|strong|b)>",
        text, flags=re.DOTALL | re.IGNORECASE,
    )
    cleaned = []
    for c in candidates:
        c = re.sub(r"<[^>]+>", "", c).strip()
        c = re.sub(r"\s+", " ", c)
        if 10 < len(c) < 300:
            cleaned.append(c)

    # 중복 제거 + 앞에서부터 max_signals개
    seen = set()
    out = []
    for c in cleaned:
        if c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) >= max_signals:
            break
    return out


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    history = load_recent()
    print(f"archive에 {len(history)}개 리포트 있음")
    for r in history[:5]:
        print(f"  {r.get('_file_date')}: 시그널 {len(r.get('signals', []))}개")
