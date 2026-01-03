# bot.py
import os
import sqlite3
import threading
import time
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
from mpesa import initiate_stk_push

load_dotenv()

# ---------------- CONFIG ----------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is required in .env")
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DB = "database.db"
MPESA_CALLBACK_URL = os.getenv("MPESA_CALLBACK_URL")
PORT = int(os.getenv("PORT", 5000))
RENDER_APP_URL = os.getenv("RENDER_APP_URL", "")

# ---------------- DATABASE SETUP ----------------
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # Users
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        unlocked INTEGER DEFAULT 0,
        shares INTEGER DEFAULT 0,
        quizzes_passed INTEGER DEFAULT 0,
        promotions_used INTEGER DEFAULT 0,
        expires_at INTEGER DEFAULT 0
    )""")
    # Groups
    c.execute("""CREATE TABLE IF NOT EXISTS approved_groups (
        chat_id INTEGER PRIMARY KEY,
        title TEXT,
        username TEXT,
        added_by INTEGER
    )""")
    # Broadcasts
    c.execute("""CREATE TABLE IF NOT EXISTS broadcasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        link TEXT,
        user_id INTEGER,
        timestamp INTEGER
    )""")
    # Payments
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT,
        amount INTEGER,
        package TEXT,
        user_id INTEGER,
        status TEXT DEFAULT 'pending',
        timestamp INTEGER
    )""")
    # Packages
    c.execute("""CREATE TABLE IF NOT EXISTS packages (
        id INTEGER PRIMARY KEY,
        name TEXT,
        price INTEGER,
        shares INTEGER
    )""")
    # Insert default packages if empty
    c.execute("SELECT COUNT(*) FROM packages")
    if c.fetchone()[0] == 0:
        c.executemany("INSERT INTO packages VALUES (?, ?, ?, ?)", [
            (1, "BASIC", 20, 20),
            (2, "PRO", 50, 50),
            (3, "VIP", 100, 100),
        ])
    conn.commit()
    conn.close()

# ---------------- HELPERS ----------------
def get_user(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()
        row = (user_id, 0, 0, 0, 0, 0)
    conn.close()
    return row

def unlock_shares(user_id, shares):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE users SET unlocked = 1, shares = shares + ?, quizzes_passed = 1 WHERE user_id = ?", (shares, user_id))
    conn.commit()
    conn.close()

def use_share(user_id):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("UPDATE users SET shares = shares - 1, promotions_used = promotions_used + 1 WHERE user_id = ? AND shares > 0", (user_id,))
    success = c.rowcount > 0
    conn.commit()
    conn.close()
    return success

def is_admin(user_id):
    return user_id in ADMIN_IDS

def register_group(chat_id, title, username, added_by):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO approved_groups VALUES (?, ?, ?, ?)", (chat_id, title, username, added_by))
    conn.commit()
    conn.close()

def get_approved_groups():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT chat_id, title, username FROM approved_groups")
    rows = c.fetchall()
    conn.close()
    return rows

# ---------------- FLASK APP (CALLBACK + HEALTH) ----------------
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Viral Music Super Bot Running!"

@flask_app.route("/mpesa_callback", methods=["POST"])
def mpesa_callback():
    try:
        data = request.json
        callback = data.get("Body", {}).get("stkCallback", {})
        if callback.get("ResultCode") != 0:
            return jsonify({"status": "failed"}), 200

        meta = callback["CallbackMetadata"]["Item"]
        amount = next(item["Value"] for item in meta if item["Name"] == "Amount")
        phone = next(item["Value"] for item in meta if item["Name"] == "PhoneNumber")
        account_ref = callback.get("MerchantRequestID")  # user_id

        user_id = int(account_ref)
        package_name = "Custom"

        # Determine package by amount
        package_map = {20: "BASIC", 50: "PRO", 100: "VIP"}
        shares = package_map.get(amount, 20)
        if amount in package_map:
            package_name = package_map[amount]

        # Record payment
        conn = sqlite3.connect(DB)
        c = conn.cursor()
        c.execute("INSERT INTO payments (phone, amount, package, user_id, status, timestamp) VALUES (?, ?, ?, ?, 'verified', ?)",
                  (str(phone), amount, package_name, user_id, int(time.time())))
        unlock_shares(user_id, shares)
        conn.commit()
        conn.close()

        # Notify user
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        bot.send_message(user_id, f"✅ Payment of KES {amount} confirmed!\nYou now have {shares} promotion shares.")
        if ADMIN_IDS:
            for aid in ADMIN_IDS:
                try:
                    bot.send_message(aid, f"💰 New payment!\nUser: {user_id}\nAmount: KES {amount}\nPackage: {package_name}")
                except:
                    pass

        return jsonify({"status": "verified"}), 200
    except Exception as e:
        print("Callback error:", e)
        return jsonify({"error": str(e)}), 500

# ---------------- TELEGRAM COMMANDS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = get_user(update.effective_user.id)
    kb = [[InlineKeyboardButton("🎧 Take Quiz", callback_data="quiz")]]
    msg = (
        "🎶 *Welcome to Viral Music Bot!*\n\n"
        "🔹 Pass the quiz to get *20 free shares*\n"
        "🔹 Or buy more shares via MPESA\n\n"
        f"Your shares: *{user[2]}*\n"
        "Use /promote <link> to share after unlocking."
    )
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode=ParseMode.MARKDOWN)

async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    kb = [
        [InlineKeyboardButton("Mama & Teachers", callback_data="correct")],
        [InlineKeyboardButton("Dance Party", callback_data="wrong")]
    ]
    await update.callback_query.message.reply_text("What is the song about?", reply_markup=InlineKeyboardMarkup(kb))

async def quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "correct":
        unlock_shares(q.from_user.id, 20)
        await q.message.reply_text("✅ Correct! You’ve been awarded 20 promotion shares.")
    else:
        await q.message.reply_text("❌ Incorrect. Try listening again!")

async def promote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("UsageId: /promote https://example.com")
        return
    link = context.args[0]
    user_id = update.effective_user.id
    user = get_user(user_id)
    if user[2] <= 0:
        await update.message.reply_text("🔒 You have no shares left. Buy more with /buy")
        return
    if use_share(user_id):
        groups = get_approved_groups()
        sent = 0
        for chat_id, title, _ in groups:
            try:
                await context.bot.send_message(chat_id, f"🔥 Viral Link!\n{link}\nShared by @{update.effective_user.username or 'user'}")
                sent += 1
            except:
                pass
        await update.message.reply_text(f"✅ Shared to {sent} groups! Remaining shares: {user[2] - 1}")
    else:
        await update.message.reply_text("❌ Failed to use share.")

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT id, name, price FROM packages")
    packages = c.fetchall()
    conn.close()
    msg = "💳 *Choose a Package:*\n"
    for pid, name, price in packages:
        msg += f"/pay {price} 2547XXXXXXXX → {name} (KES {price})\n"
    msg += "\nExample: `/pay 254712345678 50`"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("UsageId: /pay <phone> <amount>\nExample: /pay 254712345678 50")
        return
    phone = context.args[0]
    if not phone.startswith("254") or len(phone) != 12:
        await update.message.reply_text("📱 Please use format: 2547XXXXXXXX")
        return
    try:
        amount = int(context.args[1])
    except:
        await update.message.reply_text("🔢 Amount must be a number (20, 50, or 100).")
        return
    if amount not in [20, 50, 100]:
        await update.message.reply_text("⚠️ Only KES 20, 50, or 100 allowed.")
        return
    resp = initiate_stk_push(phone, amount, str(update.effective_user.id))
    if "CheckoutRequestID" in resp:
        await update.message.reply_text(f"📲 STK Push sent for KES {amount}. Complete payment on your phone!")
    else:
        await update.message.reply_text("❌ Failed to send STK. Check MPESA credentials.")

# ---------------- ADMIN COMMANDS ----------------
async def listgroups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    groups = get_approved_groups()
    if not groups:
        await update.message.reply_text("No registered groups.")
        return
    msg = "📋 *Registered Groups:*\n"
    for chat_id, title, username in groups:
        msg += f"- {title} (@{username or 'private'}) [ID: {chat_id}]\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def register_group_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("Use this command in a group.")
        return
    chat = update.effective_chat
    register_group(chat.id, chat.title, chat.username, update.effective_user.id)
    await update.message.reply_text("✅ Group registered for auto-broadcast!")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT SUM(promotions_used) FROM users")
    promos = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*), SUM(amount) FROM payments WHERE status = 'verified'")
    payments, revenue = c.fetchone()
    conn.close()
    msg = (
        f"📊 *Admin Stats*\n"
        f"Users: {users}\n"
        f"Total Promotions Used: {promos}\n"
        f"Verified Payments: {payments or 0}\n"
        f"Revenue: KES {revenue or 0}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

# ---------------- MAIN ----------------
def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("promote", promote))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("pay", pay))
    app.add_handler(CommandHandler("listgroups", listgroups))
    app.add_handler(CommandHandler("register_group", register_group_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(quiz, pattern="^quiz$"))
    app.add_handler(CallbackQueryHandler(quiz_answer, pattern="^(correct|wrong)$"))
    app.run_polling()

if __name__ == "__main__":
    init_db()
    # Start Flask in background
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=PORT, debug=False), daemon=True).start()
    print("🚀 Viral Music Super Bot is running...")
    run_bot()
