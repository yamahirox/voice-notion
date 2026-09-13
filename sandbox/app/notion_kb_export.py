"""
Notion データベースをテキストソースとして列挙する（NotebookLM 風 RAG 用）。
スキーマに依存せず、各ページのプロパティを可読テキスト化し、本文ブロックを再帰収集する。
"""
from __future__ import annotations

from typing import Any, Iterable

from notion_client import Client


def _rich_to_str(rich: list[dict] | None) -> str:
    if not rich:
        return ""
    parts: list[str] = []
    for x in rich:
        if isinstance(x, dict):
            parts.append(x.get("plain_text") or "")
    return "".join(parts).strip()


def _prop_lines(name: str, prop: dict) -> list[str]:
    if not isinstance(prop, dict):
        return []
    pt = prop.get("type")
    if not pt:
        return []
    payload = prop.get(pt)
    lines: list[str] = []

    if pt == "title":
        s = _rich_to_str(payload if isinstance(payload, list) else None)
        if s:
            lines.append(f"{name}: {s}")
    elif pt == "rich_text":
        s = _rich_to_str(payload if isinstance(payload, list) else None)
        if s:
            lines.append(f"{name}: {s}")
    elif pt == "number" and payload is not None:
        lines.append(f"{name}: {payload}")
    elif pt == "select" and isinstance(payload, dict):
        n = payload.get("name")
        if n:
            lines.append(f"{name}: {n}")
    elif pt == "multi_select" and isinstance(payload, list):
        names = [x.get("name") for x in payload if isinstance(x, dict) and x.get("name")]
        if names:
            lines.append(f"{name}: {', '.join(names)}")
    elif pt == "status" and isinstance(payload, dict):
        n = payload.get("name")
        if n:
            lines.append(f"{name}: {n}")
    elif pt == "date" and isinstance(payload, dict):
        start = payload.get("start") or ""
        end = payload.get("end") or ""
        if start and end:
            lines.append(f"{name}: {start} — {end}")
        elif start:
            lines.append(f"{name}: {start}")
    elif pt == "checkbox" and isinstance(payload, bool):
        lines.append(f"{name}: {'はい' if payload else 'いいえ'}")
    elif pt == "url" and isinstance(payload, str) and payload.strip():
        lines.append(f"{name}: {payload.strip()}")
    elif pt == "email" and isinstance(payload, str) and payload.strip():
        lines.append(f"{name}: {payload.strip()}")
    elif pt == "phone_number" and isinstance(payload, str) and payload.strip():
        lines.append(f"{name}: {payload.strip()}")
    elif pt == "created_time" and isinstance(payload, str) and payload.strip():
        lines.append(f"{name}: {payload.strip()}")
    elif pt == "last_edited_time" and isinstance(payload, str) and payload.strip():
        lines.append(f"{name}: {payload.strip()}")
    elif pt == "formula" and isinstance(payload, dict):
        # formula type varies; best-effort string
        ft = payload.get("type")
        fv = payload.get(ft)
        if isinstance(fv, str) and fv.strip():
            lines.append(f"{name}: {fv.strip()}")
        elif isinstance(fv, (int, float, bool)):
            lines.append(f"{name}: {fv}")
        elif isinstance(fv, list):
            s = _rich_to_str(fv)
            if s:
                lines.append(f"{name}: {s}")
    elif pt == "rollup" and isinstance(payload, dict):
        rt = payload.get("type")
        rv = payload.get(rt)
        if isinstance(rv, list):
            s = _rich_to_str(rv)
            if s:
                lines.append(f"{name}: {s}")
        elif isinstance(rv, (int, float, str, bool)):
            lines.append(f"{name}: {rv}")
    elif pt == "relation" and isinstance(payload, list) and payload:
        lines.append(f"{name}: （関連 {len(payload)} 件）")
    elif pt == "people" and isinstance(payload, list) and payload:
        names = []
        for p in payload:
            if isinstance(p, dict) and p.get("name"):
                names.append(str(p["name"]))
        if names:
            lines.append(f"{name}: {', '.join(names)}")
    elif pt == "files" and isinstance(payload, list) and payload:
        lines.append(f"{name}: （ファイル {len(payload)} 件）")
    return lines


def properties_to_text(properties: dict[str, Any] | None) -> str:
    if not properties:
        return ""
    chunks: list[str] = []
    for name in sorted(properties.keys()):
        prop = properties.get(name)
        if not isinstance(prop, dict):
            continue
        chunks.extend(_prop_lines(name, prop))
    return "\n".join(chunks).strip()


def _block_plain(block: dict) -> str:
    if not isinstance(block, dict):
        return ""
    t = block.get("type")
    if not t:
        return ""
    payload = block.get(t)
    if not isinstance(payload, dict):
        return ""
    rt = payload.get("rich_text")
    if isinstance(rt, list):
        return _rich_to_str(rt)
    return ""


def _iter_block_lines(block: dict, depth: int = 0) -> Iterable[str]:
    if not isinstance(block, dict):
        return
    prefix = "  " * depth
    t = block.get("type") or ""
    text = _block_plain(block)
    if t in ("paragraph", "quote", "callout"):
        if text:
            yield f"{prefix}{text}"
    elif t in ("heading_1", "heading_2", "heading_3"):
        if text:
            yield f"{prefix}# {text}"
    elif t in ("bulleted_list_item", "numbered_list_item", "to_do"):
        mark = "• " if t == "bulleted_list_item" else "- "
        if text:
            yield f"{prefix}{mark}{text}"
    elif t == "code":
        cb = block.get("code") if isinstance(block.get("code"), dict) else {}
        code_text = _rich_to_str(cb.get("rich_text") if isinstance(cb.get("rich_text"), list) else None)
        if code_text:
            lang = (cb.get("language") or "").strip()
            if lang:
                yield f"{prefix}```{lang}\n{code_text}\n```"
            else:
                yield f"{prefix}```\n{code_text}\n```"
    elif t == "divider":
        yield f"{prefix}---"
    elif text:
        yield f"{prefix}{text}"


def collect_block_text(notion: Client, block_id: str, *, depth: int = 0, max_depth: int = 12) -> str:
    """
    ページまたはブロック配下の本文をフラットなテキストにする。
    """
    lines: list[str] = []
    cursor: str | None = None
    while True:
        kwargs: dict[str, Any] = {"block_id": block_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = notion.blocks.children.list(**kwargs)
        for block in resp.get("results") or []:
            if not isinstance(block, dict):
                continue
            lines.extend(list(_iter_block_lines(block, depth=depth)))
            if block.get("has_children") and depth < max_depth:
                bid = block.get("id")
                if isinstance(bid, str) and bid:
                    nested = collect_block_text(notion, bid, depth=depth + 1, max_depth=max_depth)
                    if nested.strip():
                        lines.append(nested.rstrip())
        cursor = resp.get("next_cursor")
        if not resp.get("has_more") or not cursor:
            break
    return "\n".join(lines).strip()


def iter_database_page_metas(notion: Client, database_id: str, *, page_size: int = 100) -> Iterable[dict]:
    """
    データベース内の全ページ（行）のメタを列挙する。
    Notion API 2025-09 以降は data_sources.query を使う（notion-client 2.6+ は databases.query 非対応）。
    """
    db = notion.databases.retrieve(database_id=database_id)
    if not isinstance(db, dict):
        raise RuntimeError("Notion データベースを取得できませんでした。ID とインテグレーションの接続を確認してください。")

    ds_id = ""
    data_sources = db.get("data_sources") or []
    if isinstance(data_sources, list) and data_sources:
        ds0 = data_sources[0]
        if isinstance(ds0, dict) and ds0.get("id"):
            ds_id = str(ds0["id"])

    cursor: str | None = None
    while True:
        q: dict[str, Any] = {"page_size": page_size}
        if cursor:
            q["start_cursor"] = cursor
        if ds_id:
            resp = notion.data_sources.query(data_source_id=ds_id, **q)
        elif hasattr(notion.databases, "query"):
            resp = notion.databases.query(database_id=database_id, **q)
        else:
            raise RuntimeError(
                "この Notion / SDK では databases.query が使えず、データベースに data_sources も見つかりませんでした。"
                "DB をフルページで開いたときの URL から ID を確認してください。"
            )
        for row in resp.get("results") or []:
            if isinstance(row, dict) and row.get("object") == "page":
                yield row
        cursor = resp.get("next_cursor")
        if not resp.get("has_more") or not cursor:
            break


def export_database_documents(
    notion: Client,
    database_id: str,
    *,
    max_pages: int = 400,
) -> list[dict]:
    """
    返り値: [{ "page_id", "url", "title", "text" }, ...]
    text = プロパティ要約 + 本文ブロック
    """
    docs: list[dict] = []
    count = 0
    for page in iter_database_page_metas(notion, database_id):
        if count >= max_pages:
            break
        page_id = page.get("id") or ""
        url = page.get("url") or ""
        props = page.get("properties") if isinstance(page.get("properties"), dict) else {}
        header = properties_to_text(props)
        # タイトル推定（title 型の先頭）
        title = ""
        for _k, pv in (props or {}).items():
            if isinstance(pv, dict) and pv.get("type") == "title":
                title = _rich_to_str(pv.get("title") if isinstance(pv.get("title"), list) else None)
                break
        if not title:
            title = (page_id or "untitled")[:8]

        body = ""
        if page_id:
            try:
                body = collect_block_text(notion, page_id)
            except Exception:
                body = ""

        parts = []
        if header:
            parts.append(header)
        if body:
            parts.append(body)
        full = "\n\n".join(parts).strip()
        if not full:
            full = title

        docs.append({"page_id": page_id, "url": url, "title": title.strip() or "（無題）", "text": full})
        count += 1
    return docs


def chunk_text(text: str, *, max_chars: int = 1400, overlap: int = 180) -> list[str]:
    """
    長文を埋め込み用に分割する（簡易文字数ベース）。
    """
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= max_chars:
        return [t]
    out: list[str] = []
    start = 0
    n = len(t)
    while start < n:
        end = min(start + max_chars, n)
        chunk = t[start:end].strip()
        if chunk:
            out.append(chunk)
        if end >= n:
            break
        start = max(0, end - overlap)
    return out
