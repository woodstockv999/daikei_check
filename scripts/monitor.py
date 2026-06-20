#!/usr/bin/env python3
"""
Twitter/X monitor using twscrape (no official API key required).
Uses X's internal web API with account credentials.

Required environment variables:
  TARGET_USERNAME     - Twitter/X username to monitor (without @)
  KEYWORDS            - Comma-separated keywords to watch for
  GMAIL_ADDRESS       - Gmail address (App Password required)
  GMAIL_APP_PASSWORD  - Gmail App Password (16 chars, no spaces)
  X_USERNAME          - Your X account username or email
  X_PASSWORD          - Your X account password
  TO_EMAIL            - Recipient address (optional, defaults to GMAIL_ADDRESS)
"""

import os
import json
import asyncio
import smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import twscrape

TARGET_USERNAME = os.environ["TARGET_USERNAME"]
KEYWORDS = [k.strip().lower() for k in os.environ["KEYWORDS"].split(",") if k.strip()]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
X_USERNAME = os.environ["X_USERNAME"]
X_PASSWORD = os.environ["X_PASSWORD"]
TO_EMAIL = os.environ.get("TO_EMAIL") or GMAIL_ADDRESS

SEEN_IDS_FILE = Path(os.environ.get("SEEN_IDS_FILE", ".seen_tweet_ids.json"))


def load_seen_ids() -> set[str]:
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids: set[str]) -> None:
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-500:]))


async def fetch_tweets_async() -> list[dict]:
    api = twscrape.API()
    await api.pool.add_account(
        username=X_USERNAME,
        password=X_PASSWORD,
        email=X_USERNAME,
        email_password=X_PASSWORD,
    )
    await api.pool.login_all()

    user = await api.user_by_login(TARGET_USERNAME)
    if not user:
        print(f"User @{TARGET_USERNAME} not found.")
        return []

    tweets = []
    async for tweet in api.user_tweets(user.id, limit=20):
        tweets.append({
            "id": str(tweet.id),
            "text": tweet.rawContent,
            "url": tweet.url,
        })

    print(f"Fetched {len(tweets)} tweets from @{TARGET_USERNAME}")
    return tweets


def fetch_tweets() -> list[dict]:
    return asyncio.run(fetch_tweets_async())


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


def main() -> None:
    print(f"Monitoring @{TARGET_USERNAME} for: {KEYWORDS}")
    print(f"Sending to: {TO_EMAIL}")
    seen_ids = load_seen_ids()

    try:
        tweets = fetch_tweets()
    except Exception as e:
        print(f"Error fetching tweets: {e}")
        send_email(
            subject=f"[X Monitor] @{TARGET_USERNAME} のツイート取得に失敗しました",
            body=(
                f"ツイートの取得中にエラーが発生しました。\n\n"
                f"エラー内容: {e}\n\n"
                f"確認アカウント: https://x.com/{TARGET_USERNAME}\n"
            ),
        )
        return

    if not tweets:
        send_email(
            subject=f"[X Monitor] @{TARGET_USERNAME} のツイート取得に失敗しました",
            body=(
                f"ツイートを取得できませんでした。\n"
                f"アカウントが存在しないか、ログインに失敗した可能性があります。\n\n"
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
        if tweet_matches(tweet["text"]):
            print(f"Match: {tweet['text'][:80]}...")
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
                f"キーワード「{chr(12539).join(KEYWORDS)}」を含む新しい投稿はありませんでした。\n\n"
                f"確認アカウント: https://x.com/{TARGET_USERNAME}\n"
            ),
        )

    print(f"Checked {len(tweets)} tweet(s), sent {matched} match notification(s).")
    save_seen_ids(seen_ids | new_ids)


if __name__ == "__main__":
    main()
