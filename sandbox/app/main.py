import os
import sys
import json
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from notion_client import Client


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")
DATA_DIR = PROJECT_ROOT / "sandbox" / "data"
PROCESSED_PATH = DATA_DIR / "processed.json"

# Notion DB: 「DB６本タスク管理」用のプロパティ名
PROP_TASK_NAME = "タスク名"  # title
PROP_DUE = "期日"  # date
PROP_LIFE_IDEA = "生活：アイデア"  # multi_select
PROP_STATUS = "ステータス"  # multi_select

LIFE_VALUE = "生活"
IDEA_VALUE = "アイデア"
STATUS_TODO_VALUE = "未着手"


def _read_windows_user_env_from_registry(name: str) -> str:
    if sys.platform != "win32":
        return ""
    try:
        import winreg  # type: ignore
    except Exception:
        return ""

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
            if isinstance(value, str):
                return value.strip()
    except FileNotFoundError:
        return ""
    except OSError:
        return ""
    return ""


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        value = _read_windows_user_env_from_registry(name)
    if not value:
        raise RuntimeError(
            f"環境変数 {name} が未設定です。"
            f"プロジェクト直下の .env に記載するか、OS の環境変数を設定してください。"
            f"（ひな形: {PROJECT_ROOT / '.env.example'}）"
        )
    return value


def _load_processed_ids() -> set[str]:
    if not PROCESSED_PATH.exists():
        return set()
    try:
        data = json.loads(PROCESSED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, list):
        return set()
    return {str(x) for x in data if x}


def _save_processed_ids(ids: set[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_PATH.write_text(
        json.dumps(sorted(ids), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _find_title_property_name(database: dict) -> str:
    props = database.get("properties", {}) or {}
    if not props:
        data_sources = database.get("data_sources") or []
        if isinstance(data_sources, list) and data_sources:
            ds0 = data_sources[0]
            if isinstance(ds0, dict):
                props = ds0.get("properties", {}) or {}
    for prop_name, prop in props.items():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return prop_name
    debug = []
    for prop_name, prop in props.items():
        if isinstance(prop, dict):
            debug.append(f"{prop_name}={prop.get('type')}")
        else:
            debug.append(f"{prop_name}=<non-dict>")
    debug_str = ", ".join(debug) if debug else "<no properties>"
    raise RuntimeError(
        "このNotion DBに title 型のプロパティが見つかりませんでした。"
        f" properties={debug_str}"
    )


def _extract_best_text_from_email(msg) -> str:
    # stdlib email.message.EmailMessage を想定
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get_content_disposition() or "").lower()
            if disp == "attachment":
                continue
            if ctype == "text/plain":
                try:
                    return (part.get_content() or "").strip()
                except Exception:
                    pass
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            disp = (part.get_content_disposition() or "").lower()
            if disp == "attachment":
                continue
            if ctype == "text/html":
                try:
                    html = (part.get_content() or "").strip()
                    return html
                except Exception:
                    pass
        return ""
    try:
        return (msg.get_content() or "").strip()
    except Exception:
        return ""


def _looks_like_keep_email(subject: str, body_text: str) -> bool:
    s = (subject or "").lower()
    b = (body_text or "").lower()
    needles = [
        "keep",
        "google keep",
        "keep.google.com",
    ]
    return any(n in s for n in needles) or any(n in b for n in needles)


def _looks_like_keep_sender(from_addr: str) -> bool:
    f = (from_addr or "").lower()
    return ("keep" in f) or ("google" in f and "noreply" in f)


def _cleanup_keep_body(text: str) -> str:
    lines = [ln.rstrip() for ln in (text or "").splitlines()]
    cleaned: list[str] = []
    for ln in lines:
        if ln.lstrip().startswith(">"):
            continue
        if ln.strip().startswith("-----Original Message-----"):
            break
        cleaned.append(ln)
    while cleaned and cleaned[-1].strip() == "":
        cleaned.pop()
    return "\n".join(cleaned).strip()


def _split_title_and_body(text: str) -> tuple[str, str]:
    cleaned = _cleanup_keep_body(text)
    lines = [ln.strip() for ln in cleaned.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ("Keep", "")
    title = lines[0]
    body = "\n".join(lines[1:]).strip()
    return (title, body)


def _parse_relative_date_jp(text: str, *, base: date | None = None) -> date | None:
    t = (text or "").strip()
    if not t:
        return None
    base = base or datetime.now().date()

    if "今日" in t:
        return base
    if "明後日" in t or "あさって" in t:
        return base + timedelta(days=2)
    if "明日" in t or "あした" in t:
        return base + timedelta(days=1)
    if "来週" in t:
        days_ahead = (7 - base.weekday()) % 7
        days_ahead = 7 if days_ahead == 0 else days_ahead
        return base + timedelta(days=days_ahead)
    if "来月" in t:
        y, m = base.year, base.month
        if m == 12:
            return date(y + 1, 1, 1)
        return date(y, m + 1, 1)
    return None


def parse_idea_city_tasks(text: str) -> list[tuple[str, date | None]]:
    """
    Idea City 用: 改行で複数タスクに分割。各行について相対日付語があれば期日を付与。
    """
    out: list[tuple[str, date | None]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        due = _parse_relative_date_jp(line)
        title = line if len(line) <= 200 else line[:200]
        out.append((title, due))
    return out


def _find_first_property_name_by_type(schema: dict, prop_type: str) -> str:
    props = schema.get("properties", {}) or {}
    for name, prop in props.items():
        if isinstance(prop, dict) and prop.get("type") == prop_type:
            return name
    return ""


def _get_property(schema: dict, name: str, expected_type: str | tuple[str, ...]) -> dict:
    props = schema.get("properties", {}) or {}
    prop = props.get(name)
    if not isinstance(prop, dict):
        raise RuntimeError(f"Notion DBにプロパティ {name!r} が見つかりません。")
    actual = prop.get("type")
    expected = (expected_type,) if isinstance(expected_type, str) else expected_type
    if actual not in expected:
        raise RuntimeError(
            f"Notion DBプロパティ {name!r} のtypeが想定と違います: expected={expected!r} actual={actual!r}"
        )
    return prop


def _get_notion_context() -> tuple[Client, dict, dict]:
    """
    Notion クライアント・親オブジェクト・status プロパティ定義を返す。
    戻り値: (notion, parent, status_prop)
    """
    notion_api_key = _require_env("NOTION_API_KEY")
    database_id = _require_env("NOTION_DATABASE_ID")
    notion = Client(auth=notion_api_key)

    db = notion.databases.retrieve(database_id=database_id)
    if not isinstance(db, dict):
        raise RuntimeError(f"Notion APIから想定外の応答を受け取りました: {type(db)}")

    parent: dict
    schema_source: dict = db
    data_sources = db.get("data_sources") or []
    if isinstance(data_sources, list) and data_sources and isinstance(data_sources[0], dict) and data_sources[0].get("id"):
        data_source_id = str(data_sources[0]["id"])
        schema_source = notion.data_sources.retrieve(data_source_id=data_source_id)
        parent = {"data_source_id": data_source_id}
    else:
        parent = {"database_id": database_id}

    if not isinstance(schema_source, dict):
        raise RuntimeError(f"Notion APIから想定外の応答を受け取りました: {type(schema_source)}")

    _get_property(schema_source, PROP_TASK_NAME, "title")
    _get_property(schema_source, PROP_DUE, "date")
    _get_property(schema_source, PROP_LIFE_IDEA, "multi_select")
    status_prop = _get_property(schema_source, PROP_STATUS, ("multi_select", "status"))
    return notion, parent, status_prop


def register_notion_task(
    *,
    title: str,
    body: str = "",
    due: date | None = None,
    source_id: str = "",
    dry_run: bool = False,
    verbose: bool = True,
) -> dict:
    """
    1件 Notion DB に登録する。body は現状ページ本文には使わず API 互換のため保持。
    戻り値: ok, skipped, page_id, url など
    """
    notion, parent, status_prop = _get_notion_context()
    processed = _load_processed_ids()
    if source_id and source_id in processed:
        if verbose:
            print(f"SKIP: 既に処理済みです source_id={source_id!r}")
        return {"ok": True, "skipped": True, "source_id": source_id}

    if dry_run:
        if verbose:
            print(f"DRYRUN: title={title!r} source_id={source_id!r} due={str(due) if due else ''}")
        return {"ok": True, "dry_run": True, "title": title, "due": str(due) if due else ""}

    life_idea_value = LIFE_VALUE if due else IDEA_VALUE
    props: dict = {
        PROP_TASK_NAME: {"title": [{"type": "text", "text": {"content": title}}]},
        PROP_LIFE_IDEA: {"multi_select": [{"name": life_idea_value}]},
    }
    if status_prop.get("type") == "status":
        props[PROP_STATUS] = {"status": {"name": STATUS_TODO_VALUE}}
    else:
        props[PROP_STATUS] = {"multi_select": [{"name": STATUS_TODO_VALUE}]}
    if due:
        props[PROP_DUE] = {"date": {"start": due.isoformat()}}

    page = notion.pages.create(
        parent=parent,
        properties=props,
    )
    page_id = page.get("id", "")
    url = page.get("url", "")
    if verbose:
        print(f"OK: Notionに1件追加しました title={title!r} id={page_id} url={url}")

    if source_id:
        processed.add(source_id)
        _save_processed_ids(processed)

    return {"ok": True, "skipped": False, "page_id": page_id, "url": url, "title": title}


def _extract_first_email(header_val: str) -> str:
    """'Name <a@b.com>' または 'a@b.com' から最初のメールアドレスを取り出す。"""
    import re

    s = (header_val or "").strip()
    if not s:
        return ""
    m = re.search(r"<([^>]+)>", s)
    if m:
        return m.group(1).strip().lower()
    m2 = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", s)
    if m2:
        return m2.group(0).strip().lower()
    return ""


def _normalize_subject_for_prefix(subject: str) -> str:
    """Re:/Fwd: を繰り返し除去して件名の先頭比較用にする。"""
    s = (subject or "").strip()
    changed = True
    while changed and s:
        changed = False
        for prefix in ("re:", "fwd:", "fw:"):
            if s.lower().startswith(prefix):
                s = s[len(prefix) :].lstrip()
                changed = True
    return s.strip()


def _voice_mail_matches(
    *,
    from_addr: str,
    to_addr: str,
    subject: str,
    gmail_user: str,
    subject_prefix: str,
) -> bool:
    """
    Watch→自分宛メール経路用: 自分からの送信っぽいこと＋（任意）件名プレフィックス。
    """
    gu = (gmail_user or "").strip().lower()
    if not gu:
        return False
    from_lower = (from_addr or "").lower()
    to_lower = (to_addr or "").lower()
    from_email = _extract_first_email(from_addr)
    if from_email != gu and gu not in from_lower:
        return False
    if gu not in to_lower:
        return False
    if subject_prefix:
        subj = _normalize_subject_for_prefix(subject)
        if not subj.startswith(subject_prefix):
            return False
    return True


def _voice_mail_task_title(subject: str, body_text: str, *, subject_prefix: str) -> str:
    """タスク名: 件名からプレフィックス除去、無ければ本文先頭行。"""
    subj = _normalize_subject_for_prefix(subject)
    p = subject_prefix
    if p and subj.startswith(p):
        rest = subj[len(p) :].strip()
        if rest:
            return rest[:200]
    subj_stripped = subj.strip()
    if subj_stripped and subj_stripped.lower() not in ("(無題)", "no subject", "(no subject)"):
        return subj_stripped[:200]
    title, _ = _split_title_and_body(body_text or "")
    return (title or "Voice").strip()[:200]


def _iter_gmail_messages(
    *,
    user: str,
    app_password: str,
    folder: str,
    imap_search: str,
    max_messages: int,
) -> Iterable[tuple[str, str, str, str, str]]:
    """
    Yields (message_id, from_addr, to_addr, subject, body_text)
    """
    import imaplib
    import email
    from email import policy
    from email.parser import BytesParser

    with imaplib.IMAP4_SSL("imap.gmail.com") as imap:
        imap.login(user, app_password)
        typ, _ = imap.select(folder, readonly=True)
        if typ != "OK":
            raise RuntimeError(f"IMAP select failed folder={folder!r}")

        typ, data = imap.search(None, imap_search)
        if typ != "OK" or not data or not data[0]:
            return

        ids = data[0].split()
        ids = ids[-max_messages:] if max_messages > 0 else ids

        for msg_id in ids:
            # BODY.PEEK[] で既読を付けない
            typ, msg_data = imap.fetch(msg_id, "(BODY.PEEK[] RFC822)")
            if typ != "OK" or not msg_data:
                continue

            raw = b""
            for item in msg_data:
                if isinstance(item, tuple) and isinstance(item[1], (bytes, bytearray)):
                    raw += bytes(item[1])

            if not raw:
                continue

            msg = BytesParser(policy=policy.default).parsebytes(raw)
            message_id = (msg.get("Message-ID") or "").strip()
            from_addr = (msg.get("From") or "").strip()
            to_addr = (msg.get("To") or "").strip()
            subject = (msg.get("Subject") or "").strip()
            body_text = _extract_best_text_from_email(msg)
            yield (message_id, from_addr, to_addr, subject, body_text)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", default="", help="重複防止に使うID（例: Gmail Message-ID）")
    parser.add_argument("--title", default="", help="Notionに登録するタイトル（省略時は自動生成）")
    parser.add_argument("--from-gmail", action="store_true", help="Gmail(IMAP)から取得してNotion登録する")
    parser.add_argument("--gmail-folder", default="INBOX", help="IMAPフォルダ（例: INBOX）")
    parser.add_argument("--gmail-search", default="ALL", help="IMAP検索条件（例: ALL / UNSEEN / SUBJECT \"Keep\"）")
    parser.add_argument("--gmail-max", type=int, default=10, help="最大取得件数（末尾から）")
    parser.add_argument("--dry-run", action="store_true", help="Notion登録せずに取得結果だけ表示")
    parser.add_argument("--keep-only", action="store_true", help="Keepっぽいメールだけ処理する（件名/本文から判定）")
    parser.add_argument(
        "--voice-mail",
        action="store_true",
        help="Watch→自分宛メール用: Keepは使わず、自分へ送ったメールだけ取り込む（--from-gmail と併用）",
    )
    parser.add_argument(
        "--voice-subject-prefix",
        default="",
        help="音声メールの件名プレフィックス（省略時は環境変数 GMAIL_VOICE_SUBJECT_PREFIX）",
    )
    args = parser.parse_args()

    gmail_user = os.environ.get("GMAIL_USER", "").strip()
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()

    def upsert_one(*, title: str, source_id: str, body: str = "", due: date | None = None) -> None:
        register_notion_task(
            title=title,
            body=body,
            due=due,
            source_id=source_id,
            dry_run=args.dry_run,
            verbose=True,
        )

    if args.from_gmail:
        if not gmail_user or not gmail_app_password:
            raise RuntimeError("環境変数 GMAIL_USER / GMAIL_APP_PASSWORD が未設定です。")

        if args.keep_only and args.voice_mail:
            raise RuntimeError("--keep-only と --voice-mail は同時に使えません。")

        voice_prefix = (args.voice_subject_prefix or os.environ.get("GMAIL_VOICE_SUBJECT_PREFIX", "")).strip()
        if args.voice_mail and not voice_prefix:
            raise RuntimeError(
                "音声メールモード（--voice-mail）では、件名プレフィックスが必須です。"
                "例: 環境変数 GMAIL_VOICE_SUBJECT_PREFIX=[Voice] または "
                "`--voice-subject-prefix \"[Voice]\"` を指定してください。"
            )
        imap_search = str(args.gmail_search)
        if args.voice_mail:
            imap_search = os.environ.get("GMAIL_VOICE_IMAP_SEARCH", imap_search).strip() or imap_search
            if imap_search == "ALL":
                imap_search = "UNSEEN"

        count = 0
        for message_id, from_addr, to_addr, subject, body_text in _iter_gmail_messages(
            user=gmail_user,
            app_password=gmail_app_password,
            folder=str(args.gmail_folder),
            imap_search=imap_search,
            max_messages=int(args.gmail_max),
        ):
            if args.keep_only and not (
                _looks_like_keep_email(subject, body_text) or _looks_like_keep_sender(from_addr)
            ):
                continue
            if args.voice_mail:
                if not _voice_mail_matches(
                    from_addr=from_addr,
                    to_addr=to_addr,
                    subject=subject,
                    gmail_user=gmail_user,
                    subject_prefix=voice_prefix,
                ):
                    continue
                title = _voice_mail_task_title(subject, body_text, subject_prefix=voice_prefix)
                body = (body_text or "").strip()
                due = _parse_relative_date_jp(body_text or "")
            else:
                title, body = _split_title_and_body(body_text or subject or "")
                due = _parse_relative_date_jp(body_text or "")
            source_id = message_id or f"imap-uid:{count}"
            if len(title) > 80:
                title = title[:77] + "..."
            if args.dry_run:
                print(f"DEBUG: from={from_addr!r} to={to_addr!r} subject={subject!r}")
            upsert_one(title=title, source_id=source_id, body=body, due=due)
            count += 1

        print(f"DONE: processed {count} messages")
        return 0

    source_id = str(args.source_id).strip()
    title = str(args.title).strip()
    if not title:
        now = datetime.now(timezone.utc).astimezone()
        title = f"APIテスト {now.strftime('%Y-%m-%d %H:%M:%S')}"

    upsert_one(title=title, source_id=source_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
