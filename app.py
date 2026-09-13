"""音声入力 → 文字起こし確認 → Notion「DB6本タスク管理」へ登録する Flask アプリ。"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
NOTION_VERSION_DATA_SOURCE = "2025-09-03"
TITLE_MAX_CHARS = 2000
JST = timezone(timedelta(hours=9))

PROP_DUE = "期日"
PROP_STATUS = "ステータス"
PROP_LIFE_IDEA = "生活：アイデア"
STATUS_VALUE = "未完了"
LIFE_VALUE = "生活"

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("voice_notion")

_SECRET_PATTERNS = (
    re.compile(r"secret_[A-Za-z0-9]+", re.I),
    re.compile(r"ntn_[A-Za-z0-9]+", re.I),
    re.compile(r"Bearer\s+\S+", re.I),
)


def _redact(text: str) -> str:
    out = text or ""
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    key = os.environ.get("NOTION_API_KEY", "").strip()
    if key:
        out = out.replace(key, "[REDACTED]")
    return out


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _notion_headers(api_key: str, version: str = NOTION_VERSION) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": version,
        "Content-Type": "application/json",
    }


def _notion_request(
    method: str,
    url: str,
    api_key: str,
    body: dict[str, Any] | None = None,
    version: str = NOTION_VERSION,
) -> tuple[int, dict[str, Any] | str]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers=_notion_headers(api_key, version), method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        logger.error("Notion API HTTPError status=%s body=%s", exc.code, _redact(raw))
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw
    except urllib.error.URLError as exc:
        logger.error("Notion API 接続エラー: %s", _redact(str(exc.reason)))
        return 0, {"message": "Notion API に接続できませんでした"}

    try:
        parsed: dict[str, Any] | str = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = raw
    return status, parsed


def _schema_properties(schema: dict[str, Any]) -> dict[str, Any]:
    props = schema.get("properties") or {}
    if props:
        return props
    data_sources = schema.get("data_sources") or []
    if isinstance(data_sources, list) and data_sources:
        ds0 = data_sources[0]
        if isinstance(ds0, dict):
            return ds0.get("properties") or {}
    return {}


def _find_title_property_name(schema: dict[str, Any]) -> str:
    props = _schema_properties(schema)
    for prop_name, prop in props.items():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return str(prop_name)
    debug = []
    for prop_name, prop in props.items():
        if isinstance(prop, dict):
            debug.append(f"{prop_name}={prop.get('type')}")
        else:
            debug.append(f"{prop_name}=<non-dict>")
    debug_str = ", ".join(debug) if debug else "<no properties>"
    raise RuntimeError(f"title 型のプロパティが見つかりませんでした properties={debug_str}")


def _normalize_prop_name(name: str) -> str:
    return (name or "").replace("：", ":").replace(" ", "").strip()


def _find_property(props: dict[str, Any], wanted: str) -> tuple[str, dict[str, Any]]:
    if wanted in props and isinstance(props[wanted], dict):
        return wanted, props[wanted]
    wanted_n = _normalize_prop_name(wanted)
    for name, prop in props.items():
        if isinstance(prop, dict) and _normalize_prop_name(name) == wanted_n:
            return str(name), prop
    raise RuntimeError(f"プロパティが見つかりませんでした: {wanted}")


def _option_value(prop: dict[str, Any], preferred: str, fallbacks: tuple[str, ...] = ()) -> str:
    names = [preferred, *fallbacks]
    options: list[Any] = []
    for key in ("status", "select", "multi_select"):
        block = prop.get(key)
        if isinstance(block, dict) and isinstance(block.get("options"), list):
            options = block["options"]
            break
    available = []
    for opt in options:
        if isinstance(opt, dict):
            n = str(opt.get("name") or "").strip()
            if n:
                available.append(n)
    if not available:
        return preferred
    for name in names:
        if name in available:
            return name
    logger.error("指定の選択肢がDBにありません preferred=%s available=%s", preferred, ",".join(available))
    raise RuntimeError(f"選択肢 {preferred} がプロパティにありません")


def _prop_payload(prop: dict[str, Any], *, date_iso: str | None = None, option_name: str | None = None) -> dict[str, Any]:
    ptype = prop.get("type")
    if ptype == "date":
        if not date_iso:
            raise RuntimeError("date プロパティに日付がありません")
        return {"date": {"start": date_iso}}
    if not option_name:
        raise RuntimeError(f"{ptype} プロパティに値がありません")
    if ptype == "status":
        return {"status": {"name": option_name}}
    if ptype == "select":
        return {"select": {"name": option_name}}
    if ptype == "multi_select":
        return {"multi_select": [{"name": option_name}]}
    raise RuntimeError(f"未対応のプロパティ型です type={ptype}")


def _transcribe_ja(src_path: Path, wav_path: Path) -> str:
    import imageio_ffmpeg
    import speech_recognition as sr

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-i",
            str(src_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not wav_path.is_file():
        logger.error("ffmpeg 変換に失敗 code=%s stderr=%s", proc.returncode, (proc.stderr or "")[-500:])
        raise RuntimeError("audio_convert_failed")

    recognizer = sr.Recognizer()
    with sr.AudioFile(str(wav_path)) as source:
        audio = recognizer.record(source)
    try:
        return str(recognizer.recognize_google(audio, language="ja-JP") or "").strip()
    except sr.UnknownValueError:
        return ""


def _load_schema_and_parent(
    api_key: str, object_id: str
) -> tuple[dict[str, Any] | None, dict[str, str] | None, str]:
    db_status, db_body = _notion_request(
        "GET",
        f"{NOTION_API_BASE}/databases/{object_id}",
        api_key,
    )
    if db_status == 200 and isinstance(db_body, dict):
        props = db_body.get("properties") or {}
        if props:
            return db_body, {"database_id": object_id}, NOTION_VERSION
        data_sources = db_body.get("data_sources") or []
        if isinstance(data_sources, list) and data_sources:
            ds_id = str((data_sources[0] or {}).get("id") or "").strip()
            if ds_id:
                ds_status, ds_body = _notion_request(
                    "GET",
                    f"{NOTION_API_BASE}/data_sources/{ds_id}",
                    api_key,
                    version=NOTION_VERSION_DATA_SOURCE,
                )
                if ds_status == 200 and isinstance(ds_body, dict):
                    return ds_body, {"data_source_id": ds_id}, NOTION_VERSION_DATA_SOURCE
        return db_body, {"database_id": object_id}, NOTION_VERSION

    ds_status, ds_body = _notion_request(
        "GET",
        f"{NOTION_API_BASE}/data_sources/{object_id}",
        api_key,
        version=NOTION_VERSION_DATA_SOURCE,
    )
    if ds_status == 200 and isinstance(ds_body, dict):
        return ds_body, {"data_source_id": object_id}, NOTION_VERSION_DATA_SOURCE

    logger.error(
        "データベース/データソース取得に失敗 db_status=%s ds_status=%s db_body=%s ds_body=%s",
        db_status,
        ds_status,
        _redact(str(db_body)),
        _redact(str(ds_body)),
    )
    return None, None, NOTION_VERSION


def _is_cloud() -> bool:
    return bool(_env("PORT") or _env("VOICE_CLOUD") == "1" or _env("RAILWAY_ENVIRONMENT") or _env("RENDER"))


def _voice_secret_ok() -> bool:
    expected = _env("VOICE_SHARED_SECRET")
    if not expected:
        return True
    got = (request.headers.get("X-Voice-Secret") or "").strip()
    return got == expected


def _reject_unless_secret():
    if _voice_secret_ok():
        return None
    return jsonify({"ok": False, "error": "unauthorized"}), 401


@app.get("/")
def index():
    return render_template(
        "index.html",
        secret_required=bool(_env("VOICE_SHARED_SECRET")),
    )


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@app.get("/api/config")
def api_config():
    return jsonify(
        {
            "ok": True,
            "secret_required": bool(_env("VOICE_SHARED_SECRET")),
            "cloud": _is_cloud(),
        }
    )


@app.get("/manifest.webmanifest")
def manifest():
    static_dir = Path(__file__).resolve().parent / "static"
    return send_from_directory(
        static_dir, "manifest.webmanifest", mimetype="application/manifest+json"
    )


@app.post("/api/speech-to-text")
def speech_to_text():
    denied = _reject_unless_secret()
    if denied:
        return denied
    audio = request.files.get("audio")
    if audio is None or not audio.filename:
        return jsonify({"ok": False, "error": "no_audio"}), 400
    raw = audio.read()
    if not raw:
        return jsonify({"ok": False, "error": "empty_audio"}), 400
    if len(raw) > 12 * 1024 * 1024:
        return jsonify({"ok": False, "error": "too_large"}), 400

    suffix = Path(audio.filename).suffix or ".webm"
    tmp_dir = Path(tempfile.mkdtemp(prefix="voice_stt_"))
    src_path = tmp_dir / f"input{suffix}"
    wav_path = tmp_dir / "input.wav"
    src_path.write_bytes(raw)
    try:
        text = _transcribe_ja(src_path, wav_path)
    except Exception as exc:
        logger.error("音声認識に失敗: %s", _redact(str(exc)))
        return jsonify({"ok": False, "error": "stt_failed"}), 502
    finally:
        for p in tmp_dir.glob("*"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass

    if not text:
        return jsonify({"ok": False, "error": "empty_transcript"}), 400
    return jsonify({"ok": True, "text": text})


@app.post("/api/notion/add-task")
def add_task():
    denied = _reject_unless_secret()
    if denied:
        return denied

    api_key = _env("NOTION_API_KEY")
    database_id = _env("NOTION_DB_6PON_ID") or _env("NOTION_DATABASE_ID")
    if not api_key or not database_id:
        logger.error(
            "環境変数が不足しています（変数名のみ。値は出力しません）: NOTION_API_KEY=%s NOTION_DB_6PON_ID=%s",
            bool(api_key),
            bool(database_id),
        )
        return jsonify({"ok": False, "error": "server_misconfigured"}), 500

    payload = request.get_json(silent=True) or {}
    text = str(payload.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "empty_text"}), 400

    title = text[:TITLE_MAX_CHARS]

    schema, parent, api_version = _load_schema_and_parent(api_key, database_id)
    if schema is None or parent is None:
        logger.error(
            "データベース取得に失敗しました。NOTION_DB_6PON_ID の対象DBにインテグレーションが接続されているか確認してください（ID・APIキーは出力しません）。"
        )
        return jsonify({"ok": False, "error": "notion_failed"}), 502

    try:
        title_prop = _find_title_property_name(schema)
        props_map = _schema_properties(schema)
        due_name, due_prop = _find_property(props_map, PROP_DUE)
        status_name, status_prop = _find_property(props_map, PROP_STATUS)
        life_name, life_prop = _find_property(props_map, PROP_LIFE_IDEA)
        status_value = _option_value(status_prop, STATUS_VALUE, ("未着手",))
        life_value = _option_value(life_prop, LIFE_VALUE)
        today = datetime.now(JST).date().isoformat()
        properties = {
            title_prop: {
                "title": [{"type": "text", "text": {"content": title}}],
            },
            due_name: _prop_payload(due_prop, date_iso=today),
            status_name: _prop_payload(status_prop, option_name=status_value),
            life_name: _prop_payload(life_prop, option_name=life_value),
        }
    except RuntimeError as exc:
        logger.error("%s", exc)
        return jsonify({"ok": False, "error": "notion_failed"}), 502

    page_body = {
        "parent": parent,
        "properties": properties,
    }
    page_status, page_resp = _notion_request(
        "POST",
        f"{NOTION_API_BASE}/pages",
        api_key,
        page_body,
        version=api_version,
    )
    if page_status != 200 or not isinstance(page_resp, dict) or not page_resp.get("id"):
        logger.error("ページ作成に失敗 status=%s body=%s", page_status, _redact(str(page_resp)))
        return jsonify({"ok": False, "error": "notion_failed"}), 502

    logger.info(
        "Notion へ登録成功 page_id=%s title_prop=%s due=%s status=%s life=%s",
        page_resp.get("id"),
        title_prop,
        today,
        status_value,
        life_value,
    )
    return jsonify({"ok": True})


INTERNAL_FLASK_PORT = 5002
PUBLIC_PORT = 5000


def _lan_ipv4() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _ensure_dev_cert() -> tuple[str, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    cert_dir = Path(__file__).resolve().parent / "certs"
    cert_dir.mkdir(exist_ok=True)
    cert_file = cert_dir / "cert.pem"
    key_file = cert_dir / "key.pem"
    if cert_file.is_file() and key_file.is_file():
        return str(cert_file), str(key_file)

    lan = _lan_ipv4()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    alt_names: list[x509.GeneralName] = []
    for name in (lan, "127.0.0.1", "localhost"):
        try:
            alt_names.append(x509.IPAddress(ip_address(name)))
        except ValueError:
            alt_names.append(x509.DNSName(name))
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, lan)]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, lan)]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(alt_names), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return str(cert_file), str(key_file)


def _make_ssl_context() -> ssl.SSLContext:
    cert_file, key_file = _ensure_dev_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(certfile=cert_file, keyfile=key_file)
    return ctx


def _tcp_pipe(left: socket.socket, right: socket.socket) -> None:
    def pump(src: socket.socket, dst: socket.socket) -> None:
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    threading.Thread(target=pump, args=(right, left), daemon=True).start()
    pump(left, right)
    for sock in (left, right):
        try:
            sock.close()
        except OSError:
            pass


def _handle_public_client(client: socket.socket, ssl_ctx: ssl.SSLContext) -> None:
    backend = None
    try:
        client.settimeout(8)
        first = client.recv(1, socket.MSG_PEEK)
        client.settimeout(None)
        if first[:1] == b"\x16":
            client = ssl_ctx.wrap_socket(client, server_side=True)
        backend = socket.create_connection(("127.0.0.1", INTERNAL_FLASK_PORT), timeout=8)
        backend.settimeout(None)
        _tcp_pipe(client, backend)
    except Exception as exc:
        logger.error("接続処理エラー: %s", _redact(str(exc)))
        for sock in (client, backend):
            if sock is None:
                continue
            try:
                sock.close()
            except OSError:
                pass


def _serve_public(ssl_ctx: ssl.SSLContext) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", PUBLIC_PORT))
    server.listen(64)
    while True:
        client, _addr = server.accept()
        threading.Thread(target=_handle_public_client, args=(client, ssl_ctx), daemon=True).start()


def main() -> None:
    if _is_cloud():
        port = int(_env("PORT") or "8080")
        logger.info("クラウド公開モード http://0.0.0.0:%s （HTTPS はホスト側が担当）", port)
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        return

    lan = _lan_ipv4()
    ssl_ctx = _make_ssl_context()
    threading.Thread(
        target=lambda: app.run(
            host="127.0.0.1",
            port=INTERNAL_FLASK_PORT,
            debug=False,
            use_reloader=False,
        ),
        daemon=True,
    ).start()
    time.sleep(0.4)
    logger.info("PC: http://127.0.0.1:%s", PUBLIC_PORT)
    logger.info("スマホ: http://%s:%s", lan, PUBLIC_PORT)
    logger.info("音声入力: 同じアドレスで自動的に https へ切り替わります")
    _serve_public(ssl_ctx)


if __name__ == "__main__":
    main()
