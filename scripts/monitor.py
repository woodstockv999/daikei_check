#!/usr/bin/env python3
"""
Twitter/X post monitor: checks a specific user's recent tweets for keywords
and sends a Gmail notification when a match is found.

Required environment variables:
  TWITTER_BEARER_TOKEN  - Twitter API v2 Bearer Token
  TARGET_USERNAME       - Twitter username to monitor (without @)
  KEYWORDS              - Comma-separated keywords to watch for
  GMAIL_ADDRESS         - Gmail address used to send (must have App Password enabled)
  GMAIL_APP_PASSWORD    - Gmail App Password (not your regular password)
  TO_EMAIL              - Recipient email address (optional, defaults to GMAIL_ADDRESS)
  LAST_TWEET_ID_FILE    - Path to file storing the last seen tweet ID (default: .last_tweet_id)
"""

import os
import sys
import json
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

BEARER_TOKEN = os.environ["TWITTER_BEARER_TOKEN"]
TARGET_USERNAME = os.environ["TARGET_USERNAME"]
KEYWORDS = [k.strip().lower() for k in os.environ["KEYWORDS"].split(",") if k.strip()]
GMAIL_ADDRESS = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL = os.environ.get("TO_EMAIL", GMAIL_ADDRESS)
LAST_TWEET_ID_FILE = Path(os.environ.get("LAST_TWEET_ID_FILE", ".last_tweet_id"))

HEADERS = {"Authorization": f"Bearer {BEARER_TOKEN}"}
API_BASE = "https://api.twitter.com/2"


def get_user_id(username: str) -> str:
    url = f"{API_BASE}/users/by/username/{username}"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()
    if "errors" in data:
        print(f"Error fetching user ID: {data['errors']}", file=sys.stderr)
        sys.exit(1)
    return data["data"]["id"]


def fetch_recent_tweets(user_id: str, since_id: str | None) -> list[dict]:
    url = f"{API_BASE}/users/{user_id}/tweets"
    params = {
        "max_results": 10,
        "tweet.fields": "created_at,text",
        "exclude": "retweets,replies",
    }
    if since_id:
        params["since_id"] = since_id

    r = requests.get(url, headers=HEADERS, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    if data.get("meta", {}).get("result_count", 0) == 0:
        return []
    return data.get("data", [])


def tweet_matches(tweet_text: str) -> bool:
    text_lower = tweet_text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def send_email(tweet: dict, username: str) -> None:
    tweet_id = tweet["id"]
    tweet_text = tweet["text"]
    tweet_url = f"https://x.com/{username}/status/{tweet_id}"

    subject = f"[Twitter Alert] @{username} がキーワードを含む投稿をしました"
    body = f"""\
@{username} がキーワードを含む投稿を検知しました。

--- 投稿内容 ---
{tweet_text}

--- リンク ---
{tweet_url}
"""

    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = TO_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, TO_EMAIL, msg.as_string())

    print(f"Email sent for tweet {tweet_id}")


def load_last_id() -> str | None:
    if LAST_TWEET_ID_FILE.exists():
        content = LAST_TWEET_ID_FILE.read_text().strip()
        return content if content else None
    return None


def save_last_id(tweet_id: str) -> None:
    LAST_TWEET_ID_FILE.write_text(tweet_id)


def main() -> None:
    print(f"Monitoring @{TARGET_USERNAME} for keywords: {KEYWORDS}")

    user_id = get_user_id(TARGET_USERNAME)
    last_id = load_last_id()
    print(f"Last seen tweet ID: {last_id or '(none)'}")

    tweets = fetch_recent_tweets(user_id, last_id)
    if not tweets:
        print("No new tweets found.")
        return

    # API returns newest first — save the newest ID before filtering
    newest_id = tweets[0]["id"]

    matched = [t for t in tweets if tweet_matches(t["text"])]
    print(f"Found {len(tweets)} new tweet(s), {len(matched)} match(es).")

    for tweet in matched:
        print(f"Match: {tweet['text'][:80]}...")
        send_email(tweet, TARGET_USERNAME)

    save_last_id(newest_id)


if __name__ == "__main__":
    main()
