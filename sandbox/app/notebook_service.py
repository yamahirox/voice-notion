"""
Notion KB データベースをソースとした質問応答（埋め込み検索 + OpenAI チャット）。
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from notion_client import Client

from sandbox.app.main import _require_env
from sandbox.app.notion_kb_export import chunk_text, export_database_documents


@dataclass
class _KBIndex:
    built_at: float
    database_id: str
    chunks: list[str]
    metas: list[dict]  # per chunk: page_id, url, title, chunk_index
    embeddings: list[list[float]]


_cache: _KBIndex | None = None
_cache_key: str = ""


def _openai_base() -> str:
    return os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def _openai_key() -> str:
    return _require_env("OPENAI_API_KEY")


def _chat_model() -> str:
    return os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"


def _embed_model() -> str:
    return os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small").strip() or "text-embedding-3-small"


def _kb_database_id() -> str:
    return _require_env("NOTION_KB_DATABASE_ID")


def _max_pages() -> int:
    raw = os.environ.get("NOTION_KB_MAX_PAGES", "400").strip()
    try:
        n = int(raw)
    except ValueError:
        return 400
    return max(1, min(n, 2000))


def _cache_ttl_sec() -> float:
    raw = os.environ.get("NOTION_KB_CACHE_SEC", "300").strip()
    try:
        n = int(raw)
    except ValueError:
        return 300
    return float(max(0, n))


def _top_k() -> int:
    raw = os.environ.get("NOTION_KB_TOP_K", "8").strip()
    try:
        n = int(raw)
    except ValueError:
        return 8
    return max(1, min(n, 24))


def _embed_http(client: httpx.Client, texts: list[str]) -> list[list[float]]:
    key = _openai_key()
    url = f"{_openai_base()}/embeddings"
    out_vectors: list[list[float]] = []
    batch = 64
    for i in range(0, len(texts), batch):
        part = texts[i : i + batch]
        r = client.post(
            url,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": _embed_model(), "input": part},
            timeout=120.0,
        )
        r.raise_for_status()
        data = r.json()
        arr = data.get("data") or []
        indexed: list[tuple[int, list[float]]] = []
        for item in arr:
            if not isinstance(item, dict):
                continue
            idx = int(item.get("index", 0))
            emb = item.get("embedding")
            if isinstance(emb, list):
                indexed.append((idx, [float(x) for x in emb]))
        indexed.sort(key=lambda x: x[0])
        for _, vec in indexed:
            out_vectors.append(vec)
    if len(out_vectors) != len(texts):
        raise RuntimeError(f"埋め込み件数が一致しません: expected={len(texts)} got={len(out_vectors)}")
    return out_vectors


def _chat_http(client: httpx.Client, messages: list[dict[str, str]], *, max_tokens: int = 1200) -> str:
    key = _openai_key()
    url = f"{_openai_base()}/chat/completions"
    r = client.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": _chat_model(),
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": max_tokens,
        },
        timeout=120.0,
    )
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI から空の応答でした。")
    msg = (choices[0] or {}).get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str):
        raise RuntimeError("OpenAI 応答形式が想定外です。")
    return content.strip()


def _cosine(a: list[float], b: list[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def build_index(*, force: bool = False) -> _KBIndex:
    global _cache, _cache_key
    db_id = _kb_database_id()
    key = f"{db_id}:{_max_pages()}:{_embed_model()}"
    ttl = _cache_ttl_sec()
    now = time.time()
    if (
        not force
        and _cache is not None
        and _cache_key == key
        and (ttl <= 0 or now - _cache.built_at < ttl)
    ):
        return _cache

    notion_key = _require_env("NOTION_API_KEY")
    notion = Client(auth=notion_key)
    docs = export_database_documents(notion, db_id, max_pages=_max_pages())

    chunks: list[str] = []
    metas: list[dict] = []
    for d in docs:
        page_id = d.get("page_id") or ""
        url = d.get("url") or ""
        title = d.get("title") or ""
        text = d.get("text") or ""
        head = f"【{title}】\n" if title else ""
        pieces = chunk_text(head + text, max_chars=1400, overlap=180)
        if not pieces:
            continue
        for i, ch in enumerate(pieces):
            chunks.append(ch)
            metas.append({"page_id": page_id, "url": url, "title": title, "chunk_index": i})

    embeddings: list[list[float]] = []
    if chunks:
        with httpx.Client() as http:
            embeddings = _embed_http(http, chunks)

    idx = _KBIndex(
        built_at=now,
        database_id=db_id,
        chunks=chunks,
        metas=metas,
        embeddings=embeddings,
    )
    _cache = idx
    _cache_key = key
    return idx


def ask_notebook(question: str, *, refresh: bool = False) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        raise ValueError("質問が空です。")

    index = build_index(force=refresh)
    if not index.chunks or not index.embeddings:
        raise RuntimeError(
            "ナレッジベースにチャンクがありません。Notion DB に行があるか、インテグレーション共有を確認してください。"
        )

    k = _top_k()
    with httpx.Client() as http:
        q_vec = _embed_http(http, [q])[0]
        scored: list[tuple[float, int]] = []
        for i, emb in enumerate(index.embeddings):
            scored.append((_cosine(q_vec, emb), i))
        scored.sort(key=lambda x: x[0], reverse=True)
        top_idx = [i for _sim, i in scored[:k]]

        context_parts: list[str] = []
        sources: list[dict] = []
        seen_pages: set[str] = set()
        for rank, i in enumerate(top_idx, start=1):
            ch = index.chunks[i]
            meta = index.metas[i] if i < len(index.metas) else {}
            title = meta.get("title") or ""
            url = meta.get("url") or ""
            context_parts.append(f"--- 抜粋{rank}（{title}） ---\n{ch}")
            pid = str(meta.get("page_id") or "")
            if pid and pid not in seen_pages:
                seen_pages.add(pid)
                sources.append({"title": title, "url": url, "page_id": pid})

        context = "\n\n".join(context_parts)

        system = (
            "あなたは与えられた「抜粋」だけを根拠に回答するアシスタントです。"
            "抜粋に無い内容は推測せず、「ソースに記載がありません」と説明してください。"
            "回答は日本語で簡潔に。重要な事実には可能なら括弧で抜粋番号（例: 抜粋1）を付けてください。"
        )
        user = f"【質問】\n{q}\n\n【ソース抜粋】\n{context}"
        answer = _chat_http(
            http,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=1400,
        )

    return {
        "answer": answer,
        "sources": sources,
        "chunks_used": len(top_idx),
        "index_built_at": index.built_at,
        "cached_until_sec": _cache_ttl_sec(),
    }
