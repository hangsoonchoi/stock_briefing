"""
포지션 추적기 — 아침 풀 모드에서 추천한 종목들을 매시간 단타 모드에서 추적.

흐름:
1. 풀 모드(아침 7:30) → 생성된 HTML에서 stock-card 파싱 → archive/today_positions.json 저장
2. 단타 모드(매시간) → today_positions 로드 → 각 종목 현재가 yfinance → 변동률·상태 계산
3. analyzer가 결과 보고 "매도 검토" / "보유" / "손절 임박" 등 판단

stock-card에 다음 속성 필수:
- data-ticker: yfinance 티커
- data-recommended-at: 추천 시 가격 (숫자)
- data-target1: 1차 익절가
- data-target2: 2차 익절가
- data-stop: 손절가
- data-section: "simulation" / "candidate" / "watch" / "discovery"
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from utils import logger, retry


ARCHIVE_DIR = Path(__file__).parent / "archive"
ARCHIVE_DIR.mkdir(exist_ok=True)
POSITIONS_PATH = ARCHIVE_DIR / "today_positions.json"
# 사용자가 실제로 매수한 종목 목록 (수동 편집)
USER_HOLDINGS_PATH = Path(__file__).parent / "user_holdings.json"


def extract_positions_from_html(html: str) -> List[Dict]:
    """
    HTML에서 stock-card 데이터 추출.
    BeautifulSoup 사용 — Claude 출력은 잘 정형화돼 있음.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 미설치 — pip install beautifulsoup4")
        return []

    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all(class_="stock-card")
    positions = []

    for card in cards:
        # 데이터 속성 추출
        ticker = card.get("data-ticker") or ""
        rec_at = card.get("data-recommended-at") or ""
        target1 = card.get("data-target1") or ""
        target2 = card.get("data-target2") or ""
        stop = card.get("data-stop") or ""
        section = card.get("data-section") or ""

        if not ticker:
            continue

        # 티커 검증 — 한국=숫자.KS/.KQ, 미국=대문자만
        import re as _re
        is_kr = bool(_re.match(r"^\d{6}\.(KS|KQ)$", ticker))
        is_us = bool(_re.match(r"^[A-Z]{1,5}$", ticker))
        if not (is_kr or is_us):
            logger.warning(f"잘못된 ticker 무시: {ticker} (회사명 또는 형식 오류)")
            continue

        # 종목명 추출
        name_el = card.find(class_="stock-name") or card.find("h3")
        name = name_el.get_text(strip=True) if name_el else ticker

        # 비중 추출
        alloc_el = card.find(class_="stock-allocation")
        alloc = alloc_el.get_text(strip=True) if alloc_el else ""

        # 카드 클래스에서 종류 추정
        card_classes = card.get("class", [])
        card_type = "candidate"
        if "discovery" in card_classes:
            card_type = "discovery"
        elif "watch" in card_classes:
            card_type = "watch"
        elif "warning" in card_classes:
            card_type = "warning"

        def _num(s):
            try:
                return float(re.sub(r"[^\d.]", "", str(s))) if s else None
            except Exception:
                return None

        positions.append({
            "ticker": ticker,
            "name": name,
            "section": section or card_type,
            "card_type": card_type,
            "allocation": alloc,
            "recommended_at": _num(rec_at),
            "target_1": _num(target1),
            "target_2": _num(target2),
            "stop_loss": _num(stop),
        })

    return positions


def save_today_positions(positions: List[Dict]) -> Path:
    """오늘자 positions 저장. 풀 모드에서 호출."""
    record = {
        "saved_at": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "positions": positions,
    }
    POSITIONS_PATH.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"📌 today_positions 저장 — {len(positions)}개 포지션")
    return POSITIONS_PATH


def load_today_positions() -> Optional[Dict]:
    """오늘자 positions 로드. 없거나 어제 거면 None."""
    if not POSITIONS_PATH.exists():
        return None
    try:
        rec = json.loads(POSITIONS_PATH.read_text(encoding="utf-8"))
        today = datetime.now().strftime("%Y-%m-%d")
        if rec.get("date") != today:
            logger.info(f"today_positions가 어제({rec.get('date')}) 거 — 무시")
            return None
        return rec
    except Exception as e:
        logger.warning(f"today_positions 로드 실패: {e}")
        return None


@retry(max_attempts=2, base_delay=0.5)
def _yf_current(ticker: str) -> Optional[Dict]:
    import yfinance as yf
    tk = yf.Ticker(ticker)
    # 5분봉 1일치 — 현재가용
    hist = tk.history(period="1d", interval="5m")
    if hist is None or hist.empty:
        # 일봉 fallback
        hist = tk.history(period="2d", interval="1d")
        if hist is None or hist.empty:
            return None
    last = hist.iloc[-1]
    return {
        "current_price": round(float(last["Close"]), 2),
        "as_of": str(last.name),
    }


def evaluate_positions() -> List[Dict]:
    """
    오늘자 포지션 각각에 대해 현재가 → 평가.
    반환: 각 포지션 + 현재가, 변동률, 상태 라벨.
    """
    rec = load_today_positions()
    if not rec:
        return []

    out = []
    for p in rec.get("positions", []):
        ticker = p["ticker"]
        rec_at = p.get("recommended_at")
        if not rec_at:
            continue

        cur = _yf_current(ticker)
        if not cur:
            p["current_price"] = None
            p["change_pct"] = None
            p["status"] = "데이터 없음"
            out.append(p)
            time.sleep(0.15)
            continue

        cp = cur["current_price"]
        chg_pct = (cp - rec_at) / rec_at * 100 if rec_at else 0

        # 상태 라벨
        target1 = p.get("target_1")
        target2 = p.get("target_2")
        stop = p.get("stop_loss")
        status = "보유"
        action = "hold"

        if stop and cp <= stop:
            status = "🚨 손절 도달"
            action = "stop_loss_hit"
        elif stop and cp <= stop * 1.02:  # 손절선 2% 이내
            status = "⚠️ 손절 임박"
            action = "near_stop"
        elif target2 and cp >= target2:
            status = "🎯 2차 목표 도달"
            action = "take_profit_2"
        elif target1 and cp >= target1:
            status = "✅ 1차 목표 도달"
            action = "take_profit_1"
        elif chg_pct <= -3:
            status = "📉 단기 하락"
            action = "watch_decline"
        elif chg_pct >= 3:
            status = "📈 상승 중"
            action = "watch_rise"

        p["current_price"] = cp
        p["change_pct"] = round(chg_pct, 2)
        p["status"] = status
        p["action"] = action
        out.append(p)
        time.sleep(0.15)

    return out


def load_user_holdings() -> List[Dict]:
    """user_holdings.json — 사용자가 실제로 매수한 종목들."""
    if not USER_HOLDINGS_PATH.exists():
        return []
    try:
        rec = json.loads(USER_HOLDINGS_PATH.read_text(encoding="utf-8"))
        return rec.get("holdings", [])
    except Exception as e:
        logger.warning(f"user_holdings 로드 실패: {e}")
        return []


def evaluate_user_holdings() -> List[Dict]:
    """사용자 실제 보유 종목들 — 매입가 vs 현재가, 손익, 액션 권고."""
    holdings = load_user_holdings()
    if not holdings:
        return []

    out = []
    for h in holdings:
        ticker = h.get("ticker")
        purchase_price = h.get("purchase_price")
        if not ticker or not purchase_price:
            continue

        cur = _yf_current(ticker)
        if not cur:
            # 데이터 못 가져왔지만 그래도 기본 정보 반환
            out.append({**h, "current_price": None, "change_pct": None, "status": "데이터 없음"})
            time.sleep(0.15)
            continue

        cp = cur["current_price"]
        chg_pct = (cp - purchase_price) / purchase_price * 100

        qty = h.get("quantity", 1)
        cost = purchase_price * qty
        value = cp * qty
        pnl = value - cost

        # 상태 라벨
        stop = h.get("stop_loss")
        target1 = h.get("target_1")
        target2 = h.get("target_2")

        status = "📌 보유 중"
        action = "hold"
        if stop and cp <= stop:
            status = "🚨 손절선 도달 — 즉시 매도 검토"
            action = "stop_loss_hit"
        elif chg_pct <= -10:
            status = "🚨 -10% 이상 큰 손실 — 매도 강하게 검토"
            action = "consider_stop_loss"
        elif chg_pct <= -7:
            status = "⚠️ -7% 이상 손실 — 손절 검토 시점"
            action = "near_stop"
        elif target2 and cp >= target2:
            status = "🎯 2차 목표 도달 — 대부분 매도 검토"
            action = "take_profit_2"
        elif target1 and cp >= target1:
            status = "✅ 1차 목표 도달 — 일부 매도 검토"
            action = "take_profit_1"
        elif chg_pct >= 5:
            status = "📈 5%+ 상승 중 — 익절선 근접 시 행동"
            action = "watch_rise"
        elif chg_pct <= -3:
            status = "📉 단기 하락 (-3~-7%) — 관찰"
            action = "watch_decline"

        out.append({
            "ticker": ticker,
            "name": h.get("name", ticker),
            "quantity": qty,
            "purchase_price": purchase_price,
            "purchased_at": h.get("purchased_at"),
            "current_price": cp,
            "change_pct": round(chg_pct, 2),
            "cost": int(cost),
            "value": int(value),
            "pnl": int(pnl),
            "stop_loss": stop,
            "target_1": target1,
            "target_2": target2,
            "status": status,
            "action": action,
        })
        time.sleep(0.15)

    return out


def format_user_holdings_for_prompt(evaluated: List[Dict]) -> str:
    """analyzer 프롬프트용 — 본인 실제 보유 종목 평가."""
    if not evaluated:
        return ""

    parts = [
        "## 🎯 본인 실제 보유 종목 (user_holdings.json — 사용자 직접 매수)",
        "**가장 중요. 사용자가 실제 돈 넣은 종목들.**",
        "각 종목마다 stock-card position-update 형식으로 출력 + 매입 정보 + 현재 손익 + 명확한 권고:",
        "",
    ]

    total_cost = 0
    total_value = 0
    for p in evaluated:
        cp = p.get("current_price")
        chg = p.get("change_pct")
        pnl = p.get("pnl") or 0
        total_cost += p.get("cost") or 0
        total_value += p.get("value") or 0

        cp_s = f"{cp:,}" if cp else "—"
        chg_s = f"{chg:+.2f}%" if chg is not None else "—"
        pnl_s = f"{pnl:+,}원"

        parts.append(f"### {p['name']} ({p['ticker']}) — {p['quantity']}주 보유")
        parts.append(
            f"- 매입가 {p['purchase_price']:,}원 / 현재가 {cp_s} ({chg_s}) | 평가손익 {pnl_s}"
        )
        parts.append(
            f"- 매입일 {p.get('purchased_at', '?')} / 투자금 {p.get('cost', 0):,}원 / "
            f"현재가치 {p.get('value', 0):,}원"
        )
        parts.append(f"- 시스템 평가: **{p.get('status')}**")
        if p.get("stop_loss"):
            parts.append(f"- 설정된 손절가: {p['stop_loss']:,}원 / 1차 목표: {p.get('target_1', '?')} / 2차: {p.get('target_2', '?')}")
        parts.append("")

    if total_cost:
        total_pnl = total_value - total_cost
        total_pct = total_pnl / total_cost * 100
        parts.append(
            f"### 📊 전체 포트폴리오\n"
            f"- 총 투자금 {total_cost:,}원 / 현재가치 {total_value:,}원 / "
            f"평가손익 {total_pnl:+,}원 ({total_pct:+.2f}%)"
        )
        parts.append("")

    parts.append(
        "**카드별로 명확한 권고 작성:**\n"
        "- 손절선 도달/임박 → '즉시 매도 검토' (warning 카드, 빨간 강조)\n"
        "- 익절 도달 → '일부/대부분 매도 검토' (discovery 카드)\n"
        "- 보유 → '계속 보유, 다음 갱신까지 관찰'\n"
        "이유도 같이 (왜 이 권고인지 — 현재 시장, 종목 뉴스, 기술 흐름)"
    )

    return "\n".join(parts)


def format_positions_for_prompt(evaluated: List[Dict]) -> str:
    """단타 모드 프롬프트용 포지션 평가 텍스트."""
    if not evaluated:
        return "(오늘 추적 중인 포지션 없음 — 풀 모드가 아직 안 돌았거나 데이터 손실)"

    lines = [
        "## 🚨 오늘 아침 추천 포지션 — 현재 상태",
        "각 종목에 대해 '계속 보유 / 매도 검토 / 손절 검토' 등 권고 작성 필수.",
        "특히 손절 도달이나 임박이면 강하게 '매도 검토' 시그널.",
        "",
    ]
    for p in evaluated:
        cp = p.get("current_price")
        chg = p.get("change_pct")
        cp_s = f"{cp:,.2f}" if cp else "—"
        chg_s = f"{chg:+.2f}%" if chg is not None else "—"
        lines.append(
            f"### {p['name']} ({p['ticker']}) [{p.get('card_type', '?')}]"
        )
        lines.append(
            f"- 추천 시: {p.get('recommended_at')} → 현재: {cp_s} ({chg_s}) | 상태: {p.get('status')}"
        )
        lines.append(
            f"- 1차 익절: {p.get('target_1')} / 2차 익절: {p.get('target_2')} / 손절가: {p.get('stop_loss')}"
        )
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    evals = evaluate_positions()
    print(format_positions_for_prompt(evals))
