# 📌 ProjectA - Keep → Gmail → Notion 自動化システム

## 🧠 概要

Pixel Watch 4 で音声入力したアイデアを
Google Keep → Gmail → ローカル処理 → Notion に自動登録するシステム。

* 音声入力 → Keep保存
* KeepメモをGmailへ共有
* cronで定期取得
* 日付解析してNotionに登録

---

## 🔄 データフロー

```
Pixel Watch 4
↓
Google Keep
↓（共有）
Gmail
↓（cron）
ローカルスクリプト
↓
Notion API
```

---

## 🎯 機能

* Gmailから特定メールを取得
* テキストから日付を解析（例：明日・来週）
* タスク / アイデアを自動分類
* Notionデータベースへ登録
* 重複防止（ID管理）

---

## 📁 ディレクトリ構成

```
projectA/
├─ README.md
├─ src/              # 設計・共通コード
├─ tests/            # テストコード
├─ docs/             # 設計書・プロンプト
│  ├─ agent_prompt.md
│  ├─ security.md
│  └─ notion_schema.md
│
├─ sandbox/          # ★ 実行領域（AI操作対象）
│  ├─ app/           # 実行コード
│  ├─ data/          # 処理履歴（JSON）
│  └─ logs/          # ログ
```

---

## 🔐 セキュリティ方針（重要）

* APIキーは**OS環境変数のみ使用**
* `.env`ファイルは禁止
* Gmailは**読み取り専用**
* 外部通信は以下のみ：

  * Gmail（IMAP）
  * Notion API
* sandbox外のファイルは操作禁止

---

## 🔑 必要な環境変数

```bash
NOTION_API_KEY=xxx
NOTION_DATABASE_ID=xxx
GMAIL_USER=xxx@gmail.com
GMAIL_APP_PASSWORD=xxxx
```

---

## ⚙️ セットアップ

### ① Python環境

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

---

### ② Gmail設定

* IMAPを有効化
* アプリパスワードを発行
* KeepメモをGmailへ共有

---

### ③ Notion設定

* 対象DBにIntegrationを共有
* APIキーを取得

---

## ⏱ cron設定

```bash
crontab -e
```

例（5分ごと実行）：

```bash
*/5 * * * * /usr/bin/python3 /path/to/projectA/sandbox/app/main.py >> /path/to/projectA/sandbox/logs/cron.log 2>&1
```

---

## 🧪 実行方法

手動実行：

```bash
python sandbox/app/main.py
```

---

## 📊 ログ

```
sandbox/logs/
├─ app.log
├─ error.log
├─ processed.log
```

---

## 🛡 安全ルール

* APIキーをログに出さない
* メール本文は必要最低限のみ記録
* 重複処理は禁止
* 不明データはIdeaとして登録

---

## 🚫 禁止事項

* `.env`の使用
* APIキーのハードコード
* Gmailの削除・変更操作
* sandbox外の操作

---

## 🚀 今後の拡張

* 日付解析の精度向上
* GUI化
* Webhook化
* AIによる内容要約

---

## 📎 関連ドキュメント

* docs/agent_prompt.md
* docs/security.md
* docs/notion_schema.md

---

## 🧠 開発方針

* 小さく作って検証
* セキュリティ優先
* 自動化より安定性
* すべて再現可能にする

---

## ✅ ステータス

* [ ] 設計
* [ ] Gmail連携
* [ ] Notion連携
* [ ] cron自動化
* [ ] 運用開始
