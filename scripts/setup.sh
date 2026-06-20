#!/bin/bash
# Daikei Monitor VPS セットアップスクリプト
# Ubuntu 24.04 向け
set -e

INSTALL_DIR="/opt/daikei_monitor"
LOG_FILE="/var/log/daikei_monitor.log"

echo "========================================"
echo "  Daikei Monitor セットアップ"
echo "========================================"
echo ""

# --- システムパッケージ ---
echo "[1/5] システムパッケージをインストール中..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git curl

# --- ディレクトリ作成 ---
echo "[2/5] ディレクトリを作成中..."
mkdir -p "$INSTALL_DIR/scripts"

# --- monitor.py を書き込み ---
echo "[3/5] モニタースクリプトを作成中..."
cat > "$INSTALL_DIR/scripts/monitor.py" << 'PYEOF'
#!/usr/bin/env python3
import os, json, smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

TARGET_USERNAME = os.environ["TARGET_USERNAME"]
KEYWORDS = [k.strip().lower() for k in os.environ["KEYWORDS"].split(",") if k.strip()]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL = os.environ.get("TO_EMAIL") or GMAIL_ADDRESS
X_USERNAME = os.environ.get("X_USERNAME", "")
X_PASSWORD = os.environ.get("X_PASSWORD", "")
SEEN_IDS_FILE = Path(os.environ.get("SEEN_IDS_FILE", "/opt/daikei_monitor/.seen_tweet_ids.json"))

def load_seen_ids():
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()

def save_seen_ids(ids):
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-500:]))

def send_email(subject, body):
    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = TO_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, TO_EMAIL, msg.as_string())
    print(f"Email sent: {subject}")

def do_login(context):
    if not X_USERNAME or not X_PASSWORD:
        print("X_USERNAME/X_PASSWORD not set")
        return False
    page = context.new_page()
    try:
        page.goto("https://x.com/i/flow/login", wait_until="load", timeout=30000)
        page.wait_for_timeout(2000)
        page.fill('input[name="text"]', X_USERNAME)
        page.get_by_role("button", name="Next").click()
        page.wait_for_timeout(2000)
        if page.locator('input[name="text"]').count() > 0:
            page.fill('input[name="text"]', X_USERNAME)
            page.get_by_role("button", name="Next").click()
            page.wait_for_timeout(2000)
        page.fill('input[name="password"]', X_PASSWORD)
        page.get_by_role("button", name="Log in").click()
        page.wait_for_timeout(4000)
        logged_in = "home" in page.url or page.locator('[data-testid="AppTabBar_Home_Link"]').count() > 0
        print(f"Login {'succeeded' if logged_in else 'may have failed'}")
        return logged_in
    except Exception as e:
        print(f"Login error: {e}")
        return False
    finally:
        page.close()

def fetch_tweets():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        page = context.new_page()
        try:
            page.goto(f"https://x.com/{TARGET_USERNAME}", wait_until="load", timeout=30000)
            page.wait_for_timeout(3000)
            needs_login = (
                "login" in page.url
                or page.locator('input[name="text"]').count() > 0
                or page.locator('[data-testid="loginButton"]').count() > 0
            )
            if needs_login:
                print("Login required, attempting login...")
                if not do_login(context):
                    browser.close()
                    return []
                page.goto(f"https://x.com/{TARGET_USERNAME}", wait_until="load", timeout=30000)
                page.wait_for_timeout(3000)
            page.keyboard.press("End")
            page.wait_for_timeout(2000)
            tweets = []
            articles = page.locator('article[data-testid="tweet"]').all()
            print(f"Found {len(articles)} tweet articles")
            for article in articles[:20]:
                try:
                    text_el = article.locator('[data-testid="tweetText"]')
                    if text_el.count() == 0:
                        continue
                    text = text_el.inner_text()
                    tweet_id = ""
                    tweet_url = ""
                    for link in article.locator('a[href*="/status/"]').all():
                        href = link.get_attribute("href") or ""
                        if "/status/" in href:
                            tweet_id = href.split("/status/")[-1].split("?")[0]
                            tweet_url = f"https://x.com{href}" if href.startswith("/") else href
                            break
                    if text and tweet_id:
                        tweets.append({"id": tweet_id, "text": text, "url": tweet_url})
                except Exception as e:
                    print(f"Error parsing article: {e}")
            browser.close()
            return tweets
        except Exception as e:
            print(f"Error: {e}")
            browser.close()
            return []

def main():
    print(f"Monitoring @{TARGET_USERNAME} for: {KEYWORDS}")
    seen_ids = load_seen_ids()
    tweets = fetch_tweets()
    if not tweets:
        send_email(
            subject=f"[X Monitor] @{TARGET_USERNAME} のツイート取得に失敗しました",
            body=f"本日の定期チェックでツイートを取得できませんでした。\n\n確認アカウント: https://x.com/{TARGET_USERNAME}\n",
        )
        return
    new_ids = set()
    matched = 0
    for tweet in tweets:
        tid = tweet["id"]
        new_ids.add(tid)
        if tid in seen_ids:
            continue
        if any(kw in tweet["text"].lower() for kw in KEYWORDS):
            print(f"Match: {tweet['text'][:80]}")
            send_email(
                subject=f"[X Monitor] @{TARGET_USERNAME} が「{'・'.join(KEYWORDS)}」を含む投稿をしました",
                body=f"@{TARGET_USERNAME} がキーワードを含む投稿を検知しました。\n\n--- 投稿内容 ---\n{tweet['text']}\n\n--- リンク ---\n{tweet['url']}\n",
            )
            matched += 1
    if matched == 0:
        send_email(
            subject=f"[X Monitor] @{TARGET_USERNAME} の本日の確認結果",
            body=f"本日の定期チェックを実施しました。\n\nキーワード「{'・'.join(KEYWORDS)}」を含む新しい投稿はありませんでした。\n\n確認アカウント: https://x.com/{TARGET_USERNAME}\n",
        )
    print(f"Checked {len(tweets)} tweet(s), sent {matched} match notification(s).")
    save_seen_ids(seen_ids | new_ids)

if __name__ == "__main__":
    main()
PYEOF

chmod +x "$INSTALL_DIR/scripts/monitor.py"

# --- Python 環境 + Playwright ---
echo "[4/5] Python環境とPlaywrightをインストール中（数分かかります）..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
pip install -q --upgrade pip
pip install -q playwright
python -m playwright install chromium
python -m playwright install-deps chromium
deactivate

# --- 認証情報入力 ---
echo ""
echo "[5/5] 設定情報を入力してください"
echo "----------------------------------------"
read -p "Gmailアドレス: " GMAIL_ADDRESS
read -s -p "Gmailアプリパスワード (16文字): " GMAIL_APP_PASSWORD
echo ""
read -p "通知先メールアドレス (Enterでスキップ→Gmailと同じ): " TO_EMAIL
echo ""
echo "XのアカウントはX.comへのログインに使います。"
read -p "XのユーザーID または メールアドレス: " X_USERNAME
read -s -p "Xのパスワード: " X_PASSWORD
echo ""

# --- .env ファイル作成 ---
cat > "$INSTALL_DIR/.env" << ENV
TARGET_USERNAME=daikei_org
KEYWORDS=予約
GMAIL_ADDRESS=${GMAIL_ADDRESS}
GMAIL_APP_PASSWORD=${GMAIL_APP_PASSWORD}
TO_EMAIL=${TO_EMAIL}
X_USERNAME=${X_USERNAME}
X_PASSWORD=${X_PASSWORD}
SEEN_IDS_FILE=${INSTALL_DIR}/.seen_tweet_ids.json
ENV

chmod 600 "$INSTALL_DIR/.env"

# --- 実行スクリプト作成 ---
cat > "$INSTALL_DIR/run.sh" << 'RUNEOF'
#!/bin/bash
set -a
source /opt/daikei_monitor/.env
set +a
source /opt/daikei_monitor/venv/bin/activate
python /opt/daikei_monitor/scripts/monitor.py
RUNEOF

chmod +x "$INSTALL_DIR/run.sh"

# --- cron 設定 (毎日9時JST = 0:00 UTC) ---
(crontab -l 2>/dev/null | grep -v daikei_monitor; echo "0 0 * * * /opt/daikei_monitor/run.sh >> ${LOG_FILE} 2>&1") | crontab -

echo ""
echo "========================================"
echo "  セットアップ完了！"
echo "========================================"
echo ""
echo "今すぐテスト実行:"
echo "  bash /opt/daikei_monitor/run.sh"
echo ""
echo "ログ確認:"
echo "  cat ${LOG_FILE}"
echo ""
echo "自動実行: 毎日 午前9時(JST) に実行されます"
echo ""
