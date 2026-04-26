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


DOCS_DIR = Path(__file__).parent / "docs"
DOCS_DIR.mkdir(exist_ok=True)


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo",
                 "맑은 고딕", "Malgun Gothic", sans-serif;
    line-height: 1.6;
    color: #2c3e50;
    max-width: 760px;
    margin: 0 auto;
    padding: 16px;
    background: #fafafa;
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
    padding: 4px 10px;
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
  .header h1 {{ margin: 0 0 8px 0; font-size: 22px; }}
  .header .date {{ opacity: 0.85; font-size: 14px; }}
  .content {{
    background: white;
    padding: 24px 28px;
    border-radius: 0 0 12px 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
  }}
  .content h2 {{
    border-bottom: 2px solid #ecf0f1;
    padding-bottom: 8px;
    margin-top: 28px;
    font-size: 18px;
  }}
  .content h2:first-child {{ margin-top: 0; }}
  .content table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
    font-size: 14px;
  }}
  .content th, .content td {{
    padding: 8px 12px;
    border-bottom: 1px solid #ecf0f1;
    text-align: left;
  }}
  .content th {{ background: #f8f9fa; font-weight: 600; }}
  .footer {{
    text-align: center;
    color: #95a5a6;
    font-size: 12px;
    margin-top: 24px;
    padding: 16px;
  }}
  .up {{ color: #c0392b; font-weight: 600; }}
  .down {{ color: #2980b9; font-weight: 600; }}
  ul.archive-list {{ list-style: none; padding: 0; }}
  ul.archive-list li {{
    padding: 10px 12px;
    border-bottom: 1px solid #ecf0f1;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }}
  ul.archive-list li:hover {{ background: #f8f9fa; }}
  ul.archive-list a {{
    color: #2980b9;
    text-decoration: none;
    font-weight: 500;
  }}
  @media (max-width: 600px) {{
    body {{ padding: 8px; }}
    .header {{ padding: 16px; border-radius: 10px 10px 0 0; }}
    .content {{ padding: 16px; }}
  }}
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
    {body}
  </div>
  <div class="footer">
    이 리포트는 자동 생성된 정보 정리이며 투자 자문이 아닙니다.<br>
    모든 투자 판단과 결과의 책임은 본인에게 있습니다.
  </div>
</body>
</html>
"""


INDEX_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
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
  ul.archive-list {{
    list-style: none;
    padding: 0;
    margin: 0;
  }}
  ul.archive-list li {{
    padding: 12px 0;
    border-bottom: 1px solid #ecf0f1;
  }}
  ul.archive-list li:last-child {{ border-bottom: none; }}
  ul.archive-list a {{
    color: #2980b9;
    text-decoration: none;
    font-weight: 500;
    font-size: 15px;
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
    """docs/ 안의 YYYY-MM-DD.html 파일 목록 (최신순)."""
    files = []
    for p in DOCS_DIR.glob("*.html"):
        if re.match(r"^\d{4}-\d{2}-\d{2}\.html$", p.name):
            files.append((p.stem, p))
    files.sort(key=lambda x: x[0], reverse=True)
    return files


def publish(html_body: str, dry_run: bool = False) -> Path:
    """
    오늘 날짜 HTML 페이지 작성 + latest.html + index.html 갱신.
    반환값은 오늘 날짜 페이지 경로.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    today_kor = datetime.now().strftime("%Y년 %m월 %d일 (%a)")

    page = PAGE_TEMPLATE.format(
        title=f"시장 브리핑 — {today}",
        header="📊 오늘의 시장 브리핑",
        date_str=today_kor,
        body=html_body,
    )

    today_path = DOCS_DIR / f"{today}.html"
    latest_path = DOCS_DIR / "latest.html"

    if dry_run:
        logger.info(f"[dry_run] would write {today_path} & {latest_path}")
    else:
        today_path.write_text(page, encoding="utf-8")
        latest_path.write_text(page, encoding="utf-8")
        logger.info(f"📁 웹페이지 저장: {today_path.name} & latest.html")

    # index.html 갱신
    rebuild_index()

    return today_path


def rebuild_index() -> Path:
    """archive 목록 기반으로 index.html 새로 작성."""
    files = _list_archive()
    count = len(files)

    if files:
        latest_date, _ = files[0]
        latest_block = (
            f'<div class="latest-box">'
            f'<a href="latest.html">📅 가장 최근 리포트 보기 ({latest_date})</a>'
            f'</div>'
        )
    else:
        latest_block = (
            '<div class="latest-box">'
            '<span style="color:#95a5a6">아직 생성된 리포트가 없어요.</span>'
            '</div>'
        )

    if files:
        items = []
        for date_str, _ in files:
            items.append(
                f'<li><a href="{date_str}.html">📄 {date_str}</a></li>'
            )
        archive_html = (
            '<ul class="archive-list">' + "\n".join(items) + "</ul>"
        )
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
