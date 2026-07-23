"""
GURUH BOSHQARUV BOTI - MINI APP BACKEND
=========================================
Bu server Render.com (yoki shunga o'xshash hosting)da ishlaydi.
Vazifasi:
  1) Mini App sahifasini (static/index.html) ko'rsatish
  2) Guruh sozlamalarini saqlash/qaytarish (API)
  3) Sozlamani o'zgartirishdan oldin - so'rov haqiqatan
     Telegram'dan kelayotganini va yuboruvchi o'sha guruhda
     ADMIN ekanligini tekshirish

O'RNATISH:
    pip install flask requests

ISHGA TUSHIRISH (lokal test uchun):
    python app.py

MUHIM: BOT_TOKEN quyida bot kodidagi bilan AYNAN BIR XIL bo'lishi kerak!
"""

import hashlib
import hmac
import json
import os
import time
import urllib.parse
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

# ==========================================
# Botdagi BOT_TOKEN bilan bir xil qiymat!
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8987581784:AAE2i3xYaNlSFqoc_T6j_FBAEBmgjecI9QM")

SETTINGS_FILE = Path(__file__).parent / "settings.json"

DEFAULT_SETTINGS = {
    "subscription_check": True,
    "spam_filter": True,
    "link_filter": True,
    "join_leave_delete": True,
}

app = Flask(__name__, static_folder="static")


# ------------------------------------------
# Sozlamalarni fayldan o'qish / yozish
# (Diqqat: Render bepul tarifida disk doimiy emas -
#  qayta deploy qilinganda tozalanishi mumkin. Agar doimiy
#  saqlash kerak bo'lsa, keyinchalik bazaga (masalan Postgres)
#  o'tkazish mumkin.)
# ------------------------------------------
def load_all_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_all_settings(data: dict):
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def get_chat_settings(chat_id: str) -> dict:
    all_settings = load_all_settings()
    chat_settings = all_settings.get(str(chat_id), {})
    merged = {**DEFAULT_SETTINGS, **chat_settings}
    return merged


def set_chat_settings(chat_id: str, updates: dict):
    all_settings = load_all_settings()
    current = {**DEFAULT_SETTINGS, **all_settings.get(str(chat_id), {})}
    current.update(updates)
    all_settings[str(chat_id)] = current
    save_all_settings(all_settings)
    return current


# ------------------------------------------
# Telegram WebApp initData'ni tekshirish
# (Bu - so'rov haqiqatan Telegram'dan kelganini isbotlaydi,
#  soxta so'rovlarning oldini oladi)
# https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
# ------------------------------------------
def validate_init_data(init_data: str, max_age_seconds: int = 3600):
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(parsed.items())
    )

    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        return None

    auth_date = int(parsed.get("auth_date", 0))
    if time.time() - auth_date > max_age_seconds:
        return None  # eskirgan (1 soatdan katta) - xavfsizlik uchun rad etamiz

    user_raw = parsed.get("user")
    user = json.loads(user_raw) if user_raw else None
    return {"user": user, "auth_date": auth_date}


def is_telegram_chat_admin(chat_id: str, user_id: int) -> bool:
    """Bot API orqali foydalanuvchi shu guruhda admin ekanligini tekshiradi."""
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
            params={"chat_id": chat_id, "user_id": user_id},
            timeout=5,
        )
        data = resp.json()
        if not data.get("ok"):
            return False
        status = data["result"]["status"]
        return status in ("administrator", "creator")
    except Exception:
        return False


# ------------------------------------------
# Mini App sahifasini ko'rsatish
# ------------------------------------------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ------------------------------------------
# GET /api/settings/<chat_id> - joriy sozlamalarni olish
# (o'qish uchun initData shart emas, faqat o'zgartirish uchun kerak)
# ------------------------------------------
@app.route("/api/settings/<chat_id>", methods=["GET"])
def api_get_settings(chat_id):
    return jsonify(get_chat_settings(chat_id))


# ------------------------------------------
# POST /api/settings/<chat_id> - sozlamani o'zgartirish
# Header: X-Telegram-Init-Data - Mini App yuborgan initData
# Body (JSON): { "subscription_check": true/false, ... }
# ------------------------------------------
@app.route("/api/settings/<chat_id>", methods=["POST"])
def api_update_settings(chat_id):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    validated = validate_init_data(init_data)
    if not validated or not validated["user"]:
        return jsonify({"error": "Tekshiruvdan o'tmadi (noto'g'ri initData)"}), 401

    user_id = validated["user"]["id"]
    if not is_telegram_chat_admin(chat_id, user_id):
        return jsonify({"error": "Faqat guruh adminlari sozlamalarni o'zgartira oladi"}), 403

    updates = request.get_json(silent=True) or {}
    allowed_keys = set(DEFAULT_SETTINGS.keys())
    clean_updates = {k: bool(v) for k, v in updates.items() if k in allowed_keys}

    new_settings = set_chat_settings(chat_id, clean_updates)
    return jsonify(new_settings)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
