"""
Claude API로 모든 데이터를 분석해서 한국어 리포트(HTML) 생성

이전 버전 대비:
- 거시·섹터·기술적·공시 데이터 모두 활용
- 뉴스 비중 대폭 축소 (확인용)
- "남들 다 아는 정보 = 이미 늦음" 원칙 명시
- 메모리(과거 시그널) 주입 — Claude가 자기 판단 self-correct
- 300만원 포지션 사이징 가이드 포함
"""

import json
import os
from datetime import datetime
from typing import Dict, List

from anthropic import Anthropic

from config import (
    CLAUDE_MODEL, MAX_OUTPUT_TOKENS,
    TOTAL_CAPITAL_KRW, MAX_POSITIONS, MAX_POSITION_PCT,
    STOP_LOSS_ATR_MULTIPLIER,
)
from utils import logger
import memory


SYSTEM_PROMPT = f"""너는 한국인 개인 투자자(운용자금 약 {TOTAL_CAPITAL_KRW:,}원, 다 잃어도 됨)를
위한 매일 아침 시장 브리핑 작성자다.

# 가장 중요한 원칙

**독자는 주식 한 번도 안 해본 완전 초보다. 14살 동생한테 설명하듯 써라.**

쉬운 말 규칙:
- "익절" X → "**이익 보고 팔기**"
- "손절" X → "**손해 더 커지기 전에 팔기**"
- "비중" X → "**얼마 넣을지**"
- "포지션" X → "**보유 종목**" 또는 안 씀
- "분산투자" → "**여러 종목에 나눠서**"
- "추격매수" → "**가격 이미 많이 오른 뒤에 따라 사는 것**"
- "골든크로스" → "**단기 평균선이 장기 평균선 위로 올라간 거 (보통 좋은 신호)**"
- "RSI 70" → "**RSI 70 (100점 만점에 70. 너무 올라서 빠질 수도 있는 위험 신호)**"
- "ATR" → "**ATR (이 종목이 하루에 평균 얼마씩 흔들리는지)**"
- "CPI", "Fed금리" 등 → 본문에서 짧게 풀이 ("CPI = 미국 물가 지수, 오르면 나쁨")

문체:
- "~한 흐름이다" X → "**~하는 거 같아**" 또는 "**~로 보여**"
- 친구한테 카톡으로 설명하듯
- 비유 활용: "지금 NVDA는 풍선이 너무 빵빵해서 살짝만 찔러도 터질 위험"

각 후보에는 반드시 4가지 가격을 표로:
- 사기 좋은 가격대 (예: 65,000~68,000원)
- 일부 팔기 좋은 가격 1차 (+8~15%)
- 더 팔기 좋은 가격 2차 (+20~30%)
- 손해 줄이려고 팔 가격 (-7~10%)

각 섹션 끝에 "**→ 그래서 어떻게?**" 한 줄로 정리.

# 데이터 우선순위

CNBC/연합뉴스에 헤드라인 뜬 시점이면 이미 늦었다. 그래서:
1. **최우선**: 임원 매매(SEC Form 4 / DART 보유주식보고), 8-K 중요사건, 거시 지표 발표
2. **중간**: 섹터 자금 흐름, 기술적 지표(추세 전환), 거래량 이상치
3. **보조**: 뉴스 (확인용으로만 짧게)

공시·거시 데이터에서 먼저 단서를 찾고 뉴스는 검증용.

# 행동 가이드 작성 방식

"확실히 사세요/파세요" 단정 X — 법적 책임 문제. 대신 다음 표현 활용:
- "**매수 검토**", "**관망**", "**비중 축소 검토**", "**관찰 대상**"

**하지만 구체적 숫자는 반드시 제시해라:**

각 후보마다 다음 4가지 가격을 표로 명시:
1. **매수 검토 가격대** (range): 현재가 기준 어디서 어디까지가 진입 매력적인 구간인지
   예: "현재 65,000원 → 62,000~66,000원 사이 매수 검토" (현재가 -5% ~ +1%)
2. **1차 익절 검토가**: 현재가 기준 +8~15% 정도 (보수적 차익)
3. **2차 익절 검토가**: +20~30% 정도 (목표가)
4. **손절가**: ATR 기반 또는 -7~10% 정도

이 가격은 "추천"이 아니라 "이런 시나리오면 이렇게 행동을 검토할 수 있다"는 시뮬레이션이다.
근거는 반드시 첨부 (RSI 위치, 기술적 지지/저항, 장기선, 공시 신호 등).

# 300만원 분산 시뮬레이션 (필수)

**중요: 사용자는 테스트 목적이며 "300만원 다 잃어도 된다"고 명시했음. 따라서 100% 투입 모드.**
현금 비중 두지 말고 100% 종목에 분산. 단, 종목 수는 분산 원칙은 유지.

매일 마지막에 "**오늘 기준 300만원이라면 이렇게 짤 수 있다**" 시뮬레이션 표 작성.
- 종목 / 티커 / 비중(%) / 금액(원) / 진입 검토가 / 1차 익절가 / 2차 익절가 / 손절가 / 이유 1줄
- **합계가 정확히 100% (3,000,000원) 되도록 구성**. 현금 비중 0%.
- 최대 {MAX_POSITIONS}종목, 한 종목 {MAX_POSITION_PCT}% 이하.
- 신호가 약한 날에도 현금이 아니라 가장 안정적인 종목(우량주, ETF 등) 비중을 늘려서 100% 채운다.
- 발굴 후보(잘 모르는 작은 회사)도 포함. "추가 조사 필요" 라벨 + 비중 5~10%로 작게.
- 외국인/기관 순매수 상위 + Reddit 화제 종목도 같이 고려해서 후보군 풍부하게.

# 자기 검증 (메모리 활용)

프롬프트 끝에 너의 과거 시그널 이력이 주어지면, 거기서 자주 틀린 패턴이 있는지 확인.
틀린 패턴이 있으면 오늘 그 부분은 더 보수적으로 다뤄라. (이건 본문에 "지난 며칠 X 신호 잘 안 맞아서 보수적" 식으로 짧게 언급)

# 불확실성 명시

모든 전망은 "~로 보이는 흐름", "~일 가능성", "신호" 같은 표현으로 헤지.
단정 X. 단기 가격은 누구도 못 맞춤.

# 출력 형식

한국어 HTML. 인라인 CSS만 (이메일 호환). 상승 #c0392b 빨강 / 하락 #2980b9 파랑.
표는 간결하게. 글자 크기 너무 작지 않게.

# 출력 섹션 순서 (반드시 이 순서)

<h2>📝 오늘 한 줄 정리 (TL;DR)</h2>
<!-- 진짜 단순하게. 어려운 단어 하나도 없이 3~4줄.
     예: "오늘은 미국 금리가 다음달에 떨어질 가능성이 커지면서 기술주에 좋아 보이는 흐름.
         관심종목 중에서는 NVDA가 가장 좋은 신호 (임원이 최근 매수). 작은 회사 중엔 [발굴목록의 회사 1~2개] 살펴볼만.
         300만원이라면 70%만 분산 투자하고 30%는 현금으로 두는 걸 검토." -->

<h2>🎯 오늘 행동 가이드</h2>
<!-- 가장 중요. 이거만 봐도 오늘 뭘 하면 좋을지 알게.
     - 매수 검토 후보 1~3개 (표): 종목 / 왜 / 매수 검토가 / 손절가
     - 비중 축소 검토 (있다면)
     - 관망 (있다면)
     - 오늘 절대 하지 말 것 (1~2줄, 진한 글씨)
-->

<h2>💰 300만원 분산 시뮬레이션</h2>
<!-- 표: 종목/티커/비중%/금액원/진입가/손절가/이유.
     신호 약하면 현금 비중 키움. 다 채울 필요 없음. -->

<h2>🔍 오늘 새로 발굴된 후보 (대중에 덜 알려진 종목)</h2>
<!-- 가장 흥미로운 부분. 본인이 모를 작은/중형 회사 중 임원이 최근 매수한 곳.
     한국(코스닥/코스피) + 미국(SEC Form 4 클러스터) 각각 3~6개씩.
     표 형식: 회사명 / 시장 / 공시 횟수 / 어떤 의미인지 1줄 / DART/SEC 링크.
     특히 같은 회사에 임원 여러 명이 동시에 매수했으면 강한 신호로 짚어라.
     단, 이건 "확실한 매수 신호"가 아니라 "추가 조사해볼 출발점"임을 명시해라.
     이 종목들은 yfinance에 데이터가 없을 수 있으므로, 사용자가 직접 한 번 더 확인해야 함을 알려라.
-->

<h2>🌐 거시 환경 (쉽게 풀어서)</h2>
<!-- Fed금리, 금리차, CPI 등. 어려운 단어 옆에 반드시 한 줄로 풀이.
     예: "장단기 금리차 = 단기 금리 vs 장기 금리 차이. 마이너스면 경기 안 좋아질 신호로 본다."
     끝에 "→ 그래서?" -->

<h2>🏭 섹터 흐름 (돈이 어디로 가나?)</h2>
<!-- 좋은/나쁜 섹터 각 2~3개. 표 단순하게. 끝에 "→ 그래서?" -->

<h2>📋 관심종목 + 공시 한 줄 평가</h2>
<!-- watchlist 종목별로: 현재가 / 1일% / 핵심 라벨 / 최근 공시 한 줄.
     너무 자세하지 말고 한 종목당 2~3줄로. -->

<h2>📰 뉴스 한 줄</h2>
<!-- 거시 영향 큰 거 3~5줄만. 짧게. -->

<h2>⚠️ 조심할 것 / 면책</h2>
<!-- 변동성 큰 이벤트 예고, 추격매수 경고. 면책 1줄. -->

<h2>📚 어려운 용어 풀이</h2>
<!-- 본문에 나온 어려운 단어 4~6개를 마지막에 모아서 한 줄씩 풀이.
     예: "RSI: 주식이 너무 올랐는지/내렸는지 보는 0~100 숫자. 70 이상=과매수, 30 이하=과매도."
-->
"""


def _format_macro(macro: List[Dict]) -> str:
    if not macro:
        return "(거시 지표 데이터 없음 — FRED API 키 미설정 또는 호출 실패)"
    lines = []
    for m in macro:
        change = m.get("change_pct")
        ch_str = f" ({change:+.2f}%)" if change is not None else ""
        lines.append(f"- {m['name']} ({m['series_id']}): {m['last_value']}{ch_str} [기준 {m['last_date']}]")
    return "\n".join(lines)


def _format_sectors(sectors: List[Dict]) -> str:
    if not sectors:
        return "(섹터 데이터 없음)"
    lines = []
    for s in sectors:
        r1 = s.get("ret_1d"); r5 = s.get("ret_5d"); r20 = s.get("ret_20d")
        lines.append(
            f"- {s['name']} ({s['ticker']}): "
            f"1일 {r1:+.2f}% / 5일 {r5:+.2f}% / 20일 {r20:+.2f}%"
            if all(x is not None for x in [r1, r5, r20]) else
            f"- {s['name']} ({s['ticker']}): 데이터 부족"
        )
    return "\n".join(lines)


def _format_watchlist(watchlist: List[Dict]) -> str:
    if not watchlist:
        return "(관심 종목 데이터 없음)"
    parts = []
    for s in watchlist:
        parts.append(f"\n### [{s['market']}] {s['name']} ({s['ticker']})")
        parts.append(
            f"- 종가 {s['close']:,} ({s['change_pct']:+.2f}%) / "
            f"거래량 {s['volume']:,} (평균 대비 {s['vol_vs_avg']}x) / "
            f"52주 위치 {s['year_position']:.0%} (저 {s['year_low']:,} ~ 고 {s['year_high']:,})"
        )
        tech = s.get("technicals")
        if tech:
            labels_str = ", ".join(tech["labels"]) if tech["labels"] else "특이 신호 없음"
            parts.append(
                f"- 기술적: RSI {tech['rsi']} / MA20 {tech['ma20']:,} / MA60 {tech['ma60']:,} / "
                f"MA200 {tech['ma200']:,} / ATR {tech['atr']} ({tech['atr_pct_of_price']}%) / "
                f"라벨: {labels_str}"
            )
        if s.get("analyst"):
            parts.append(f"- 애널리스트(raw): {json.dumps(s['analyst'], default=str, ensure_ascii=False)[:300]}")
    return "\n".join(parts)


def _format_filings(filings: Dict) -> str:
    sec = filings.get("sec", {})
    dart = filings.get("dart", {})
    if not sec and not dart:
        return "(공시 데이터 없음 — DART_API_KEY 미설정 또는 호출 실패)"

    parts = ["## SEC EDGAR (미국 watchlist)"]
    if sec:
        for ticker, d in sec.items():
            parts.append(
                f"\n### {ticker}: Form 4 {d['form4_count']}건 / 8-K {d['form8k_count']}건 / 13D-G {d['form13_count']}건"
            )
            for f in d.get("form4_recent", []):
                parts.append(f"- [Form 4 / {f['date']}] {f['url']}")
            for f in d.get("form8k_recent", []):
                parts.append(f"- [8-K / {f['date']}] {f['url']}")
            for f in d.get("form13_recent", []):
                parts.append(f"- [13D-G / {f['date']}] {f['url']}")
    else:
        parts.append("(SEC 데이터 없음)")

    parts.append("\n## DART (한국 watchlist) — 중요 공시만")
    if dart:
        for ticker, d in dart.items():
            parts.append(f"\n### {ticker}: 중요 공시 {d['important_count']}건 / 전체 {d['all_count']}건")
            for f in d.get("important_recent", []):
                parts.append(
                    f"- [{f['rcept_dt']}] {f['report_nm']} (제출: {f['flr_nm']}) {f['url']}"
                )
    else:
        parts.append("(DART 데이터 없음)")

    return "\n".join(parts)


def _format_news(news: List[Dict]) -> str:
    if not news:
        return "(뉴스 데이터 없음)"
    lines = []
    for n in news:
        lines.append(f"[{n['source']}] {n['title']}")
        if n.get("summary"):
            lines.append(f"  · {n['summary'][:180]}")
    return "\n".join(lines)


def _format_screener(screener: Dict) -> str:
    """발굴 스캔 결과 포매팅 — 'watchlist 밖' 후보들."""
    if not screener:
        return "(발굴 데이터 없음)"

    parts = []

    # === 한국 DART 임원 매매 ===
    kr = screener.get("kr_candidates", [])
    parts.append(f"## 🔍 한국 시장 발굴 — 임원이 자기 회사 주식 매매 신고 (DART, 최근 {screener.get('scanned_days', 7)}일)")
    parts.append(
        "*일반인이 잘 모르는 작은/중형 회사들. 공시 횟수 많을수록 활발한 활동.*\n"
        "*매수일 수도 있고 매도일 수도 있음 — DART 링크에서 직접 확인해야 함.*"
    )
    if kr:
        for c in kr:
            titles_str = " / ".join(c.get("recent_titles", [])[:2])
            parts.append(
                f"- **{c['corp_name']}** ({c.get('stock_code') or '코드미상'}): "
                f"공시 {c['filing_count']}건. 제출자: {', '.join(c.get('filers', [])[:3])}. "
                f"최근 제목: {titles_str}. 링크: {c.get('url_first')}"
            )
    else:
        parts.append("- (없음)")

    # === 미국 SEC Form 4 ===
    parts.append("")
    us = screener.get("us_candidates", [])
    parts.append("## 🔍 미국 시장 발굴 — 임원 매매 클러스터 (SEC Form 4 RSS)")
    parts.append("*같은 회사에 임원 여러 명이 동시에 매매 신고 = 강한 신호.*")
    if us:
        for c in us:
            parts.append(
                f"- **{c['company']}**: Form 4 {c['filing_count']}건. 링크: {c.get('recent_url')}"
            )
    else:
        parts.append("- (없음)")

    # === KRX 외국인/기관 순매수 ===
    parts.append("")
    krx_flow = screener.get("krx_flow", {})
    flow_date = krx_flow.get("date", "?")
    parts.append(f"## 💰 한국 거래소 외국인·기관 순매수 상위 (KRX, 기준일 {flow_date})")
    parts.append(
        "*외국인·기관이 어제 가장 많이 순매수한 종목. 큰돈이 어디로 들어가는지 보여주는 강한 신호.*\n"
        "*큰돈이 들어가는 종목은 보통 향후 상승 가능성이 평균보다 높다고 본다 (개인 투자자가 따라가기 좋은 채널).*"
    )

    def _fmt_flow_list(label: str, items: List[Dict]) -> str:
        if not items:
            return f"### {label}\n- (데이터 없음)"
        lines = [f"### {label}"]
        for it in items[:10]:
            amt = it.get("net_buy_amount")
            amt_str = f"{amt/1e8:.1f}억원" if isinstance(amt, (int, float)) and amt else "?"
            lines.append(f"- **{it.get('name')}** ({it.get('ticker')}): 순매수 {amt_str}")
        return "\n".join(lines)

    parts.append(_fmt_flow_list("외국인 순매수 상위 — 코스피", krx_flow.get("foreign_kospi", [])))
    parts.append(_fmt_flow_list("외국인 순매수 상위 — 코스닥", krx_flow.get("foreign_kosdaq", [])))
    parts.append(_fmt_flow_list("기관 순매수 상위 — 코스피", krx_flow.get("inst_kospi", [])))
    parts.append(_fmt_flow_list("기관 순매수 상위 — 코스닥", krx_flow.get("inst_kosdaq", [])))

    # === Reddit 트렌딩 ===
    parts.append("")
    reddit = screener.get("reddit_trend", [])
    parts.append("## 📣 미국 Reddit 트렌딩 종목 (r/stocks, r/wallstreetbets 등)")
    parts.append(
        "*미국 retail(개인 투자자) 커뮤니티에서 자주 언급되는 티커. 화제성 = 변동성 신호.*\n"
        "*대중 관심이 폭증하면 단기 변동성 큼. 좋은 기회일 수도, 거품일 수도 있음.*"
    )
    if reddit:
        for r in reddit:
            sample = r["sample_posts"][0]["title"] if r.get("sample_posts") else ""
            parts.append(
                f"- **{r['ticker']}**: 점수 {r['score']:,} | 예시 게시물: \"{sample[:80]}\""
            )
    else:
        parts.append("- (데이터 없음)")

    return "\n".join(parts)


def build_user_prompt(data: Dict) -> str:
    parts = [f"# 데이터 수집 시각: {data['collected_at']}\n"]

    parts.append("## 1. 거시 경제 지표 (FRED)")
    parts.append(_format_macro(data.get("macro", [])))

    parts.append("\n## 2. 시장 지표 (지수/환율/원자재/금리)")
    indicators = data.get("indicators", [])
    for ind in indicators:
        arrow = "▲" if ind["change_pct"] > 0 else ("▼" if ind["change_pct"] < 0 else "—")
        parts.append(
            f"- {ind['name']} ({ind['ticker']}): {ind['close']:,} {arrow} {ind['change_pct']:+.2f}% [{ind['date']}]"
        )

    parts.append("\n## 3. 섹터 로테이션 (ETF 1일/5일/20일 수익률, 1일순)")
    parts.append(_format_sectors(data.get("sectors", [])))

    parts.append("\n## 4. 🚨 공시 시그널 (관심 종목 — 가장 중요)")
    parts.append(_format_filings(data.get("filings", {})))

    parts.append("\n## 5. 관심 종목 동향 + 기술 지표")
    parts.append(_format_watchlist(data.get("watchlist", [])))

    parts.append("\n## 6. 🔍 발굴 후보 (watchlist 밖 — 잘 안 알려진 종목)")
    parts.append(_format_screener(data.get("screener", {})))

    parts.append("\n## 7. 뉴스 (확인용 — 비중 작게)")
    parts.append(_format_news(data.get("news", [])))

    # 메모리 주입 (지난 시그널 자기 검증용)
    current_prices = {
        s["ticker"]: s["close"] for s in data.get("watchlist", [])
    }
    mem = memory.build_memory_prompt(current_prices)
    if mem:
        parts.append("\n---\n")
        parts.append(mem)

    parts.append("""
---

위 데이터로 시스템 프롬프트 형식대로 오늘의 브리핑을 HTML로 작성해.

**명심**:
1. 독자는 주식 초보다. 중학생도 이해할 쉬운 말로. 어려운 용어는 괄호로 풀이.
2. **첫 번째 섹션 "🎯 오늘 행동 가이드"**가 가장 중요. 이거만 봐도 오늘 뭘 하면 좋을지 알 수 있어야 한다.
   거기에 매수 검토 후보, 비중 축소 검토, 관망, 절대 하지 말 것을 표 형식으로 명료하게.
3. **두 번째 섹션 "💰 300만원 분산 시뮬레이션"** — 진짜 표로. 종목/티커/비중%/금액원/진입가/손절가/이유.
   신호가 약하면 현금 비중을 키워라 (다 100% 채울 필요 없음).
4. 임원 매매(SEC Form 4 / DART)가 있으면 그걸 강하게 다뤄라. "임원 N주 매수 — 보통 이런 신호는 ~~한 의미"
5. 거시 → 섹터 → 종목 으로 인과관계 연결해라. "금리 ↑ 가능성 → 성장주 부담 → NVDA 매수 검토 보수적"
6. 메모리에 과거 시그널이 있으면 거기서 자주 틀린 패턴을 의식해서 오늘은 더 보수적으로.
7. "사세요/파세요" X. "매수 검토", "관망", "비중 축소 검토" 표현만 사용.
8. 각 섹션 끝에 "**→ 그래서?**" 한 줄로 그 섹션이 의미하는 바를 정리.

특히 행동 가이드와 300만원 시뮬레이션을 자세하고 구체적으로. 데이터 나열보다 해석/의미가 중요.
""")

    return "\n".join(parts)


def generate_briefing(data: Dict) -> str:
    """Claude API 호출 → HTML 리포트."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수 없음")

    client = Anthropic(api_key=api_key)
    user_prompt = build_user_prompt(data)

    logger.info(f"🤖 Claude ({CLAUDE_MODEL}) 호출 — 입력 {len(user_prompt):,}자")
    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    html_content = ""
    for block in response.content:
        if hasattr(block, "text"):
            html_content += block.text
    html_content = html_content.strip()

    # ```html 펜스 제거
    if html_content.startswith("```"):
        lines = html_content.split("\n")
        if lines[-1].startswith("```"):
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        html_content = "\n".join(lines)

    logger.info(
        f"📝 리포트 생성 완료 — 출력 {len(html_content):,}자 / "
        f"입력토큰 {response.usage.input_tokens} / 출력토큰 {response.usage.output_tokens}"
    )
    return html_content


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from utils import setup_logging
    setup_logging()

    from data_fetcher import fetch_all_data
    from macro_fetcher import fetch_macro_indicators
    from filings_fetcher import fetch_all_filings

    data = fetch_all_data()
    data["macro"] = fetch_macro_indicators()
    data["filings"] = fetch_all_filings()

    html = generate_briefing(data)
    out_path = os.path.join(os.path.dirname(__file__), "briefing_test.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"테스트 출력: {out_path}")
