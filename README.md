# 音声入力 → Notion（スマホ向け Web アプリ）

スマホで話した内容を日本語で文字にし、確認・修正したあと Notion の **DB6本タスク管理** へ新規タスクとして登録するアプリです。

```
スマホのブラウザ（https の公開 URL）
  → インターネット上のこのアプリ（24時間稼働）
    → Notion API
```

パソコンの電源は入りません。家にいなくても、スマホのブックマーク（またはホーム画面）から使えます。

## 0. スマホだけで使う（外出先向け・おすすめ）

家のパソコンを起動しておく必要はありません。アプリを **Render** に置き、発行された `https://…` をスマホで開きます。

### 準備（最初の1回だけ）

1. このフォルダの中身は GitHub リポジトリ `yamahirox/voice-notion` に置いてあります。`.env` は上げないでください。
2. [Render](https://render.com/) でアカウントを作り、その GitHub リポジトリを選びます。
3. 作り方は **Docker**（このフォルダの `Dockerfile`）にします。
4. サービスの **Environment Variables** に次を入れます。

| 名前 | 内容 |
| --- | --- |
| `NOTION_API_KEY` | Notion インテグレーションの API キー |
| `NOTION_DB_6PON_ID` | 「DB6本タスク管理」の Database ID |
| `VOICE_SHARED_SECRET` | 自分だけが知る長いパスワード（推奨） |

5. 公開が終わると `https://…….onrender.com` のような URL が出ます。
6. スマホの Chrome でその URL を開き、画面の「接続用パスワード」に同じ値を保存します。
7. 「🎤 音声入力開始」を押し、マイクを許可します。公開 URL は https なので、スマホの音声認識が使えます。
8. Chrome のメニュー → **ホーム画面に追加** すると、次からアプリのように開けます。

無料枠では、しばらく使わないと眠ることがあります。そのときは画面を開いて数十秒待つと起きます。

### 今開いている Render「New Web Service」画面の記入

| 項目 | 入れる値 |
| --- | --- |
| Source Code | GitHub の `yamahirox/voice-notion` |
| Name | `voice-notion` |
| Language | `Docker`（Python ではない） |
| Branch | `main` |
| Region | `Singapore`（なければそのまま） |
| Root Directory | 空のまま |
| Instance Type | `Free`（$0、カード登録なし） |
| Dockerfile Path | `./Dockerfile`（出ていればそのままでよい） |

Environment Variables に、上の3つを入れてから一番下の **Deploy Web Service** を押します。

---

以下は、今までどおり **自分の Windows PC で動かす** 場合の手順です。PC を使うときだけ読んでください。

## 1. 必要ライブラリのインストール

1. このフォルダ（`project音声入力Notion転記`）を開きます。
2. **コマンドプロンプト** または **PowerShell** を開き、次を実行します。

```bat
cd /d このフォルダのパス
python -m pip install -r requirements.txt
```

仮想環境を使う場合の例：

```bat
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
```

## 2. 環境変数の確認方法

Notion の秘密情報はソースコードに書きません。Windows のユーザー環境変数、またはこのフォルダの `.env`（Git には入れない）を使います。

必要な変数：

| 名前 | 内容 |
| --- | --- |
| `NOTION_API_KEY` | Notion インテグレーションの API キー |
| `NOTION_DB_6PON_ID` | 「DB6本タスク管理」の Database ID |

PowerShell で「名前だけ」確認する例（値は画面に出さない）：

```powershell
[bool][Environment]::GetEnvironmentVariable("NOTION_API_KEY", "User")
[bool][Environment]::GetEnvironmentVariable("NOTION_DB_6PON_ID", "User")
```

どちらも `True` になれば設定されています。

`.env` を使う場合は `.env.example` をコピーして `.env` を作り、同じ名前の項目を記入してください。`.gitignore` に `.env` があるため、Git には登録されません。

対象データベースに、使っている Notion インテグレーションを **接続（共有）** しておいてください。接続されていないと登録時に 404 になり、画面には「❌ Notionへの登録に失敗しました」と出ます。サーバー側のログに Notion の HTTP ステータスとエラー本文が出ます（APIキーは出ません）。

## 3. アプリの起動方法

**かんたん：** `アプリ起動.bat` をダブルクリックします。

手動の場合：

```bat
cd /d このフォルダのパス
python app.py
```

起動すると、この PC のポート **5000** で待ち受けます（`host=0.0.0.0`）。

## 4. PC からアクセスする方法

同じ PC のブラウザで次を開きます。

http://127.0.0.1:5000

または

http://localhost:5000

## 5. PC のローカル IP アドレスの確認方法

1. コマンドプロンプトを開く
2. `ipconfig` と入力して Enter
3. **ワイヤレス LAN アダプター Wi-Fi** または **イーサネット** の **IPv4 アドレス** を見る

例：`192.168.11.23`

## 6. スマホからアクセスする方法

1. スマホと PC を **同じ Wi-Fi** につなぐ
2. スマホのブラウザ（Chrome 推奨）で次を開く

http://（手順5で調べたIPv4）:5000

例：`http://192.168.11.23:5000`

「🎤 音声入力開始」を押し、必要ならマイク許可をします。認識文は下のテキストエリアで直せます。「Notionに登録」で DB に追加されます。

音声認識はブラウザの Web Speech API（`ja-JP`）を使います。使えないブラウザでは手入力だけできます。

**注意（Android / iPhone）：** マイク付きの音声認識は、`http://192.168.x.x` のような HTTP ではブラウザが拒否することがあります。その場合は文字を直接入力して登録できます。PC の `http://127.0.0.1:5000` では音声認識が使えることが多いです。Chrome で LAN の HTTP を試す場合は、`chrome://flags/#unsafely-treat-insecure-origin-as-secure` にこのアプリの URL を追加する方法があります（自己責任）。

## 7. Windows ファイアウォールで接続できない場合

スマホからページが開かないときは、PC 側でポート 5000 の受信を許可します。

**管理者の PowerShell** で例：

```powershell
New-NetFirewallRule -DisplayName "Flask Voice Notion 5000" -Direction Inbound -Protocol TCP -LocalPort 5000 -Action Allow
```

または「Windows セキュリティ」→「ファイアウォールとネットワーク保護」→「詳細設定」→「受信の規則」→「新しい規則」で、TCP ポート **5000** を許可します。

そのほか確認：

- PC とスマホが同じ Wi-Fi か
- VPN を切っているか
- アドレスが `http://` で、ポートが `:5000` か
- アプリ起動中か（黒い窓を閉じると止まります）
- 外出先から使うなら、上の「0. スマホだけで使う」で出した Render の URL を開く

---

以下は、同じフォルダ内にある以前の Keep → Gmail → Notion 自動化の説明です。今回の Flask アプリとは別系統です。

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
