import os, logging
from uuid import uuid4
from flask import Flask
from threading import Thread
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, BotCommand
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, InlineQueryHandler
from pymongo import MongoClient

# ==== CONFIG ====
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
MONGO_URL = os.getenv("MONGO_URL")

# ==== DATABASE ====
client = MongoClient(MONGO_URL)
db = client["moviebot"]
files_col = db["files"]
users_col = db["users"]
logs_col = db["logs"]

# ==== LOGGING ====
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# ==== FLASK KEEP ALIVE ====
app = Flask('')

@app.route('/')
def home():
    return "✅ Bot is alive!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask).start()

def ensure_user(uid):
    if not users_col.find_one({"id": uid}):
        users_col.insert_one({"id": uid})

# ==== COMMANDS ====
def start(update: Update, ctx: CallbackContext):
    uid = update.effective_user.id
    ensure_user(uid)
    update.message.reply_text("🎬 Welcome! Use inline: `@bot MovieName` or `/help`", parse_mode="Markdown")

def help_cmd(update: Update, ctx: CallbackContext):
    texts = [
        "/start – Start the bot",
        "/help – Show commands",
        "/search – Inline guide",
        "/request <movie> – Request a movie",
        "🔒 Admin only:",
        "/upload – Upload movie",
        "/files – List movies",
        "/delete <title> – Delete movie",
        "/broadcast <msg> – Message all users",
        "/reply <id> <msg> – Reply to user",
        "/users – User count",
        "/logs – Recent requests"
    ]
    update.message.reply_text("\n".join(texts))

def search_cmd(update: Update, ctx: CallbackContext):
    update.message.reply_text("🔎 Use inline: `@bot MovieName 2023 1080p`", parse_mode="Markdown")

def request_movie(update: Update, ctx: CallbackContext):
    uid = update.effective_user.id
    req = " ".join(ctx.args)
    if not req:
        update.message.reply_text("⚠️ Usage: /request <movie>")
        return
    logs_col.insert_one({"id": uid, "name": update.effective_user.username, "query": req})
    ctx.bot.send_message(chat_id=ADMIN_ID, text=f"🎬 Request: {req}\n👤 {update.effective_user.username} ({uid})")
    update.message.reply_text("✅ Request sent to admin!")

def upload_start(update: Update, ctx: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Admin only.")
        return
    update.message.reply_text("📤 Send movie file with caption as title")

def handle_file(update: Update, ctx: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    file = update.message.video or update.message.document
    title = update.message.caption or "Untitled"
    if not file:
        update.message.reply_text("⚠️ Send video/document")
        return
    files_col.insert_one({"title": title, "file_id": file.file_id})
    update.message.reply_text("✅ Movie uploaded")

def show_files(update: Update, ctx: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    movies = list(files_col.find({}, {"title":1}))
    text = "\n".join(f"{i+1}. {m['title']}" for i, m in enumerate(movies[-20:]))
    update.message.reply_text(text or "No movies")

def delete_movie(update: Update, ctx: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    title = " ".join(ctx.args).lower()
    files_col.delete_many({"title": {"$regex": title, "$options": "i"}})
    update.message.reply_text("✅ Deleted entries")

def broadcast(update: Update, ctx: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = " ".join(ctx.args)
    uids = [u['id'] for u in users_col.find()]
    for uid in uids:
        try: ctx.bot.send_message(chat_id=uid, text=msg)
        except: pass
    update.message.reply_text(f"✅ Broadcasted to {len(uids)} users")

def reply(update: Update, ctx: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    target = int(ctx.args[0])
    msg = " ".join(ctx.args[1:])
    ctx.bot.send_message(chat_id=target, text=msg)
    update.message.reply_text("✅ Sent")

def show_users(update: Update, ctx: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    count = users_col.count_documents({})
    update.message.reply_text(f"👥 Users: {count}")

def show_logs(update: Update, ctx: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        return
    logs = list(logs_col.find().sort("_id", -1).limit(10))
    text = "\n".join(f"{l['name']} ({l['id']}): {l['query']}" for l in logs)
    update.message.reply_text(text or "No requests")

def inline_query(update: Update, ctx: CallbackContext):
    query = update.inline_query.query.lower()
    user = update.inline_query.from_user
    results = []
    match = False

    for m in files_col.find({"title": {"$regex": query, "$options": "i"}}):
        match = True
        results.append(InlineQueryResultArticle(id=str(uuid4()), title=m['title'],
            input_message_content=InputTextMessageContent(f"🎬 *{m['title']}*", parse_mode="Markdown")))

    # admin alert
    ctx.bot.send_message(ADMIN_ID, f"🔍 {user.username or user.first_name} ({user.id}) searched: {query}")

    if not match:
        results.append(InlineQueryResultArticle(id=str(uuid4()), title="No match found",
            input_message_content=InputTextMessageContent("⚠️ No match. Admin has been notified.", parse_mode="Markdown")))

    update.inline_query.answer(results, cache_time=1)

def main():
    updater = Updater(TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("search", search_cmd))
    dp.add_handler(CommandHandler("request", request_movie))
    dp.add_handler(CommandHandler("upload", upload_start))
    dp.add_handler(MessageHandler(Filters.video|Filters.document, handle_file))
    dp.add_handler(CommandHandler("files", show_files))
    dp.add_handler(CommandHandler("delete", delete_movie))
    dp.add_handler(CommandHandler("broadcast", broadcast))
    dp.add_handler(CommandHandler("reply", reply))
    dp.add_handler(CommandHandler("users", show_users))
    dp.add_handler(CommandHandler("logs", show_logs))
    dp.add_handler(InlineQueryHandler(inline_query))
    updater.bot.set_my_commands([
        BotCommand("start","Start"),BotCommand("help","Help"),
        BotCommand("search","Inline Guide"),BotCommand("request","Request"),
        BotCommand("upload","Admin Upload"),BotCommand("files","Admin Files"),
        BotCommand("delete","Admin Delete"),BotCommand("broadcast","Admin MsgAll"),
        BotCommand("reply","Admin Reply"),BotCommand("users","Admin Users"),
        BotCommand("logs","Admin Logs")
    ])
    updater.start_polling()
    logging.info("✅ Bot Started")
    updater.idle()

if __name__ == "__main__":
    main()
