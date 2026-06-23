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
  SEEN_IDS_FILE       - Path to JSON file tracking seen tweet IDs
"""

import os
import json
import smtplib
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

_DEFAULT_SEEN_IDS = Path.home() / "daikei_check" / ".seen_tweet_ids.json"
SEEN_IDS_FILE = Path(os.environ.get("SEEN_IDS_FILE", str(_DEFAULT_SEEN_IDS)))


def load_seen_ids() -> set[str]:
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids: set[str]) -> None:
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-500:]))


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


def do_login(context) -> bool:
    if not X_USERNAME or not X_PASSWORD:
        print("X_USERNAME/X_PASSWORD not set, cannot log in")
        return False
    page = context.new_page()
    try:
        page.goto("https://x.com/i/flow/login", wait_until="load", timeout=30000)
        page.wait_for_timeout(2000)

        page.fill('input[name="text"]', X_USERNAME)
        page.get_by_role("button", name="Next").click()
        page.wait_for_timeout(2000)

        # Handle phone/email verification step if it appears
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
        page = context.new_page()
        try:
            page.goto(f"https://x.com/{TARGET_USERNAME}", wait_until="load", timeout=30000)
            page.wait_for_timeout(3000)

            # Login wall check
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

            # Scroll once to load more tweets
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

    tweets = fetch_tweets()

    if not tweets:
        send_email(
            subject=f"[X Monitor] @{TARGET_USERNAME} のツイート取得に失敗しました",
            body=(
                f"本日の定期チェックでツイートを取得できませんでした。\n\n"
                f"確認アカウント: https://x.com/{TARGET_USERNAME}\n"
            ),
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
                body=(
                    f"@{TARGET_USERNAME} がキーワードを含む投稿を検知しました。\n\n"
                    f"--- 投稿内容 ---\n{tweet['text']}\n\n"
                    f"--- リンク ---\n{tweet['url']}\n"
                ),
            )
            matched += 1

    if matched == 0:
        send_email(
            subject=f"[X Monitor] @{TARGET_USERNAME} の本日の確認結果",
            body=(
                f"本日の定期チェックを実施しました。\n\n"
                f"キーワード「{'・'.join(KEYWORDS)}」を含む新しい投稿はありませんでした。\n\n"
                f"確認アカウント: https://x.com/{TARGET_USERNAME}\n"
            ),
        )

    print(f"Checked {len(tweets)} tweet(s), sent {matched} match notification(s).")
    save_seen_ids(seen_ids | new_ids)


if __name__ == "__main__":
    main()
