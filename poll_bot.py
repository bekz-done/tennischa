#!/usr/bin/env python3
"""
Telegram poll bot for Sunday game — ready for Render.com / any 24/7 host.

Features
- Posts a NON-ANONYMOUS poll every Thursday 08:00 (Asia/Tashkent): ["Играю", "Не играю", "50/50"].
- Posts a summary every Saturday 20:00 (Asia/Tashkent) with who goes / not / 50-50.
- Commands: /start, /chatid, /setgroup, /force_poll, /force_summary.
- Uses env var BOT_TOKEN (do NOT hardcode tokens). Optional GROUP_CHAT_ID env var.
- Persists group chat id and votes to small JSON files (settings.json, votes.json).

Run locally
  export BOT_TOKEN=123456:ABC...
  python poll_bot_render.py

Deploy on Render
  requirements.txt -> python-telegram-bot[http2]>=21.1,<22.0\napscheduler\npytz
  Procfile        -> worker: python poll_bot_render.py
  Env vars        -> BOT_TOKEN=... (optional GROUP_CHAT_ID=-100xxxxxxxxxx)

Requires: python-telegram-bot >= 21.1, APScheduler, pytz (or Python 3.9+ with zoneinfo)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    PollAnswerHandler,
)

# ---------------- Config ----------------
TZ = ZoneInfo("Asia/Tashkent")
OPTIONS = ["Играю", "Не играю", "50/50"]
DATA_DIR = Path(".")
SETTINGS_FILE = DATA_DIR / "settings.json"
VOTES_FILE = DATA_DIR / "votes.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("poll-bot")

# ---------------- Persistence helpers ----------------

def _read_json(path: Path, default):
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        log.warning("Failed to read %s: %s", path, e)
        return default


def _write_json(path: Path, obj) -> None:
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        tmp.replace(path)
    except Exception as e:
        log.warning("Failed to write %s: %s", path, e)


# in-memory state (mirrored to disk)
settings = _read_json(SETTINGS_FILE, {})  # keys: group_chat_id, latest_poll_id
votes: Dict[str, Dict[str, List[int]]] = _read_json(VOTES_FILE, {})  # poll_id -> {user_name: [option_ids]}


# ---------------- Handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я делаю опрос в четверг 08:00 и публикую статистику в субботу 20:00 (Asia/Tashkent).\n\n"
        "Команды:\n"
        "/chatid — показать ID чата\n"
        "/setgroup — сохранить этот чат как основной\n"
        "/force_poll — создать опрос сейчас\n"
        "/force_summary — показать статистику сейчас"
    )


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"Chat ID: {chat.id}\nTitle: {chat.title or ''}")


async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    settings["group_chat_id"] = chat.id
    _write_json(SETTINGS_FILE, settings)
    await update.message.reply_text(f"Группа сохранена. GROUP_CHAT_ID = {chat.id}")


async def create_poll(context: ContextTypes.DEFAULT_TYPE, chat_id: Optional[int] = None):
    target_chat = (
        chat_id
        or settings.get("group_chat_id")
        or (int(os.getenv("GROUP_CHAT_ID")) if os.getenv("GROUP_CHAT_ID") else None)
    )
    if not target_chat:
        log.warning("No group_chat_id set; skip poll creation")
        return

    msg = await context.bot.send_poll(
        chat_id=target_chat,
        question="Вы идете играть в воскресенье?",
        options=OPTIONS,
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    settings["latest_poll_id"] = msg.poll.id
    _write_json(SETTINGS_FILE, settings)
    votes.setdefault(msg.poll.id, {})
    _write_json(VOTES_FILE, votes)
    log.info("Created poll %s in chat %s", msg.poll.id, target_chat)


async def on_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    pid = ans.poll_id
    name = ans.user.full_name
    if ans.user.username:
        name = f"{name} (@{ans.user.username})"
    votes.setdefault(pid, {})[name] = ans.option_ids[:]
    _write_json(VOTES_FILE, votes)
    log.info("Vote: poll=%s user=%s choice=%s", pid, name, ans.option_ids)


def _build_summary_text(pid: str) -> str:
    data = votes.get(pid, {})
    going = sorted([u for u, o in data.items() if 0 in o])
    not_going = sorted([u for u, o in data.items() if 1 in o])
    fifty = sorted([u for u, o in data.items() if 2 in o])
    lines = ["📊 <b>Итоги голосования (воскресная игра)</b>"]
    lines.append(f"✅ Играют ({len(going)}): " + (", ".join(going) if going else "никто"))
    lines.append(f"❌ Не играют ({len(not_going)}): " + (", ".join(not_going) if not_going else "никто"))
    lines.append(f"🤷 50/50 ({len(fifty)}): " + (", ".join(fifty) if fifty else "никто"))
    return "\n".join(lines)


async def post_summary(context: ContextTypes.DEFAULT_TYPE, chat_id: Optional[int] = None):
    target_chat = (
        chat_id
        or settings.get("group_chat_id")
        or (int(os.getenv("GROUP_CHAT_ID")) if os.getenv("GROUP_CHAT_ID") else None)
    )
    if not target_chat:
        log.warning("No group_chat_id set; skip summary")
        return

    pid = settings.get("latest_poll_id")
    if not pid:
        await context.bot.send_message(target_chat, "Пока нет данных для статистики.")
        return

    text = _build_summary_text(pid)
    await context.bot.send_message(target_chat, text, parse_mode=ParseMode.HTML)


async def force_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await create_poll(context, chat_id=update.effective_chat.id)
    await update.message.reply_text("Опрос создан.")


async def force_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await post_summary(context, chat_id=update.effective_chat.id)


# ---------------- Main ----------------

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN env var is required")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("setgroup", setgroup))
    app.add_handler(CommandHandler("force_poll", force_poll))
    app.add_handler(CommandHandler("force_summary", force_summary))
    app.add_handler(PollAnswerHandler(on_poll_answer))

    jq = app.job_queue
    jq.run_daily(lambda c: create_poll(c), time=time(8, 0, tzinfo=TZ), days=(3,), name="weekly_poll")  # Thu 08:00
    jq.run_daily(lambda c: post_summary(c), time=time(20, 0, tzinfo=TZ), days=(5,), name="weekly_summary")  # Sat 20:00

    log.info("Bot is running…")
    app.run_polling()


if __name__ == "__main__":
    main()
