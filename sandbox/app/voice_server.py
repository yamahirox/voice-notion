"""
ブラウザの音声認識 → 既存の Notion DB（main.py と同じスキーム）へ登録するローカルAPI。
  - `/` … 1件転記（`/api/tasks`）
  - `/idea-city` … 複数行をタスクに分割（`/api/idea-city/tasks`、行内に日付語があれば期日付き＝生活、なければアイデア）

--- ローカル（自宅PC）---
  python -m pip install -r requirements.txt
  python -m uvicorn sandbox.app.voice_server:app --host 127.0.0.1 --port 8765
  同一 Wi‑Fi のスマホ: --host 0.0.0.0（家庭内LANのみ推奨）

--- 外から常時使う（クラウド）---
  例: Railway / Render / Fly.io などに Docker デプロイ。サービスは24時間稼働。
  環境変数: NOTION_API_KEY, NOTION_DATABASE_ID（必須・音声→タスク登録用）
  Notebook Q&A: NOTION_KB_DATABASE_ID（別DB・ソース用）, OPENAI_API_KEY
  任意: VOICE_SHARED_SECRET（推奨・長いランダム文字列。設定時は画面の「公開URL用」で同じ値を保存）
  ビルドはリポジトリ直下の Dockerfile を使用。
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sandbox.app.notebook_service import ask_notebook, build_index

_APP_DIR = Path(__file__).resolve().parent
_MAIN = _APP_DIR / "main.py"
_spec = importlib.util.spec_from_file_location("notion_voice_main", _MAIN)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"main.py を読み込めません: {_MAIN}")
notion_main = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notion_main)

app = FastAPI(title="Voice → Notion", version="1.0.0")


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


# クロスオリジンが必要なとき（例: フロントだけ別ドメイン）に VOICE_CORS_ALLOW_ALL=1
if _truthy_env("VOICE_CORS_ALLOW_ALL"):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # プライベート IPv4 + localhost（ポート任意）。https の公開URLは同一オリジンなら通常この制限に引っかからない。
    _allow_origin_regex = (
        r"^https?://"
        r"(127\.0\.0\.1|localhost|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2[0-9]|3[0-1])\.\d{1,3}\.\d{1,3})"
        r"(:\d+)?$"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_origin_regex=_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def _verify_voice_secret(request: Request) -> None:
    expected = os.environ.get("VOICE_SHARED_SECRET", "").strip()
    if not expected:
        return
    got = request.headers.get("X-Voice-Secret", "").strip()
    if got != expected:
        raise HTTPException(
            status_code=401,
            detail="接続用パスワードが一致しません。画面の「インターネットの URL で使う」と VOICE_SHARED_SECRET を確認してください。",
        )


class TranscriptIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=8000)
    dry_run: bool = False


class IdeaCityBatchIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=32000)
    dry_run: bool = False


class NotebookAskIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=8000)
    refresh: bool = False


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    path = _APP_DIR / "static" / "voice.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"静的ファイルが見つかりません: {path}")
    return FileResponse(path)


@app.post("/api/tasks")
def create_task(body: TranscriptIn, request: Request) -> dict:
    _verify_voice_secret(request)
    raw = body.text.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="text が空です")

    title, rest = notion_main._split_title_and_body(raw)
    title = (title or "").strip() or "（無題）"
    if len(title) > 200:
        title = title[:200]
    due = notion_main._parse_relative_date_jp(raw)

    try:
        result = notion_main.register_notion_task(
            title=title,
            body=rest,
            due=due,
            source_id="",
            dry_run=body.dry_run,
            verbose=False,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return result


def _idea_city_file_response() -> FileResponse:
    path = _APP_DIR / "static" / "idea_city.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"静的ファイルが見つかりません: {path}")
    return FileResponse(path)


@app.get("/idea-city")
def idea_city_index() -> FileResponse:
    return _idea_city_file_response()


@app.get("/idea-city/")
def idea_city_index_slash() -> RedirectResponse:
    """ブラウザやブックマークで末尾 / が付いても 404 にしない"""
    return RedirectResponse(url="/idea-city", status_code=307)


def _notebook_file_response() -> FileResponse:
    path = _APP_DIR / "static" / "notebook.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"静的ファイルが見つかりません: {path}")
    return FileResponse(path)


@app.get("/notebook")
def notebook_page() -> FileResponse:
    """Notion KB（別DB）をソースにした Q&A（NotebookLM 風）"""
    return _notebook_file_response()


@app.get("/notebook/")
def notebook_page_slash() -> RedirectResponse:
    return RedirectResponse(url="/notebook", status_code=307)


@app.post("/api/notebook/ask")
def api_notebook_ask(body: NotebookAskIn, request: Request) -> dict:
    _verify_voice_secret(request)
    try:
        return ask_notebook(body.question, refresh=body.refresh)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/notebook/refresh")
def api_notebook_refresh(request: Request) -> dict:
    """Notion から KB を再取得し埋め込みを作り直す（キャッシュを無視）"""
    _verify_voice_secret(request)
    try:
        idx = build_index(force=True)
        page_ids = {str(m.get("page_id") or "") for m in idx.metas if m.get("page_id")}
        page_ids.discard("")
        return {"ok": True, "chunks": len(idx.chunks), "pages": len(page_ids), "built_at": idx.built_at}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/idea-city/tasks")
@app.post("/api/idea-city/tasks/")
def create_idea_city_batch(body: IdeaCityBatchIn, request: Request) -> dict:
    """
    改行区切りで複数タスク。各行について _parse_relative_date_jp で期日が取れれば期日＋「生活」、
    なければ「アイデア」（register_notion_task と同じルール）。
    """
    _verify_voice_secret(request)
    tasks = notion_main.parse_idea_city_tasks(body.text)
    if not tasks:
        raise HTTPException(status_code=400, detail="有効な行がありません")

    results: list[dict] = []
    errors: list[dict] = []
    for i, (title, due) in enumerate(tasks):
        try:
            r = notion_main.register_notion_task(
                title=title,
                body="",
                due=due,
                source_id="",
                dry_run=body.dry_run,
                verbose=False,
            )
            row = dict(r)
            row["index"] = i
            row["due"] = str(due) if due else ""
            results.append(row)
        except RuntimeError as e:
            errors.append({"index": i, "title": title, "error": str(e)})
        except Exception as e:
            errors.append({"index": i, "title": title, "error": str(e)})

    return {
        "ok": len(errors) == 0,
        "created": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest_webmanifest() -> FileResponse:
    path = _APP_DIR / "static" / "manifest.webmanifest"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="manifest が見つかりません")
    return FileResponse(path, media_type="application/manifest+json")


app.mount("/static", StaticFiles(directory=str(_APP_DIR / "static")), name="static")
