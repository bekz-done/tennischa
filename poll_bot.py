from datetime import time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    PollAnswerHandler,
)

# === НАСТРОЙКИ ===
BOT_TOKEN = "7204419848:AAHGw28dWiC-C4UsOyLpv05WduBaV-sHREY"  # ⚠️ Поменяй на новый токен из BotFather!
GROUP_CHAT_ID = None   # установи командой /setgroup
TZ = ZoneInfo("Asia/Tashkent")

OPTIONS = ["Играю", "Не играю", "50/50"]

latest_poll_id: str | None = None
poll_results: dict[str, dict[str, list[int]]] = {}


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я делаю опрос в четверг 08:00 и публикую статистику в субботу 20:00.\n"
        "Команды: /chatid /setgroup /force_poll /force_summary"
    )

# /chatid
async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(f"Chat ID: {chat.id}\nTitle: {chat.title or ''}")

# /setgroup
async def setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global GROUP_CHAT_ID
    GROUP_CHAT_ID = update.effective_chat.id
    await update.message.reply_text(f"Группа сохранена. GROUP_CHAT_ID = {GROUP_CHAT_ID}")

# === Опрос ===
async def create_poll(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None = None):
    global latest_poll_id, poll_results
    target_chat = chat_id or GROUP_CHAT_ID
    if not target_chat:
        return
    msg = await context.bot.send_poll(
        chat_id=target_chat,
        question="Вы идете играть в воскресенье?",
        options=OPTIONS,
        is_anonymous=False,
        allows_multiple_answers=False,
    )
    latest_poll_id = msg.poll.id
    poll_results[latest_poll_id] = {}

async def on_poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    if ans.poll_id not in poll_results:
        poll_results[ans.poll_id] = {}
    name = ans.user.full_name
    if ans.user.username:
        name = f"{name} (@{ans.user.username})"
    poll_results[ans.poll_id][name] = ans.option_ids[:]

# === Статистика ===
async def post_summary(context: ContextTypes.DEFAULT_TYPE, chat_id: int | None = None):
    target_chat = chat_id or GROUP_CHAT_ID
    if not target_chat:
        return
    if not latest_poll_id or latest_poll_id not in poll_results:
        await context.bot.send_message(target_chat, "Пока нет данных для статистики.")
        return

    results = poll_results[latest_poll_id]
    going = [u for u, o in results.items() if 0 in o]
    not_going = [u for u, o in results.items() if 1 in o]
    fifty = [u for u, o in results.items() if 2 in o]

    text = [
        "📊 <b>Итоги голосования (воскресная игра)</b>",
        f"✅ Играют ({len(going)}): " + (", ".join(sorted(going)) if going else "никто"),
        f"❌ Не играют ({len(not_going)}): " + (", ".join(sorted(not_going)) if not_going else "никто"),
        f"🤷 50/50 ({len(fifty)}): " + (", ".join(sorted(fifty)) if fifty else "никто"),
    ]
    await context.bot.send_message(target_chat, "\n".join(text), parse_mode="HTML")

# Ручные команды
async def force_poll(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await create_poll(context, chat_id=update.effective_chat.id)
    await update.message.reply_text("Опрос создан.")

async def force_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await post_summary(context, chat_id=update.effective_chat.id)

# === Запуск ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("setgroup", setgroup))
    app.add_handler(CommandHandler("force_poll", force_poll))
    app.add_handler(CommandHandler("force_summary", force_summary))
    app.add_handler(PollAnswerHandler(on_poll_answer))

    jq = app.job_queue
    jq.run_daily(lambda c: create_poll(c), time=time(8, 0, tzinfo=TZ), days=(3,), name="weekly_poll")
    jq.run_daily(lambda c: post_summary(c), time=time(20, 0, tzinfo=TZ), days=(5,), name="weekly_summary")

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
