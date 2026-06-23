#!/bin/bash
# Daikei Monitor VPS セットアップスクリプト
# Ubuntu 24.04 向け（w00dst0ck ユーザーで実行すること。root 不要）
set -e

INSTALL_DIR="$HOME/daikei_check"
LOG_FILE="$HOME/logs/daikei_monitor.log"

echo "========================================"
echo "  Daikei Monitor セットアップ"
echo "========================================"
echo ""

# --- ディレクトリ作成 ---
echo "[1/3] ディレクトリを作成中..."
mkdir -p "$(dirname "$LOG_FILE")"

# --- Python 環境 + Playwright ---
echo "[2/3] Python環境とPlaywrightをインストール中（数分かかります）..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
pip install -q --upgrade pip
pip install -q playwright
python -m playwright install chromium
python -m playwright install-deps chromium
deactivate

# --- 既存 .env のバックアップ ---
if [ -f "$INSTALL_DIR/.env" ]; then
    BACKUP_FILE="$INSTALL_DIR/.env.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$INSTALL_DIR/.env" "$BACKUP_FILE"
    chmod 600 "$BACKUP_FILE"
    echo "既存の設定をバックアップしました: $BACKUP_FILE"
    set -a; source "$INSTALL_DIR/.env"; set +a
    PREV_GMAIL_ADDRESS="$GMAIL_ADDRESS"
    PREV_GMAIL_APP_PASSWORD="$GMAIL_APP_PASSWORD"
    PREV_TO_EMAIL="$TO_EMAIL"
    PREV_X_USERNAME="$X_USERNAME"
    PREV_X_PASSWORD="$X_PASSWORD"
else
    PREV_GMAIL_ADDRESS=""
    PREV_GMAIL_APP_PASSWORD=""
    PREV_TO_EMAIL=""
    PREV_X_USERNAME=""
    PREV_X_PASSWORD=""
fi

# --- 認証情報入力 ---
echo ""
echo "[3/3] 設定情報を入力してください"
echo "  (Enterで既存の値をそのまま使います)"
echo "----------------------------------------"
read -p "Gmailアドレス${PREV_GMAIL_ADDRESS:+ [$PREV_GMAIL_ADDRESS]}: " GMAIL_ADDRESS
GMAIL_ADDRESS="${GMAIL_ADDRESS:-$PREV_GMAIL_ADDRESS}"

read -s -p "Gmailアプリパスワード (16文字)${PREV_GMAIL_APP_PASSWORD:+ [****]}: " GMAIL_APP_PASSWORD
echo ""
GMAIL_APP_PASSWORD="${GMAIL_APP_PASSWORD:-$PREV_GMAIL_APP_PASSWORD}"

read -p "通知先メールアドレス (Enterでスキップ→Gmailと同じ)${PREV_TO_EMAIL:+ [$PREV_TO_EMAIL]}: " TO_EMAIL
TO_EMAIL="${TO_EMAIL:-$PREV_TO_EMAIL}"

echo ""
echo "XのアカウントはX.comへのログインに使います。"
read -p "XのユーザーID または メールアドレス${PREV_X_USERNAME:+ [$PREV_X_USERNAME]}: " X_USERNAME
X_USERNAME="${X_USERNAME:-$PREV_X_USERNAME}"

read -s -p "Xのパスワード${PREV_X_PASSWORD:+ [****]}: " X_PASSWORD
echo ""
X_PASSWORD="${X_PASSWORD:-$PREV_X_PASSWORD}"

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
cat > "$INSTALL_DIR/run.sh" << RUNEOF
#!/bin/bash
set -a
source ${INSTALL_DIR}/.env
set +a
source ${INSTALL_DIR}/venv/bin/activate
python ${INSTALL_DIR}/scripts/monitor.py
RUNEOF

chmod +x "$INSTALL_DIR/run.sh"

# --- cron 設定 (毎日20時JST = 11:00 UTC) ---
(crontab -l 2>/dev/null | grep -v daikei_monitor; echo "0 11 * * * ${INSTALL_DIR}/run.sh >> ${LOG_FILE} 2>&1") | crontab -

echo ""
echo "========================================"
echo "  セットアップ完了！"
echo "========================================"
echo ""
echo "今すぐテスト実行:"
echo "  bash ${INSTALL_DIR}/run.sh"
echo ""
echo "ログ確認:"
echo "  cat ${LOG_FILE}"
echo ""
echo "自動実行: 毎日 午後8時(JST) に実行されます"
echo ""
