# daikei_check

> Twitter/X の特定アカウント（@daikei_org）を毎日監視し、指定キーワードを含むツイートをメールで通知する自動監視ツールです。

## 概要

Playwright によるヘッドレスブラウザで Twitter/X のタイムラインを巡回し、未確認のツイートの中からキーワードに一致するものが見つかったときだけ Gmail でアラートを送信します。
GitHub Actions のセルフホストランナーで毎日 20:00 JST に自動実行されます。

## 機能

- **毎日 20:00 JST の自動実行**: GitHub Actions スケジュール（`0 11 * * *` UTC）で実行
- **差分通知**: 既読ツイート ID を `.seen_tweet_ids.json` に保存し、新着のみを対象にする
- **キーワードフィルタリング**: 環境変数で複数のキーワードをカンマ区切りで指定可能
- **Gmail 通知**: マッチしたツイートの内容とリンクをメールで送信
- **ヘッドレスブラウザ**: Playwright で JavaScript レンダリングを伴う Twitter/X ページに対応
- **手動実行対応**: `workflow_dispatch` で GitHub UI からいつでも即時実行可能

## ディレクトリ構成

```
daikei_check/
├── .github/workflows/monitor.yml  # GitHub Actions ワークフロー
├── scripts/
│   ├── monitor.py     # メイン監視スクリプト
│   ├── setup.sh       # セットアップスクリプト
│   └── configure.sh   # 環境設定スクリプト
└── requirements.txt
```

## セットアップ

### 1. リポジトリをクローン

```bash
git clone https://github.com/woodstockv999/daikei_check.git
cd daikei_check
```

### 2. セルフホストランナーを登録

GitHub リポジトリの `Settings > Actions > Runners` からランナーを追加してください。

### 3. GitHub Secrets を設定

| シークレット名 | 説明 |
|--------------|------|
| `KEYWORDS` | 監視するキーワード（カンマ区切り例: `予算,補助金,支援`） |
| `GMAIL_ADDRESS` | 送信元・受信先の Gmail アドレス |
| `GMAIL_APP_PASSWORD` | Gmail アプリパスワード（16 桁、スペースなし） |
| `X_USERNAME` | Twitter/X のログイン用ユーザー名 or メール |
| `X_PASSWORD` | Twitter/X のパスワード |

### 4. 依存パッケージのインストール

```bash
pip install -r requirements.txt
playwright install chromium
```

## ローカルでのテスト実行

```bash
export TARGET_USERNAME=daikei_org
export KEYWORDS="予算,補助金"
export GMAIL_ADDRESS=your@gmail.com
export GMAIL_APP_PASSWORD=xxxxxxxxxxxx
export X_USERNAME=your_twitter_user
export X_PASSWORD=your_twitter_pass
export SEEN_IDS_FILE=.seen_tweet_ids.json

python scripts/monitor.py
```

## 注意事項

- Twitter/X の利用規約を遵守した上でご使用ください。
- ログイン情報は GitHub Secrets で安全に管理してください。
- アカウントのセキュリティ設定によってはログインに失敗する場合があります。

## ライセンス

MIT
