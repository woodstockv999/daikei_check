#!/usr/bin/env python3
"""
Twitter/X monitor using Playwright (no API key required).
Opens x.com/<TARGET_USERNAME> in a headless browser, finds new tweets
containing any of the configured KEYWORDS, and sends a Gmail alert.

Required environment variables:
  TARGET_USERNAME     - Twitter/X username to monitor (without @)
  KEYWORDS            - Comma-separated keywords to watch for
  GMAIL_ADDRESS       - Gmail address used to send (must have App Password enabled)
  GMAIL_APP_PASSWORD  - Gmail App Password
  TO_EMAIL            - Recipient address (optional, defaults to GMAIL_ADDRESS)

Optional (for login — needed if X.com blocks anonymous access):
  X_USERNAME          - Your X account username or email
  X_PASSWORD          - Your X account password
"""

import os
import sys
import json
import smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

TARGET_USERNAME = os.environ["TARGET_USERNAME"]
KEYWORDS = [k.strip().lower() for k in os.environ["KEYWORDS"].split(",") if k.strip()]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL = os.environ.get("TO_EMAIL", GMAIL_ADDRESS)
X_USERNAME = os.environ.get("X_USERNAME", "")
X_PASSWORD = os.environ.get("X_PASSWORD", "")

SEEN_IDS_FILE = Path(os.environ.get("SEEN_IDS_FILE", ".seen_tweet_ids.json"))
PROFILE_URL = f"https://x.com/{TARGET_USERNAME}"


def load_seen_ids() -> set[str]:
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids: set[str]) -> None:
    # Keep only the latest 500 IDs to avoid unbounded growth
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-500:]))


def save_screenshot(page, name: str) -> None:
    path = f"debug_{name}.png"
    page.screenshot(path=path, full_page=True)
    print(f"Screenshot saved: {path}")


def login(page) -> None:
    print("Logging in to X.com...")
    page.goto("https://x.com/i/flow/login", wait_until="load", timeout=30000)
    page.wait_for_timeout(2000)
    save_screenshot(page, "01_login_page")

    # Username field (X.com uses input[name="text"] or input[autocomplete="username"])
    username_found = False
    for sel in ['input[autocomplete="username"]', 'input[name="text"]', 'input[type="text"]']:
        try:
            page.wait_for_selector(sel, timeout=5000)
            page.fill(sel, X_USERNAME)
            username_found = True
            print(f"Username field found: {sel}")
            break
        except PWTimeout:
            continue

    if not username_found:
        save_screenshot(page, "02_username_not_found")
        raise Exception("Username field not found on login page")

    page.keyboard.press("Enter")
    page.wait_for_timeout(2000)
    save_screenshot(page, "03_after_username")

    # X.com sometimes asks for email/phone verification ("unusual activity" check)
    try:
        verify = page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=4000)
        if verify:
            print("Unusual activity check detected, entering username again...")
            page.fill('input[data-testid="ocfEnterTextTextInput"]', X_USERNAME)
            page.keyboard.press("Enter")
            page.wait_for_timeout(2000)
    except PWTimeout:
        pass

    # Password field
    password_found = False
    for sel in ['input[name="password"]', 'input[type="password"]']:
        try:
            page.wait_for_selector(sel, timeout=8000)
            page.fill(sel, X_PASSWORD)
            password_found = True
            print(f"Password field found: {sel}")
            break
        except PWTimeout:
            continue

    if not password_found:
        save_screenshot(page, "04_password_not_found")
        raise Exception("Password field not found on login page")

    page.keyboard.press("Enter")
    page.wait_for_timeout(5000)
    save_screenshot(page, "05_after_login")
    print("Login completed.")


def scrape_tweets(page) -> list[dict]:
    """Return list of {id, text} dicts from the profile timeline."""
    page.goto(PROFILE_URL, wait_until="load", timeout=30000)

    try:
        page.wait_for_selector('article[data-testid="tweet"]', timeout=20000)
    except PWTimeout:
        print("No tweets found on page (possible login wall or empty timeline).")
        return []

    articles = page.query_selector_all('article[data-testid="tweet"]')
    tweets = []
    for article in articles:
        text_el = article.query_selector('[data-testid="tweetText"]')
        if not text_el:
            continue

        # Grab tweet ID from the permalink inside the article
        link_el = article.query_selector('a[href*="/status/"]')
        tweet_id = None
        if link_el:
            href = link_el.get_attribute("href") or ""
            parts = href.split("/status/")
            if len(parts) > 1:
                tweet_id = parts[1].split("/")[0].split("?")[0]

        if tweet_id:
            tweets.append({"id": tweet_id, "text": text_el.inner_text()})

    return tweets


def tweet_matches(text: str) -> bool:
    return any(kw in text.lower() for kw in KEYWORDS)


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


def send_match_email(tweet: dict) -> None:
    tweet_url = f"https://x.com/{TARGET_USERNAME}/status/{tweet['id']}"
    send_email(
        subject=f"[X Monitor] @{TARGET_USERNAME} がキーワードを含む投稿をしました",
        body=(
            f"@{TARGET_USERNAME} がキーワード({', '.join(KEYWORDS)})を含む投稿を検知しました。\n\n"
            f"--- 投稿内容 ---\n{tweet['text']}\n\n"
            f"--- リンク ---\n{tweet_url}\n"
        ),
    )


def send_no_update_email() -> None:
    send_email(
        subject=f"[X Monitor] @{TARGET_USERNAME} の本日の確認結果",
        body=(
            f"本日の定期チェックを実施しました。\n\n"
            f"キーワード「{', '.join(KEYWORDS)}」を含む新しい投稿はありませんでした。\n\n"
            f"--- 確認アカウント ---\n"
            f"https://x.com/{TARGET_USERNAME}\n"
        ),
    )


def main() -> None:
    print(f"Monitoring @{TARGET_USERNAME} for: {KEYWORDS}")
    seen_ids = load_seen_ids()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ja-JP",
        )
        page = context.new_page()

        if X_USERNAME and X_PASSWORD:
            login(page)

        tweets = scrape_tweets(page)
        browser.close()

    if not tweets:
        print("No tweets retrieved.")
        send_email(
            subject=f"[X Monitor] @{TARGET_USERNAME} のツイート取得に失敗しました",
            body=(
                f"本日の定期チェックでツイートを取得できませんでした。\n\n"
                f"X.comのログインが必要になっている可能性があります。\n"
                f"X_USERNAME / X_PASSWORD を Secrets に設定してください。\n\n"
                f"--- 確認アカウント ---\n"
                f"https://x.com/{TARGET_USERNAME}\n"
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
        if tweet_matches(tweet["text"]):
            print(f"Match: {tweet['text'][:80]}...")
            send_match_email(tweet)
            matched += 1

    if matched == 0:
        send_no_update_email()

    print(f"Checked {len(tweets)} tweet(s), sent {matched} match notification(s).")
    save_seen_ids(seen_ids | new_ids)


if __name__ == "__main__":
    main()
