#!/usr/bin/env python3
"""
Twitter/X monitor via Playwright (headless browser).
Navigates to the target profile, extracts tweets, and sends a Gmail alert
when a new tweet matches any of the configured keywords.

Required environment variables:
  TARGET_USERNAME     - Twitter/X username to monitor (without @)
  KEYWORDS            - Comma-separated keywords to watch for
  GMAIL_ADDRESS       - Gmail address used to send (App Password required)
  GMAIL_APP_PASSWORD  - Gmail App Password (16 chars, no spaces)
  TO_EMAIL            - Recipient address (optional, defaults to GMAIL_ADDRESS)
  X_USERNAME          - X/Twitter login username or email
  X_PASSWORD          - X/Twitter login password
  X_VERIFY            - Phone number or email for unusual-activity check (optional)
  SEEN_IDS_FILE       - Path to JSON file tracking seen tweet IDs
  COOKIES_FILE        - Path to JSON file storing session cookies (optional)
"""

import os
import sys
import json
import smtplib
from datetime import datetime, timezone
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
X_VERIFY = os.environ.get("X_VERIFY", "")

_DEFAULT_SEEN_IDS = Path.home() / "daikei_check" / ".seen_tweet_ids.json"
SEEN_IDS_FILE = Path(os.environ.get("SEEN_IDS_FILE", str(_DEFAULT_SEEN_IDS)))

_DEFAULT_LOG = Path.home() / "apps" / "daikei_check" / "monitor_log.json"
MONITOR_LOG_FILE = Path(os.environ.get("MONITOR_LOG_FILE", str(_DEFAULT_LOG)))

_DEFAULT_COOKIES = Path(".x_cookies.json")
COOKIES_FILE = Path(os.environ.get("COOKIES_FILE", str(_DEFAULT_COOKIES)))


def write_log(status: str, checked: int, matched: int, message: str, matches: list[dict] | None = None) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "checked": checked,
        "matched": matched,
        "message": message,
    }
    if matches:
        entry["matches"] = matches
    try:
        logs = json.loads(MONITOR_LOG_FILE.read_text()) if MONITOR_LOG_FILE.exists() else []
        logs.insert(0, entry)
        MONITOR_LOG_FILE.write_text(json.dumps(logs[:30], ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Log write error: {e}")


def load_seen_ids() -> list[str]:
    if SEEN_IDS_FILE.exists():
        return json.loads(SEEN_IDS_FILE.read_text())
    return []


def save_seen_ids(ids: list[str]) -> None:
    # Keep as an order-preserving list (oldest first) so trimming to the last
    # 500 evicts genuinely old IDs instead of an arbitrary set() ordering.
    SEEN_IDS_FILE.write_text(json.dumps(ids[-500:]))


def send_email(subject: str, body: str) -> None:
    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = TO_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, TO_EMAIL, msg.as_string())
    print(f"Email sent: {subject}")


def save_cookies(context) -> None:
    try:
        cookies = context.cookies()
        COOKIES_FILE.write_text(json.dumps(cookies, ensure_ascii=False))
        COOKIES_FILE.chmod(0o600)
        print(f"Cookies saved to {COOKIES_FILE}")
    except Exception as e:
        print(f"Cookie save error: {e}")


def load_cookies(context) -> bool:
    if not COOKIES_FILE.exists():
        return False
    try:
        cookies = json.loads(COOKIES_FILE.read_text())
        context.add_cookies(cookies)
        print(f"Cookies loaded from {COOKIES_FILE}")
        return True
    except Exception as e:
        print(f"Cookie load error: {e}")
        return False


def check_logged_in(page) -> bool:
    try:
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(3000)
        logged_in = (
            "/home" in page.url
            and page.locator('[data-testid="AppTabBar_Home_Link"]').count() > 0
        )
        print(f"Session check: {'valid' if logged_in else 'expired'} (url={page.url})")
        return logged_in
    except Exception as e:
        print(f"Session check error: {e}")
        return False


def do_login(context) -> bool:
    if not X_USERNAME or not X_PASSWORD:
        print("X_USERNAME/X_PASSWORD not set, cannot log in")
        return False
    page = context.new_page()
    try:
        page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        print(f"Login page: {page.url}")

        # Step 1: Username (X uses autocomplete="username" since ~2023)
        username_input = page.locator('input[autocomplete="username"]').first
        username_input.wait_for(state="visible", timeout=15000)
        username_input.fill(X_USERNAME)
        page.wait_for_timeout(500)

        # Click "Next" / "次へ"
        next_btn = page.locator('[data-testid="LoginForm_Login_Button"]').first
        if next_btn.count() == 0:
            # Fallback: any "Next"/"次へ" button in the form
            next_btn = page.locator('button:has-text("次へ"), button:has-text("Next")').first
        next_btn.click()
        page.wait_for_timeout(3000)
        print(f"After Next: {page.url}")

        # Step 1.5: Unusual activity check (X may ask for phone/email)
        unusual = page.locator('input[data-testid="ocfEnterTextTextInput"]')
        if unusual.count() > 0:
            print("Unusual activity check triggered")
            if X_VERIFY:
                unusual.fill(X_VERIFY)
                page.locator('[data-testid="ocfEnterTextNextButton"]').click()
                page.wait_for_timeout(2000)
            else:
                print("X_VERIFY not set — cannot complete unusual activity check")
                return False

        # Step 2: Password
        password_input = page.locator('input[name="password"]').first
        password_input.wait_for(state="visible", timeout=15000)
        password_input.fill(X_PASSWORD)
        page.wait_for_timeout(500)

        # Click "Log in" / "ログイン"
        login_btn = page.locator('[data-testid="LoginForm_Login_Button"]').first
        login_btn.click()
        page.wait_for_timeout(6000)
        print(f"After login: {page.url}")

        logged_in = (
            "/home" in page.url
            or page.locator('[data-testid="AppTabBar_Home_Link"]').count() > 0
        )
        if logged_in:
            save_cookies(context)
        print(f"Login {'succeeded' if logged_in else 'failed'}")
        return logged_in
    except Exception as e:
        print(f"Login error: {e}")
        return False
    finally:
        page.close()


def ensure_logged_in(context) -> bool:
    """Use saved cookies if valid, otherwise do full login."""
    cookies_loaded = load_cookies(context)
    if cookies_loaded:
        page = context.new_page()
        try:
            if check_logged_in(page):
                return True
            print("Saved cookies expired, re-logging in...")
        finally:
            page.close()

    # Full login
    return do_login(context)


def fetch_tweets() -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
        )
        try:
            if not ensure_logged_in(context):
                browser.close()
                return []

            page = context.new_page()
            page.goto(f"https://x.com/{TARGET_USERNAME}", wait_until="load", timeout=30000)
            page.wait_for_timeout(4000)

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

        except PlaywrightTimeout as e:
            print(f"Timeout: {e}")
            browser.close()
            return []
        except Exception as e:
            print(f"Error: {e}")
            browser.close()
            return []


def main() -> None:
    print(f"Monitoring @{TARGET_USERNAME} for: {KEYWORDS}")
    seen_ids = load_seen_ids()
    seen_set = set(seen_ids)

    tweets = fetch_tweets()

    if not tweets:
        print("No tweets fetched — skipping email, logging error only.")
        write_log("error", 0, 0, "ツイートの取得に失敗しました")
        sys.exit(1)

    new_ids = []
    matched = 0
    match_details = []
    for tweet in tweets:
        tid = tweet["id"]
        if tid not in seen_set:
            new_ids.append(tid)
        if tid in seen_set:
            continue
        if any(kw in tweet["text"].lower() for kw in KEYWORDS):
            print(f"Match: {tweet['text'][:80]}")
            send_email(
                subject=f"[X Monitor] @{TARGET_USERNAME} が「{'・'.join(KEYWORDS)}」を含む投稿をしました",
                body=(
                    f"@{TARGET_USERNAME} がキーワードを含む投稿を検知しました。\n\n"
                    f"--- 投稿内容 ---\n{tweet['text']}\n\n"
                    f"--- リンク ---\n{tweet['url']}\n"
                ),
            )
            match_details.append({"text": tweet["text"][:200], "url": tweet["url"]})
            matched += 1

    if matched == 0:
        print("No keyword matches — no email sent.")
        write_log("ok", len(tweets), 0, f"{len(tweets)}件チェック。キーワード一致なし。")
    else:
        write_log("match", len(tweets), matched,
                  f"{len(tweets)}件チェック。{matched}件のキーワード一致を検知。",
                  match_details)

    print(f"Checked {len(tweets)} tweet(s), sent {matched} match notification(s).")
    save_seen_ids(seen_ids + new_ids)


if __name__ == "__main__":
    main()
