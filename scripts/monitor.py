#!/usr/bin/env python3
"""
Twitter/X monitor via Nitter RSS (no API key, no browser required).
Tries multiple Nitter instances in order and sends a Gmail alert when
a new tweet from TARGET_USERNAME matches any of the KEYWORDS.

Required environment variables:
  TARGET_USERNAME     - Twitter/X username to monitor (without @)
  KEYWORDS            - Comma-separated keywords to watch for
  GMAIL_ADDRESS       - Gmail address used to send (App Password required)
  GMAIL_APP_PASSWORD  - Gmail App Password (16 chars, no spaces)
  TO_EMAIL            - Recipient address (optional, defaults to GMAIL_ADDRESS)
"""

import os
import json
import smtplib
import requests
import feedparser
from pathlib import Path
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

TARGET_USERNAME = os.environ["TARGET_USERNAME"]
KEYWORDS = [k.strip().lower() for k in os.environ["KEYWORDS"].split(",") if k.strip()]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL = os.environ.get("TO_EMAIL", GMAIL_ADDRESS)

SEEN_IDS_FILE = Path(os.environ.get("SEEN_IDS_FILE", ".seen_tweet_ids.json"))

NITTER_INSTANCES = [
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.kavin.rocks",
    "https://nitter.nl",
    "https://nitter.1d4.us",
    "https://nitter.unixfox.eu",
]


def load_seen_ids() -> set[str]:
    if SEEN_IDS_FILE.exists():
        return set(json.loads(SEEN_IDS_FILE.read_text()))
    return set()


def save_seen_ids(ids: set[str]) -> None:
    SEEN_IDS_FILE.write_text(json.dumps(list(ids)[-500:]))


def fetch_rss() -> list[dict]:
    """Try each Nitter instance until one returns feed entries."""
    for instance in NITTER_INSTANCES:
        url = f"{instance}/{TARGET_USERNAME}/rss"
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                print(f"{instance} → HTTP {resp.status_code}, skipping")
                continue

            feed = feedparser.parse(resp.text)
            if not feed.entries:
                print(f"{instance} → no entries, skipping")
                continue

            print(f"{instance} → {len(feed.entries)} entries found")
            tweets = []
            for entry in feed.entries:
                tweet_id = entry.get("id", "").split("/status/")[-1].split("#")[0]
                text = entry.get("title", "") or entry.get("summary", "")
                if tweet_id and text:
                    tweets.append({"id": tweet_id, "text": text, "url": entry.get("link", "")})
            return tweets

        except Exception as e:
            print(f"{instance} → error: {e}, skipping")
            continue

    return []


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
    seen_ids = load_seen_ids()

    tweets = fetch_rss()

    if not tweets:
        send_email(
            subject=f"[X Monitor] @{TARGET_USERNAME} のRSS取得に失敗しました",
            body=(
                f"本日の定期チェックでNitter RSSからツイートを取得できませんでした。\n\n"
                f"全てのNitterサーバーが応答しませんでした。\n\n"
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
                f"キーワード「{'・'.join(KEYWORDS)}」を含む新しい投稿はありませんでした。\n\n"
                f"確認アカウント: https://x.com/{TARGET_USERNAME}\n"
            ),
        )

    print(f"Checked {len(tweets)} tweet(s), sent {matched} match notification(s).")
    save_seen_ids(seen_ids | new_ids)


if __name__ == "__main__":
    main()
