import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote

import requests

TELEGRAM_API = "https://api.telegram.org"
TELEGRAM_FILE_API = "https://api.telegram.org/file/bot{token}/{path}"
REMOVE_BG_API = "https://api.remove.bg/v1.0/removebg"

MAX_WEBHOOK_BYTES = 1_000_000
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_MIME_PREFIX = "image/"


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing environment variable: {name}")
    return value


def telegram_call(method, *, data=None, files=None, timeout=20):
    token = env("TELEGRAM_BOT_TOKEN")
    response = requests.post(
        f"{TELEGRAM_API}/bot{token}/{method}",
        data=data,
        files=files,
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error in {method}")
    return result["result"]


def send_message(chat_id, text):
    telegram_call("sendMessage", data={"chat_id": chat_id, "text": text}, timeout=15)


def get_image_from_update(message):
    # Telegram photos are provided in several sizes; choose the largest.
    photos = message.get("photo") or []
    if photos:
        return photos[-1]["file_id"], "image/jpeg"

    document = message.get("document") or {}
    mime_type = document.get("mime_type", "")
    if document.get("file_id") and mime_type.startswith(ALLOWED_IMAGE_MIME_PREFIX):
        return document["file_id"], mime_type

    return None, None


def download_telegram_file(file_id):
    token = env("TELEGRAM_BOT_TOKEN")
    metadata = telegram_call("getFile", data={"file_id": file_id}, timeout=15)
    file_path = metadata.get("file_path")
    if not file_path:
        raise RuntimeError("Telegram did not return a file path")

    response = requests.get(
        TELEGRAM_FILE_API.format(token=token, path=file_path),
        timeout=25,
        stream=True,
    )
    response.raise_for_status()

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_IMAGE_BYTES:
            raise ValueError("Image is too large. Please send an image under 10 MB.")
        chunks.append(chunk)

    image_bytes = b"".join(chunks)
    if not image_bytes:
        raise ValueError("The uploaded image is empty.")
    return image_bytes


def remove_background(image_bytes, mime_type):
    api_key = env("REMOVEBG_API_KEY")
    response = requests.post(
        REMOVE_BG_API,
        headers={"X-Api-Key": api_key},
        files={"image_file": ("upload", image_bytes, mime_type)},
        data={"size": "auto", "format": "png"},
        timeout=45,
    )
    if response.status_code == 402:
        raise RuntimeError("The background-removal API quota or credits may be exhausted.")
    if response.status_code == 413:
        raise ValueError("The image is too large for the background-removal service.")
    if not response.ok:
        # Do not relay raw upstream responses, which could expose implementation details.
        raise RuntimeError(f"Background-removal service returned HTTP {response.status_code}.")
    if not response.content:
        raise RuntimeError("The background-removal service returned an empty image.")
    return response.content


def send_png(chat_id, png_bytes):
    telegram_call(
        "sendDocument",
        data={
            "chat_id": chat_id,
            "caption": "Background removed. Your PNG has a transparent background.",
        },
        files={"document": ("background-removed.png", png_bytes, "image/png")},
        timeout=25,
    )


def process_update(update):
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id:
        return

    text = (message.get("text") or "").strip()
    if text.startswith("/start") or text.startswith("/help"):
        send_message(
            chat_id,
            "Send me a photo or an image file, and I will return a PNG with its background removed.\\n\\n"
            "Please send images under 10 MB. No account or registration is required.",
        )
        return

    file_id, mime_type = get_image_from_update(message)
    if not file_id:
        send_message(chat_id, "Please send a photo or an image document (PNG, JPG, or WebP).")
        return

    # Avoid processing an image that is already known to exceed the supported limit.
    file_info = message.get("document") or {}
    if file_info.get("file_size", 0) > MAX_IMAGE_BYTES:
        send_message(chat_id, "That image is too large. Please send an image under 10 MB.")
        return

    send_message(chat_id, "Processing your image. Please wait…")
    try:
        source_bytes = download_telegram_file(file_id)
        output_bytes = remove_background(source_bytes, mime_type)
        send_png(chat_id, output_bytes)
    except ValueError as exc:
        send_message(chat_id, str(exc))
    except Exception:
        # Keep tokens, API responses, and internal details out of user-visible messages.
        send_message(
            chat_id,
            "Sorry, I couldn't process that image. Please try again later or use a smaller image.",
        )


class handler(BaseHTTPRequestHandler):
    def _reply(self, status, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        self._reply(200, {"ok": True, "service": "telegram-background-remover"})

    def do_POST(self):
        expected_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
        supplied_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not expected_secret or not hmac.compare_digest(supplied_secret, expected_secret):
            self._reply(401, {"ok": False, "error": "unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._reply(400, {"ok": False, "error": "invalid content length"})
            return

        if length <= 0 or length > MAX_WEBHOOK_BYTES:
            self._reply(413 if length > MAX_WEBHOOK_BYTES else 400,
                        {"ok": False, "error": "invalid request size"})
            return

        try:
            raw = self.rfile.read(length)
            update = json.loads(raw.decode("utf-8"))
            process_update(update)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._reply(400, {"ok": False, "error": "invalid JSON"})
            return
        except Exception:
            # Log only a generic failure; never print request bodies or credentials.
            self._reply(200, {"ok": True, "note": "update received"})
            return

        self._reply(200, {"ok": True})

    def log_message(self, format, *args):
        # Avoid writing request details to function logs.
        return
