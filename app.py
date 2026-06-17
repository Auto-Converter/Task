import json
import time
import uuid
import os
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

# ---------------- CONFIG ----------------

TOKEN = os.getenv("BOT_TOKEN")
DATA_FILE = "data.json"

INTERVALS = {
    "meow": 5 * 60,
    "fish": 15 * 60,
    "casino": 80 * 60
}

waiting = {}
panel_owner = {}  # message_id -> {user_id, time}

# ---------------- FILE ----------------

def load():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "chats" not in data:
                data["chats"] = {}
            return data
    except:
        return {"chats": {}}

def save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_chat(data, chat_id):
    if chat_id not in data["chats"]:
        data["chats"][chat_id] = {"tasks": []}
    return data["chats"][chat_id]

# ---------------- TIME ----------------

def parse_time(text: str) -> float:
    m = re.search(r"(\d+(\.\d+)?)", text.lower())
    if not m:
        return 0

    value = float(m.group(1))

    if "ساعت" in text:
        return value * 3600
    if "دقیقه" in text:
        return value * 60

    return value * 60

# ---------------- MENU ----------------

def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🐱 Meow", callback_data="preset:meow")],
        [InlineKeyboardButton("🎣 Fish", callback_data="preset:fish")],
        [InlineKeyboardButton("🎰 Casino", callback_data="preset:casino")],
        [InlineKeyboardButton("➕ New Task", callback_data="new")],
        [InlineKeyboardButton("📋 List Tasks", callback_data="list")]
    ])

# ---------------- ALERT (FIXED) ----------------

async def alert(context, q, text):
    try:
        await context.bot.answer_callback_query(
            callback_query_id=q.id,
            text=text,
            show_alert=True
        )
    except:
        pass

# ---------------- PANEL CHECK ----------------

def validate_panel(q, user_id):
    msg_id = q.message.message_id
    panel = panel_owner.get(msg_id)

    if not panel:
        return False, "پنل معتبر نیست"

    if time.time() - panel["time"] > 30:
        return False, "پنل منقضی شده"

    if panel["user_id"] != user_id:
        return False, "این پنل برای شما نیست"

    return True, None

# ---------------- START ----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📌 Bot Ready", reply_markup=menu())

# ---------------- CALLBACK ----------------

async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    chat_id = str(q.message.chat.id)
    user_id = q.from_user.id

    data = load()
    chat = get_chat(data, chat_id)

    # ---------- PRESET ----------
    if q.data.startswith("preset:"):
        t = q.data.split(":")[1]
        await q.message.reply_text("⏱ چند دقیقه؟")

        waiting[(chat_id, user_id)] = {"step": "preset", "type": t}

    # ---------- NEW ----------
    elif q.data == "new":
        await q.message.reply_text("📝 اسم تسک؟")

        waiting[(chat_id, user_id)] = {"step": "name"}

    # ---------- LIST ----------
    elif q.data == "list":

        if not chat["tasks"]:
            await q.message.reply_text("❌ خالیه")
            return

        text = "📋 Tasks:\n\n"
        keyboard = []

        for t in chat["tasks"]:
            if t["user_id"] == user_id:
                text += f"• {t['name']}\n"

                keyboard.append([
                    InlineKeyboardButton("❌ حذف", callback_data=f"del:{t['id']}"),
                    InlineKeyboardButton("⛔ stop", callback_data=f"stop:{t['id']}")
                ])

        msg = await q.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

        panel_owner[msg.message_id] = {
            "user_id": user_id,
            "time": time.time()
        }

    # ---------- DELETE ----------
    elif q.data.startswith("del:"):

        ok, err = validate_panel(q, user_id)
        if not ok:
            await alert(context, q, err)
            return

        task_id = q.data.split(":")[1]

        for task in chat["tasks"]:
            if task["id"] == task_id and task["user_id"] == user_id:
                chat["tasks"].remove(task)
                save(data)
                await q.message.reply_text("🗑 حذف شد")
                return

    # ---------- STOP ----------
    elif q.data.startswith("stop:"):

        ok, err = validate_panel(q, user_id)
        if not ok:
            await alert(context, q, err)
            return

        task_id = q.data.split(":")[1]

        for task in chat["tasks"]:
            if task["id"] == task_id and task["user_id"] == user_id:
                task["active"] = False
                task["next_run"] = float("inf")
                save(data)
                await q.message.reply_text("⛔ متوقف شد")
                return

# ---------------- TEXT FLOW ----------------

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    key = (chat_id, user_id)

    if key not in waiting:
        return

    state = waiting[key]
    text = update.message.text

    data = load()
    chat = get_chat(data, chat_id)

    # ---------- PRESET ----------
    if state["step"] == "preset":

        task = {
            "id": str(uuid.uuid4()),
            "name": state["type"],
            "type": state["type"],
            "user_id": user_id,
            "chat_id": chat_id,
            "next_run": time.time() + parse_time(text),
            "interval": INTERVALS[state["type"]],
            "active": True
        }

        chat["tasks"].append(task)
        save(data)

        await update.message.reply_text("✅ ساخته شد")
        del waiting[key]

    # ---------- NAME ----------
    elif state["step"] == "name":
        state["task_name"] = text
        state["step"] = "delay"
        await update.message.reply_text("⏱ زمان؟")
        waiting[key] = state

    # ---------- DELAY ----------
    elif state["step"] == "delay":
        state["delay"] = parse_time(text)
        state["step"] = "repeat"
        await update.message.reply_text("🔁 تکرار؟")
        waiting[key] = state

    # ---------- FINAL ----------
    elif state["step"] == "repeat":

        task = {
            "id": str(uuid.uuid4()),
            "name": state["task_name"],
            "type": "custom",
            "user_id": user_id,
            "chat_id": chat_id,
            "next_run": time.time() + state["delay"],
            "interval": parse_time(text),
            "active": True
        }

        chat["tasks"].append(task)
        save(data)

        await update.message.reply_text("✅ ساخته شد")
        del waiting[key]

# ---------------- JOB ----------------

async def job(context: ContextTypes.DEFAULT_TYPE):

    data = load()
    now = time.time()

    for chat_id, chat in list(data["chats"].items()):

        for task in chat["tasks"][:]:

            if not task.get("active"):
                continue

            if now < task["next_run"]:
                continue

            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⏰ [{task['name']}](tg://user?id={task['user_id']}) وقتشه!",
                    parse_mode="Markdown"
                )
            except:
                continue

            if task["interval"] > 0:
                task["next_run"] = now + task["interval"]
            else:
                task["active"] = False

    save(data)

# ---------------- CLEANUP ----------------

async def cleanup_panels(context: ContextTypes.DEFAULT_TYPE):
    now = time.time()

    for msg_id in list(panel_owner.keys()):
        if now - panel_owner[msg_id]["time"] > 30:
            del panel_owner[msg_id]

# ---------------- MAIN ----------------

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    app.job_queue.run_repeating(job, interval=10, first=5)
    app.job_queue.run_repeating(cleanup_panels, interval=10, first=10)

    PORT = int(os.environ.get("PORT", 10000))
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")

    print("Bot running with webhook...")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{RENDER_URL}/{TOKEN}",
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
