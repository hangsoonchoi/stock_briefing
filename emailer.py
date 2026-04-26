"""
Gmail SMTP 이메일 발송 + 텔레그램 알림 (선택)

텔레그램 봇 토큰/chat_id가 .env에 있으면 발송 실패 시
텔레그램으로도 알림. 큰 시그널 푸시 백업용.
"""

import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

from utils import logger


EMAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo",
                 "맑은 고딕", "Malgun Gothic", sans-serif;
    line-height: 1.6;
    color: #2c3e50;
    max-width: 760px;
    margin: 0 auto;
    padding: 20px;
    background: #fafafa;
  }}
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
</style>
</head>
<body>
  <div class="header">
    <h1>📊 오늘의 시장 브리핑</h1>
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


def send_email(html_body: str, subject_suffix: str = "") -> None:
    """Gmail SMTP로 HTML 본문 발송."""
    sender = os.environ["SENDER_EMAIL"]
    app_password = os.environ["SENDER_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    today = datetime.now().strftime("%Y년 %m월 %d일 (%a)")
    full_html = EMAIL_TEMPLATE.format(date_str=today, body=html_body)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 시장 브리핑 - {today} {subject_suffix}".strip()
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(full_html, "html", "utf-8"))

    logger.info(f"✉️  {recipient} 으로 발송 중...")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(sender, app_password.replace(" ", ""))
            server.send_message(msg)
        logger.info("✅ 이메일 발송 완료")
    except Exception as e:
        logger.error(f"이메일 실패: {e}")
        # 텔레그램 fallback (있으면)
        send_telegram_fallback(f"⚠️ 이메일 발송 실패 — {e}")
        raise


def send_telegram_fallback(text: str) -> bool:
    """선택사항: 텔레그램 봇으로 짧은 알림. 키 없으면 조용히 패스."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text[:3500]},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        logger.warning(f"텔레그램 발송 실패: {e}")
        return False


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from utils import setup_logging
    setup_logging()
    send_email("<h2>테스트</h2><p>이메일 발송 테스트입니다.</p>", subject_suffix="(TEST)")
