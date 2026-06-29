#!/usr/bin/env python3
"""
Twitter/X monitor via API v2.
Fetches recent tweets from the target account and sends a Gmail alert
when a new tweet matches any of the configured keywords.

Required environment variables:
  TARGET_USERNAME       - Twitter/X username to monitor (without @)
  KEYWORDS              - Comma-separated keywords to watch for
  TWITTER_BEARER_TOKEN  - Twitter API v2 Bearer Token
  GMAIL_ADDRESS         - Gmail address used to send (App Password required)
  GMAIL_APP_PASSWORD    - Gmail App Password (16 chars, no spaces)
  TO_EMAIL              - Recipient address (optional, defaults to GMAIL_ADDRESS)
  SEEN_IDS_FILE         - Path to JSON file storing last seen tweet ID
  MONITOR_LOG_FILE      - Path to JSON file for run history log
"""

import os
import json
import smtplib
import requests
from datetime import datetime, timezone
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

TARGET_USERNAME   = os.environ["TARGET_USERNAME"]
KEYWORDS          = [k.strip().lower() for k in os.environ["KEYWORDS"].split(",") if k.strip()]
BEARER_TOKEN      = os.environ["TWITTER_BEARER_TOKEN"]
GMAIL_ADDRESS     = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
TO_EMAIL          = os.environ.get("TO_EMAIL") or GMAIL_ADDRESS

_DEFAULT_STATE    = Path(".seen_tweet_ids.json")
_DEFAULT_LOG      = Path.home() / "apps" / "daikei_check" / "monitor_log.json"
STATE_FILE        = Path(os.environ.get("SEEN_IDS_FILE", str(_DEFAULT_STATE)))
MONITOR_LOG_FILE  = Path(os.environ.get("MONITOR_LOG_FILE", str(_DEFAULT_LOG)))

API_BASE = "https://api.twitter.com/2"
HEADERS  = {"Authorization": f"Bearer {BEARER_TOKEN}"}


def api_get(path: str, **params) -> dict:
    resp = requests.get(f"{API_BASE}{path}", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_user_id(username: str) -> str:
    data = api_get(f"/users/by/username/{username}")
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]["id"]


def get_tweets(user_id: str, since_id: str | None) -> list[dict]:
    params = {"max_results": 10, "tweet.fields": "created_at"}
    if since_id:
        params["since_id"] = since_id
    data = api_get(f"/users/{user_id}/tweets", **params)
    return data.get("data", [])


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            v = json.loads(STATE_FILE.read_text())
            if isinstance(v, dict):
                return v
        except Exception:
            pass
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def send_email(subject: str, body: str) -> None:
    msg = MIMEMultipart()
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = TO_EMAIL
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, TO_EMAIL, msg.as_string())
    print(f"Email sent: {subject}")


def write_log(status: str, checked: int, matched: int, message: str,
              matches: list[dict] | None = None) -> None:
    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status":    status,
        "checked":   checked,
        "matched":   matched,
        "message":   message,
    }
    if matches:
        entry["matches"] = matches
    try:
        logs = json.loads(MONITOR_LOG_FILE.read_text()) if MONITOR_LOG_FILE.exists() else []
        logs.insert(0, entry)
        MONITOR_LOG_FILE.write_text(json.dumps(logs[:30], ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"Log write error: {e}")


def main() -> None:
    print(f"Monitoring @{TARGET_USERNAME} for: {KEYWORDS}")
    state    = load_state()
    since_id = state.get("since_id")

    try:
        user_id = get_user_id(TARGET_USERNAME)
        print(f"User ID: {user_id}")
    except Exception as e:
        print(f"Failed to get user ID: {e}")
        write_log("error", 0, 0, f"ユーザーID取得に失敗: {e}")
        return

    try:
        tweets = get_tweets(user_id, since_id)
        print(f"Found {len(tweets)} new tweet(s)")
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        msg  = f"API エラー {code}"
        if code == 429:
            msg = "APIレート制限 (429)"
        print(f"API error: {e}")
        write_log("error", 0, 0, msg)
        return
    except Exception as e:
        print(f"Failed to fetch tweets: {e}")
        write_log("error", 0, 0, f"ツイート取得に失敗: {e}")
        return

    if not tweets:
        print("No new tweets since last check.")
        write_log("ok", 0, 0, "前回チェック以降、新しいツイートなし")
        return

    newest_id    = tweets[0]["id"]
    matched      = 0
    match_details: list[dict] = []

    for tweet in tweets:
        text = tweet["text"]
        url  = f"https://x.com/{TARGET_USERNAME}/status/{tweet['id']}"
        if any(kw in text.lower() for kw in KEYWORDS):
            print(f"Match: {text[:80]}")
            send_email(
                subject=f"[X Monitor] @{TARGET_USERNAME} が「{'・'.join(KEYWORDS)}」を含む投稿をしました",
                body=(
                    f"@{TARGET_USERNAME} がキーワードを含む投稿を検知しました。\n\n"
                    f"--- 投稿内容 ---\n{text}\n\n"
                    f"--- リンク ---\n{url}\n"
                ),
            )
            match_details.append({"text": text[:200], "url": url})
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
        write_log("ok", len(tweets), 0, f"{len(tweets)}件チェック。キーワード一致なし。")
    else:
        write_log(
            "match", len(tweets), matched,
            f"{len(tweets)}件チェック。{matched}件のキーワード一致を検知。",
            match_details,
        )

    print(f"Checked {len(tweets)} tweet(s), sent {matched} alert(s).")
    state["since_id"] = newest_id
    save_state(state)


if __name__ == "__main__":
    main()
