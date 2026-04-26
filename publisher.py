"""
HTML 리포트를 docs/ 폴더에 저장.
- docs/YYYY-MM-DD.html — 그날 리포트
- docs/latest.html — 가장 최근 리포트 (북마크용)
- docs/index.html — 전체 archive 목록 (홈)

GitHub Pages는 docs/ 폴더를 기본 publish 경로로 인식하므로,
이 폴더만 push 되면 자동으로 웹사이트가 생성됨.

이메일 대신 (또는 이메일과 함께) 사용 가능.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from utils import logger


import re as _re
DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)


def _sanitize_html(html: str) -> str:
    """
    Claude가 생성한 HTML에서 위험한 인라인 스타일 제거 + 깨진 태그 정규화.
    - 어두운 배경/색 인라인 제거 (글씨 안 보이게 되는 거 방지)
    - float/position/transform 제거 (레이아웃 망가지는 거 방지)
    - BeautifulSoup으로 닫히지 않은 태그 자동 닫기
    """
    # 1. 위험한 인라인 스타일 속성 제거
    DANGEROUS_PROPS = [
        "background", "background-color", "background-image",
        "color",
        "float", "clear",
        "position", "top", "right", "bottom", "left",
        "transform",
        "display", "flex-direction",
        "width", "height",
        "z-index",
    ]
    danger_pattern = "|".join(DANGEROUS_PROPS)

    def _strip(m):
        style_content = m.group(1)
        cleaned = _re.sub(
            rf"(\b({danger_pattern})\s*:[^;]+;?)",
            "",
            style_content,
            flags=_re.IGNORECASE,
        )
        cleaned = cleaned.strip().rstrip(";").strip()
        if not cleaned:
            return ""
        return f'style="{cleaned}"'

    html = _re.sub(r'style\s*=\s*"([^"]*)"', _strip, html)

    # 2. BeautifulSoup으로 깨진 태그 닫기 (float right 같은 거 방지)
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # 원래 다 자식이 body 없이 그냥 fragment로 들어옴
        html = str(soup)
    except Exception as e:
        logger.warning(f"HTML BeautifulSoup 정규화 실패: {e}")

    return html


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<meta name="color-scheme" content="light">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  html {{ color-scheme: light !important; background: #fafafa !important; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo",
                 "맑은 고딕", "Malgun Gothic", sans-serif;
    line-height: 1.65;
    color: #2c3e50 !important;
    max-width: 960px;
    margin: 0 auto;
    padding: 16px;
    background: #fafafa !important;
    font-size: 16px;
  }}
  .nav {{
    background: white;
    padding: 12px 16px;
    border-radius: 10px;
    margin-bottom: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .nav a {{
    color: #2980b9;
    text-decoration: none;
    font-size: 14px;
    padding: 6px 12px;
    border-radius: 6px;
    background: #ecf0f1;
  }}
  .nav a:hover {{ background: #d5dde0; }}
  .header {{
    background: linear-gradient(135deg, #1a2332 0%, #2c3e50 100%);
    color: white;
    padding: 24px;
    border-radius: 12px 12px 0 0;
  }}
  .header h1 {{ margin: 0 0 8px 0; font-size: 24px; }}
  .header .date {{ opacity: 0.85; font-size: 14px; }}
  .content {{
    background: #ffffff !important;
    color: #1a2332 !important;
    padding: 28px 32px;
    border-radius: 0 0 12px 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }}
  .content * {{ color: #1a2332; }}
  .content h2 {{
    border-bottom: 2px solid #ecf0f1;
    padding-bottom: 10px;
    margin-top: 32px;
    font-size: 20px;
    color: #1a2332 !important;
    background: transparent !important;
  }}
  .content h2:first-child {{ margin-top: 0; }}
  .content h3 {{ font-size: 17px; margin-top: 20px; }}
  .content p, .content li {{ font-size: 15px; }}

  /* 표 — 한글 자연 줄바꿈 강제 + 헤더 진한색 강제 (Claude 인라인 스타일 덮어쓰기) */
  .content table {{
    display: block !important;
    overflow-x: auto !important;
    -webkit-overflow-scrolling: touch !important;
    width: 100% !important;
    border-collapse: collapse !important;
    margin: 14px 0 !important;
    font-size: 14px !important;
  }}
  .content table > thead,
  .content table > tbody,
  .content table > tfoot {{
    display: table !important;
    width: 100% !important;
    min-width: 640px !important;
    border-collapse: collapse !important;
  }}
  .content table tr {{ display: table-row !important; }}
  .content th, .content td {{
    display: table-cell !important;
    padding: 10px 14px !important;
    border-bottom: 1px solid #ecf0f1 !important;
    text-align: left !important;
    vertical-align: top !important;
    word-break: keep-all !important;
    word-wrap: break-word !important;
    white-space: normal !important;
    line-height: 1.6 !important;
    min-width: 90px !important;
    background: transparent !important;
    color: #2c3e50 !important;
  }}
  .content th {{
    background: #2c3e50 !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    white-space: nowrap !important;
    border-bottom: 2px solid #c0392b !important;
  }}
  /* 마지막 열(이유)은 더 넓게 */
  .content td:last-child {{ min-width: 220px !important; }}

  /* 종목 카드 — 배경/글씨 색 무조건 라이트 강제 */
  /* [style*="background"] 같은 인라인 스타일도 덮어쓰도록 강력 강제 */
  .stock-card,
  .stock-card[style] {{
    border: 1px solid #e0e6ed !important;
    border-radius: 10px !important;
    padding: 16px 18px !important;
    margin: 14px 0 !important;
    background: #ffffff !important;
    background-color: #ffffff !important;
    background-image: none !important;
    color: #1a2332 !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03) !important;
  }}
  /* 카드 안 모든 자식들도 어두운 배경 박는 인라인 스타일 무력화 */
  .stock-card *[style*="background"] {{
    background: transparent !important;
    background-color: transparent !important;
    background-image: none !important;
  }}
  .stock-card.candidate {{
    border-left: 4px solid #c0392b;
    background: #ffffff !important;
  }}
  .stock-card.watch {{
    border-left: 4px solid #f39c12;
    background: #fffbf0 !important;
  }}
  .stock-card.discovery {{
    border-left: 4px solid #27ae60;
    background: #f5fbf7 !important;
  }}
  .stock-card.warning {{
    border-left: 4px solid #e74c3c;
    background: #fff7f5 !important;
  }}

  /* TOP 3 우선순위 카드 — 금/은/동 강조 */
  .stock-card.priority-1 {{
    border-left: 6px solid #f39c12;
    background: linear-gradient(90deg, #fffaf0 0%, #fff 30%);
    box-shadow: 0 2px 8px rgba(243,156,18,0.2);
    padding: 20px 24px;
  }}
  .stock-card.priority-1 .stock-header h3 {{ font-size: 19px; }}
  .stock-card.priority-1 .stock-header h3::before {{
    content: "🥇 ";
    margin-right: 4px;
  }}
  .stock-card.priority-2 {{
    border-left: 5px solid #95a5a6;
    background: linear-gradient(90deg, #fafbfc 0%, #fff 30%);
    padding: 18px 22px;
  }}
  .stock-card.priority-2 .stock-header h3::before {{
    content: "🥈 ";
    margin-right: 4px;
  }}
  .stock-card.priority-3 {{
    border-left: 5px solid #b87333;
    background: linear-gradient(90deg, #fcf8f3 0%, #fff 30%);
    padding: 18px 22px;
  }}
  .stock-card.priority-3 .stock-header h3::before {{
    content: "🥉 ";
    margin-right: 4px;
  }}

  .stock-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 8px;
    border-bottom: 1px dashed #e0e6ed;
    padding-bottom: 8px;
    margin-bottom: 10px;
  }}
  .stock-header h3, .stock-header .stock-name {{
    margin: 0;
    font-size: 17px;
    font-weight: 700;
    color: #1a2332;
  }}
  /* 우상단 배지 — 무조건 어두운 배경 + 흰 글씨 (Claude 인라인 스타일 덮어쓰기) */
  .stock-card .stock-allocation,
  .stock-card .stock-header .stock-allocation,
  .stock-card .stock-allocation * {{
    color: #ffffff !important;
    font-weight: 700 !important;
    text-decoration: none !important;
  }}
  .stock-header .stock-allocation {{
    font-size: 13px !important;
    background: #2c3e50 !important;
    padding: 4px 10px !important;
    border-radius: 12px !important;
    white-space: nowrap !important;
    display: inline-block !important;
  }}
  /* 카드 종류별 배지 색 — 모두 어두운 톤으로 흰 글씨 잘 보임 */
  .stock-card.candidate .stock-header .stock-allocation {{ background: #c0392b !important; }}
  .stock-card.discovery .stock-header .stock-allocation {{ background: #1e8449 !important; }}
  .stock-card.watch .stock-header .stock-allocation {{ background: #b9770e !important; }}
  .stock-card.warning .stock-header .stock-allocation {{ background: #922b21 !important; }}
  .stock-card.priority-1 .stock-header .stock-allocation {{ background: #b7950b !important; }}
  .stock-card.priority-2 .stock-header .stock-allocation {{ background: #566573 !important; }}
  .stock-card.priority-3 .stock-header .stock-allocation {{ background: #935116 !important; }}

  /* 카드 본문 글씨 — 무조건 진한 검정 (라이트 배경에 명확하게 보이도록) */
  .stock-card,
  .stock-card *:not(.stock-allocation):not(.stock-allocation *):not(.up):not(.down):not(.live-price-row .label):not(.stock-prices .label):not(.stock-reason) {{
    color: #1a2332 !important;
  }}
  .stock-card p,
  .stock-card li,
  .stock-card span:not(.stock-allocation):not(.stock-allocation *):not(.up):not(.down) {{
    color: #1a2332 !important;
  }}
  .stock-card .stock-name,
  .stock-card h3 {{
    color: #1a2332 !important;
    font-weight: 700;
  }}
  /* 라벨(작은 회색 글씨)는 약간 흐리게 */
  .stock-card .label {{ color: #5d6d7e !important; }}
  /* stock-reason은 살짝 다른 톤 */
  .stock-card .stock-reason {{
    color: #2c3e50 !important;
    background: #f8f9fb;
    padding: 10px 14px;
    border-radius: 6px;
    margin-top: 10px;
    line-height: 1.65;
  }}
  /* 가격 — 빨강(상승) / 파랑(하락) 강조 */
  .stock-card .value.up,
  .stock-card .price-diff.up,
  .stock-card .up {{ color: #c0392b !important; font-weight: 700; }}
  .stock-card .value.down,
  .stock-card .price-diff.down,
  .stock-card .down {{ color: #1f618d !important; font-weight: 700; }}
  /* 일반 가격 숫자 */
  .stock-card .value,
  .stock-card .rec-price,
  .stock-card .current-price {{ color: #1a2332 !important; font-weight: 700; }}

  .stock-prices {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px 16px;
    margin: 10px 0;
    font-size: 14px;
  }}
  .stock-prices .label {{
    color: #7f8c8d;
    margin-right: 6px;
    font-weight: 600;
  }}
  .stock-prices .value {{ color: #2c3e50; }}
  .stock-prices .value.up {{ color: #c0392b; font-weight: 700; }}
  .stock-prices .value.down {{ color: #2980b9; font-weight: 700; }}

  .stock-reason {{
    font-size: 14px;
    color: #555;
    background: #f8f9fa;
    padding: 8px 12px;
    border-radius: 6px;
    margin-top: 10px;
    line-height: 1.6;
  }}

  /* TL;DR 박스 */
  .tldr {{
    background: linear-gradient(135deg, #fff8e1 0%, #fffde7 100%);
    border-left: 4px solid #f39c12;
    border-radius: 8px;
    padding: 16px 20px;
    margin: 14px 0;
    font-size: 15px;
    line-height: 1.7;
  }}

  /* 그래서? 박스 */
  .so-what {{
    background: #e8f4f8;
    border-left: 4px solid #2980b9;
    padding: 10px 14px;
    margin: 12px 0;
    border-radius: 6px;
    font-weight: 600;
    color: #1a4f6b;
  }}

  .footer {{
    text-align: center;
    color: #95a5a6;
    font-size: 12px;
    margin-top: 24px;
    padding: 16px;
  }}
  .up {{ color: #c0392b; font-weight: 600; }}
  .down {{ color: #2980b9; font-weight: 600; }}
  strong {{ color: #c0392b; }}
  ul, ol {{ padding-left: 1.4em; }}
  li {{ margin-bottom: 6px; }}

  ul.archive-list {{ list-style: none; padding: 0; }}
  ul.archive-list li {{
    padding: 10px 12px;
    border-bottom: 1px solid #ecf0f1;
  }}
  ul.archive-list a {{
    color: #2980b9;
    text-decoration: none;
    font-weight: 500;
  }}

  /* 모바일 */
  @media (max-width: 720px) {{
    body {{ padding: 8px; font-size: 15px; }}
    .header {{ padding: 18px; border-radius: 10px 10px 0 0; }}
    .header h1 {{ font-size: 20px; }}
    .content {{ padding: 16px 18px; }}
    .content h2 {{ font-size: 18px; }}
    .content table {{ font-size: 13px; }}
    .content th, .content td {{ padding: 8px 10px; }}
    .stock-card {{ padding: 14px; }}
    .stock-header {{ flex-direction: column; align-items: flex-start; gap: 4px; }}
    .stock-header h3, .stock-header .stock-name {{ font-size: 16px; }}
    .stock-prices {{ grid-template-columns: 1fr; gap: 6px; }}
    .tldr {{ font-size: 14px; padding: 14px 16px; }}
  }}

  /* 표 줄 줄무늬 (가독성) */
  .content table tr:nth-child(even) td {{ background: #fafbfc; }}

  /* 실시간 가격 행 */
  .live-price-row {{
    display: grid;
    grid-template-columns: auto 1fr auto 1fr auto 1fr;
    gap: 6px 10px;
    align-items: center;
    background: #f0f4f8;
    padding: 10px 14px;
    border-radius: 6px;
    margin: 8px 0 12px;
    font-size: 14px;
  }}
  .live-price-row .label {{ color: #7f8c8d; font-weight: 600; }}
  .live-price-row .rec-price {{ color: #2c3e50; font-weight: 700; }}
  .live-price-row .current-price {{
    color: #1a2332;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }}
  .live-price-row .current-price.loading {{ color: #95a5a6; }}
  .live-price-row .price-diff {{
    color: #7f8c8d;
    font-weight: 700;
    font-variant-numeric: tabular-nums;
  }}
  .live-price-row .price-diff.up {{ color: #c0392b; }}
  .live-price-row .price-diff.down {{ color: #2980b9; }}

  @media (max-width: 720px) {{
    .live-price-row {{
      grid-template-columns: auto 1fr;
      font-size: 13px;
    }}
  }}

  .last-refreshed {{
    font-size: 12px;
    color: #95a5a6;
    text-align: right;
    margin: 4px 4px 16px;
  }}
  .refresh-btn {{
    background: #2c3e50;
    color: #fff;
    border: none;
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 12px;
    cursor: pointer;
    margin-left: 8px;
  }}
  .refresh-btn:hover {{ background: #1a2332; }}
</style>
</head>
<body>
  <div class="nav">
    <a href="index.html">📚 전체 목록</a>
    <a href="latest.html">📅 가장 최근</a>
  </div>
  <div class="header">
    <h1>{header}</h1>
    <div class="date">{date_str}</div>
  </div>
  <div class="content">
    <div class="last-refreshed">
      📡 실시간 가격 갱신: <span class="last-refreshed-time">로딩 중...</span>
      <button class="refresh-btn" onclick="manualRefresh()">🔄 새로고침</button>
    </div>
    {body}
  </div>
  <div class="footer">
    이 리포트는 자동 생성된 정보 정리이며 투자 자문이 아닙니다.<br>
    모든 투자 판단과 결과의 책임은 본인에게 있습니다.
  </div>

<script>
// 실시간 가격 갱신 (Yahoo Finance public API)
// 페이지에 [data-ticker="..."] [data-recommended-at="..."] 속성을 가진 카드의
// 현재가, 추천 시점 대비 변동률을 매분 갱신.

async function fetchPrice(ticker) {{
  const yahoo = `https://query1.finance.yahoo.com/v8/finance/chart/${{ticker}}?interval=1m&range=1d`;
  const proxy = 'https://corsproxy.io/?' + encodeURIComponent(yahoo);
  try {{
    const r = await fetch(proxy, {{ cache: 'no-store' }});
    if (!r.ok) throw new Error('http ' + r.status);
    const d = await r.json();
    const meta = d.chart && d.chart.result && d.chart.result[0] && d.chart.result[0].meta;
    if (!meta || meta.regularMarketPrice == null) return null;
    return {{
      price: meta.regularMarketPrice,
      previousClose: meta.previousClose,
      currency: meta.currency || '',
    }};
  }} catch (e) {{
    console.warn('price fetch fail', ticker, e);
    return null;
  }}
}}

function fmtNum(n, cur) {{
  if (n == null || isNaN(n)) return '—';
  if (cur === 'USD') return '$' + Number(n).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
  return Number(n).toLocaleString('ko-KR', {{ maximumFractionDigits: 2 }}) + '원';
}}

async function refreshAll() {{
  const cards = document.querySelectorAll('[data-ticker]');
  for (const card of cards) {{
    const ticker = card.dataset.ticker;
    const recAt = parseFloat(card.dataset.recommendedAt || '0');
    const result = await fetchPrice(ticker);
    if (!result) continue;

    const cur = card.querySelector('.current-price');
    const diff = card.querySelector('.price-diff');

    if (cur) {{
      cur.textContent = fmtNum(result.price, result.currency);
      cur.classList.remove('loading');
    }}
    if (diff && recAt > 0) {{
      const pct = ((result.price - recAt) / recAt) * 100;
      const sign = pct >= 0 ? '+' : '';
      diff.textContent = sign + pct.toFixed(2) + '%';
      diff.classList.remove('up', 'down');
      if (pct > 0.05) diff.classList.add('up');
      else if (pct < -0.05) diff.classList.add('down');
    }}
    await new Promise(r => setTimeout(r, 150));
  }}
  const ts = new Date().toLocaleTimeString('ko-KR');
  document.querySelectorAll('.last-refreshed-time').forEach(el => el.textContent = ts);
}}

document.addEventListener('DOMContentLoaded', () => {{
  refreshAll();
  setInterval(refreshAll, 60000);
}});

// 수동 새로고침 버튼
window.manualRefresh = function() {{
  const btn = document.querySelector('.refresh-btn');
  if (btn) {{ btn.disabled = true; btn.textContent = '⏳ 갱신 중...'; }}
  refreshAll().finally(() => {{
    if (btn) {{ btn.disabled = false; btn.textContent = '🔄 새로고침'; }}
  }});
}};
</script>
</body>
</html>
"""


INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<title>📊 매일 시장 브리핑 — 전체 목록</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo",
                 "맑은 고딕", "Malgun Gothic", sans-serif;
    line-height: 1.6;
    color: #2c3e50;
    max-width: 760px;
    margin: 0 auto;
    padding: 16px;
    background: #fafafa;
  }}
  .header {{
    background: linear-gradient(135deg, #1a2332 0%, #2c3e50 100%);
    color: white;
    padding: 24px;
    border-radius: 12px;
    margin-bottom: 16px;
  }}
  .header h1 {{ margin: 0 0 8px 0; font-size: 22px; }}
  .header p {{ margin: 0; opacity: 0.85; font-size: 14px; }}
  .latest-box {{
    background: white;
    padding: 16px 20px;
    border-radius: 12px;
    border-left: 4px solid #c0392b;
    margin-bottom: 16px;
  }}
  .latest-box a {{
    color: #c0392b;
    font-weight: 600;
    text-decoration: none;
    font-size: 16px;
  }}
  .archive {{
    background: white;
    padding: 8px 16px;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }}
  .day-group {{ margin-bottom: 18px; }}
  .day-group h3 {{
    font-size: 15px;
    color: #1a2332;
    margin: 0 0 8px;
    padding: 6px 8px;
    background: #ecf0f1;
    border-radius: 6px;
  }}
  ul.archive-list {{
    list-style: none;
    padding: 0;
    margin: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 6px;
  }}
  ul.archive-list li {{
    padding: 8px 10px;
    background: #fff;
    border: 1px solid #ecf0f1;
    border-radius: 6px;
    text-align: center;
  }}
  ul.archive-list li:hover {{ background: #f8f9fa; }}
  ul.archive-list a {{
    color: #2980b9;
    text-decoration: none;
    font-weight: 500;
    font-size: 14px;
  }}
  ul.archive-list a:hover {{ text-decoration: underline; }}
  .empty {{ color: #95a5a6; padding: 24px; text-align: center; }}
  .footer {{
    text-align: center;
    color: #95a5a6;
    font-size: 12px;
    margin-top: 24px;
    padding: 16px;
  }}
</style>
</head>
<body>
  <div class="header">
    <h1>📊 매일 시장 브리핑</h1>
    <p>한국·미국 시장 + 거시 지표 + 임원 매매 공시 자동 분석</p>
  </div>

  {latest_block}

  <div class="archive">
    <h3 style="margin: 12px 0;">📚 이전 리포트 ({count}개)</h3>
    {archive_html}
  </div>

  <div class="footer">
    매일 한국 시간 7:30 자동 갱신 · 자동 생성 정보이며 투자 자문이 아님
  </div>
</body>
</html>
"""


def _list_archive() -> List[Tuple[str, Path]]:
    """
    docs/ 안의 시간 스탬프 HTML 파일 목록 (최신순).
    포맷: YYYY-MM-DD-HHMM.html (예: 2026-04-26-1430.html)
    또는 (구버전) YYYY-MM-DD.html
    """
    files = []
    for p in DOCS_DIR.glob("*.html"):
        # 시간 포함: 2026-04-26-1430.html
        if re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}\.html$", p.name):
            files.append((p.stem, p))
        # 날짜만: 2026-04-26.html (legacy)
        elif re.match(r"^\d{4}-\d{2}-\d{2}\.html$", p.name):
            files.append((p.stem, p))
    files.sort(key=lambda x: x[0], reverse=True)
    return files


def publish(html_body: str, dry_run: bool = False) -> Path:
    """
    시간 스탬프 HTML 페이지 작성 + latest.html + index.html 갱신.
    매시간 실행해도 덮어쓰지 않고 비교 가능하게 별도 파일.
    """
    # Claude HTML에서 어두운 배경 인라인 스타일 제거
    html_body = _sanitize_html(html_body)

    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d-%H%M")  # 예: 2026-04-26-1430
    date_kor = now.strftime("%Y년 %m월 %d일 (%a) %H:%M KST")

    page = PAGE_TEMPLATE.format(
        title=f"시장 브리핑 — {timestamp}",
        header="📊 시장 브리핑",
        date_str=date_kor,
        body=html_body,
    )

    timestamped_path = DOCS_DIR / f"{timestamp}.html"
    latest_path = DOCS_DIR / "latest.html"

    if dry_run:
        logger.info(f"[dry_run] would write {timestamped_path} & latest.html")
    else:
        timestamped_path.write_text(page, encoding="utf-8")
        latest_path.write_text(page, encoding="utf-8")
        logger.info(f"📁 웹페이지 저장: {timestamped_path.name} (+ latest.html 갱신)")

    rebuild_index()
    return timestamped_path


def rebuild_index() -> Path:
    """archive 목록 기반으로 index.html 새로 작성. 날짜별로 그룹핑 + 시간 표시."""
    files = _list_archive()
    count = len(files)

    if files:
        latest_stem, _ = files[0]
        # 시간 정보 파싱
        if re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}$", latest_stem):
            d = latest_stem[:10]
            t = latest_stem[11:13] + ":" + latest_stem[13:15]
            latest_label = f"{d} {t}"
        else:
            latest_label = latest_stem
        latest_block = (
            f'<div class="latest-box">'
            f'<a href="latest.html">📅 가장 최근 리포트 ({latest_label})</a>'
            f'</div>'
        )
    else:
        latest_block = (
            '<div class="latest-box">'
            '<span style="color:#95a5a6">아직 생성된 리포트가 없어요.</span>'
            '</div>'
        )

    # 날짜별로 그룹핑
    if files:
        from collections import defaultdict
        grouped = defaultdict(list)
        for stem, _ in files:
            if re.match(r"^\d{4}-\d{2}-\d{2}-\d{4}$", stem):
                date = stem[:10]
                time_str = stem[11:13] + ":" + stem[13:15]
                grouped[date].append((time_str, stem))
            else:
                grouped[stem].append(("—", stem))

        sections = []
        for date in sorted(grouped.keys(), reverse=True):
            entries = sorted(grouped[date], reverse=True)
            sections.append(f'<div class="day-group"><h3>📅 {date}</h3><ul class="archive-list">')
            for time_str, stem in entries:
                if time_str == "—":
                    sections.append(f'<li><a href="{stem}.html">📄 (시간 미상)</a></li>')
                else:
                    sections.append(f'<li><a href="{stem}.html">🕐 {time_str}</a></li>')
            sections.append('</ul></div>')
        archive_html = "\n".join(sections)
    else:
        archive_html = '<p class="empty">아직 리포트가 없습니다.</p>'

    page = INDEX_TEMPLATE.format(
        latest_block=latest_block,
        count=count,
        archive_html=archive_html,
    )
    index_path = DOCS_DIR / "index.html"
    index_path.write_text(page, encoding="utf-8")
    logger.info(f"📁 index.html 갱신 (archive {count}개)")
    return index_path


if __name__ == "__main__":
    from utils import setup_logging
    setup_logging()
    publish("<h2>테스트</h2><p>퍼블리셔 테스트입니다.</p>")
