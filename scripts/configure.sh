#!/bin/bash
# Daikei Monitor 設定変更スクリプト
# setup.sh を再実行せずに .env の認証情報だけを更新します
set -e

INSTALL_DIR="$HOME/daikei_check"
ENV_FILE="$INSTALL_DIR/.env"

echo "========================================"
echo "  Daikei Monitor 設定変更"
echo "========================================"
echo ""

if [ ! -d "$INSTALL_DIR" ]; then
    echo "エラー: $INSTALL_DIR が見つかりません。先に setup.sh を実行してください。"
    exit 1
fi

# --- 既存値を読み込む ---
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
    echo "現在の設定を読み込みました。Enterで既存の値をそのまま使います。"
else
    echo "警告: $ENV_FILE が見つかりません。新規作成します。"
fi

# --- バックアップ ---
if [ -f "$ENV_FILE" ]; then
    BACKUP_FILE="$ENV_FILE.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$ENV_FILE" "$BACKUP_FILE"
    chmod 600 "$BACKUP_FILE"
    echo "バックアップ: $BACKUP_FILE"
fi

echo ""
echo "----------------------------------------"

read -p "Gmailアドレス${GMAIL_ADDRESS:+ [$GMAIL_ADDRESS]}: " NEW_GMAIL_ADDRESS
NEW_GMAIL_ADDRESS="${NEW_GMAIL_ADDRESS:-$GMAIL_ADDRESS}"

read -s -p "Gmailアプリパスワード (16文字)${GMAIL_APP_PASSWORD:+ [****]}: " NEW_GMAIL_APP_PASSWORD
echo ""
NEW_GMAIL_APP_PASSWORD="${NEW_GMAIL_APP_PASSWORD:-$GMAIL_APP_PASSWORD}"

read -p "通知先メールアドレス (Enterでスキップ→Gmailと同じ)${TO_EMAIL:+ [$TO_EMAIL]}: " NEW_TO_EMAIL
NEW_TO_EMAIL="${NEW_TO_EMAIL:-$TO_EMAIL}"

echo ""
echo "XのアカウントはX.comへのログインに使います。"
read -p "XのユーザーID または メールアドレス${X_USERNAME:+ [$X_USERNAME]}: " NEW_X_USERNAME
NEW_X_USERNAME="${NEW_X_USERNAME:-$X_USERNAME}"

read -s -p "Xのパスワード${X_PASSWORD:+ [****]}: " NEW_X_PASSWORD
echo ""
NEW_X_PASSWORD="${NEW_X_PASSWORD:-$X_PASSWORD}"

# TARGET_USERNAME / KEYWORDS / SEEN_IDS_FILE は変更しない（既存値を保持）
NEW_TARGET_USERNAME="${TARGET_USERNAME:-daikei_org}"
NEW_KEYWORDS="${KEYWORDS:-予約}"
NEW_SEEN_IDS_FILE="${SEEN_IDS_FILE:-$INSTALL_DIR/.seen_tweet_ids.json}"

# --- .env 書き込み ---
cat > "$ENV_FILE" << ENV
TARGET_USERNAME=${NEW_TARGET_USERNAME}
KEYWORDS=${NEW_KEYWORDS}
GMAIL_ADDRESS=${NEW_GMAIL_ADDRESS}
GMAIL_APP_PASSWORD=${NEW_GMAIL_APP_PASSWORD}
TO_EMAIL=${NEW_TO_EMAIL}
X_USERNAME=${NEW_X_USERNAME}
X_PASSWORD=${NEW_X_PASSWORD}
SEEN_IDS_FILE=${NEW_SEEN_IDS_FILE}
ENV

chmod 600 "$ENV_FILE"

echo ""
echo "========================================"
echo "  設定を保存しました: $ENV_FILE"
echo "========================================"
echo ""
echo "動作確認:"
echo "  bash $INSTALL_DIR/run.sh"
echo ""
echo "バックアップから戻す場合:"
if [ -n "${BACKUP_FILE:-}" ]; then
    echo "  cp ${BACKUP_FILE} ${ENV_FILE}"
fi
echo ""
