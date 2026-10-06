# ==========================================
# AUTO INSTALL REQUIRED PACKAGES (Replit/Nix compatible)
# ==========================================
import sys
import subprocess
import importlib.util

REQUIRED_PACKAGES = {
    "qrcode": "qrcode[pil]",
    "aiohttp": "aiohttp",
    "aiogram": "aiogram",
    "PIL": "Pillow",
}

def install_missing_packages():
    for module, package in REQUIRED_PACKAGES.items():
        if importlib.util.find_spec(module) is None:
            print(f"📦 Installing {package}...")
            try:
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install",
                    "--break-system-packages", package
                ])
            except subprocess.CalledProcessError:
                print(f"❌ Failed to install {package}")
                raise

install_missing_packages()
print("✅ Required packages are ready")

import qrcode
from io import BytesIO
from aiogram.types import BufferedInputFile
import asyncio
import sqlite3
import random
import logging
import time
import aiohttp
import hmac
import hashlib
import urllib.parse
import json
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
                           InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message)

# ==========================================
# 1. CONFIGURATION 
# ==========================================
BOT_TOKEN = "8934805689:AAH3Tc7XlhJyeJ3uTHzILs_mhG444wHP8Mo"
BOT_USERNAME = "@BikramXstorebot"
ADMIN_ID = 8829459097
ADMIN_CONTACT = "Rupamcoderx"

FAMGATEWAY_API_KEY = "fam_663c8ddc791e71e5d9e222c0a3d81ca01e306472"
USDT_TO_INR = 90.0

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

def fmt_curr(amount):
    return f"₹{amount:.2f}"

# ==========================================
# 2. DATABASE ARCHITECTURE
# ==========================================
def init_db():
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, 
        phone TEXT, 
        first_name TEXT, 
        balance REAL DEFAULT 0.0, 
        orders_count INTEGER DEFAULT 0, 
        spent REAL DEFAULT 0.0, 
        joined_date TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        category TEXT, 
        name TEXT, 
        price_inr REAL, 
        stock INTEGER, 
        apk_link TEXT, 
        validity TEXT DEFAULT 'Lifetime', 
        device_limit TEXT DEFAULT '1 Device'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS product_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        product_id INTEGER, 
        key_text TEXT, 
        is_used INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id INTEGER, 
        product_name TEXT, 
        price_paid REAL, 
        delivered_key TEXT, 
        purchase_date TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        user_id INTEGER, 
        message TEXT, 
        status TEXT DEFAULT 'Open'
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY, 
        value TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS coupons (
        code TEXT PRIMARY KEY, 
        amount REAL, 
        uses_left INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS redeemed (
        user_id INTEGER, 
        code TEXT,
        PRIMARY KEY (user_id, code)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
        order_id TEXT PRIMARY KEY, 
        user_id INTEGER, 
        amount_inr REAL, 
        status TEXT, 
        timestamp INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS crypto_txns (
        txid TEXT PRIMARY KEY, 
        user_id INTEGER, 
        amount_usdt REAL, 
        timestamp INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount REAL,
        screenshot_file_id TEXT,
        status TEXT DEFAULT 'pending',
        timestamp INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS famgateway_orders (
        order_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        status TEXT DEFAULT 'pending',
        utr TEXT,
        transaction_id TEXT,
        sender_name TEXT,
        created_at INTEGER NOT NULL,
        paid_at INTEGER,
        credited INTEGER DEFAULT 0
    )''')
    conn.commit()
    conn.close()

def db_query(query, params=(), fetchone=False, fetchall=False, commit=True):
    conn = sqlite3.connect('store.db')
    c = conn.cursor()
    c.execute(query, params)
    res = c.fetchone() if fetchone else c.fetchall() if fetchall else None
    if commit: conn.commit()
    conn.close()
    return res

# ==========================================
# 3. MAINTENANCE MIDDLEWARE
# ==========================================
class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if event.from_user.id == ADMIN_ID:
            return await handler(event, data)
        status_check = db_query("SELECT value FROM settings WHERE key='bot_status'", fetchone=True)
        status = status_check[0] if status_check else 'ON'
        if status == 'OFF':
            msg = "⚠️ <b>Store Maintenance</b>\n\nThe store is currently offline for updates. Please check back later!"
            if isinstance(event, Message): await event.answer(msg)
            elif isinstance(event, CallbackQuery): await event.answer("⚠️ Bot is currently OFF.", show_alert=True)
            return
        return await handler(event, data)

dp.message.middleware(MaintenanceMiddleware())
dp.callback_query.middleware(MaintenanceMiddleware())

# ==========================================
# 4. FSM STATES
# ==========================================
class UserStates(StatesGroup):
    wait_for_ticket = State()
    wait_for_redeem = State()
    wait_for_custom_amount = State()
    wait_for_crypto_txid = State() 
    wait_for_payment_screenshot = State()

class AdminStates(StatesGroup):
    add_prod_category = State()
    add_prod_name = State()
    add_prod_validity = State() 
    add_prod_device_limit = State() 
    add_prod_price = State()
    add_prod_apk = State()
    add_prod_keys = State()
    edit_prod_field = State()
    wait_for_new_value = State()
    wait_for_add_keys = State()
    broadcast_msg = State()
    add_coupon_code = State()
    add_coupon_amount = State()
    add_coupon_uses = State()
    wait_for_upi_id = State()
    wait_for_binance_api = State()
    wait_for_binance_secret = State()
    wait_for_binance_address = State()
    ticket_reply_msg = State()
    wait_for_delete_key = State()

# ==========================================
# 5. KEYBOARDS
# ==========================================
def contact_kb(): 
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Tap here to verify contact", request_contact=True)]],
        resize_keyboard=True, 
        one_time_keyboard=True
    )

def main_menu_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 Buy Key", callback_data="menu_shop")],
            [
                InlineKeyboardButton(text="🧾 My Orders", callback_data="menu_orders"),
                InlineKeyboardButton(text="👑 Profile", callback_data="menu_profile")
            ],
            [
                InlineKeyboardButton(text="💳 Add Balance", callback_data="menu_add_balance"),
                InlineKeyboardButton(text="🔑 Tutorial", callback_data="menu_how_to")
            ],
            [
                InlineKeyboardButton(text="📥 Check Update", callback_data="menu_Update"),
                InlineKeyboardButton(text="🌹 Selling Proof", callback_data="menu_Feed")
            ],
            [
                InlineKeyboardButton(text="💬 Support Center", callback_data="menu_support")
            ]
        ]
    )

def back_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="« Back to Menu", callback_data="back_main")]
        ]
    )

def admin_kb():
    status = db_query("SELECT value FROM settings WHERE key='bot_status'", fetchone=True)
    status_val = status[0] if status else 'ON'
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Product", callback_data="admin_add_prod"), 
         InlineKeyboardButton(text="📦 Manage Products", callback_data="admin_manage_prods")], 
        [InlineKeyboardButton(text="🎟 Create Coupon", callback_data="admin_create_coupon"), 
         InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast_btn")], 
        [InlineKeyboardButton(text="🎫 View Tickets", callback_data="admin_view_tickets")],
        [InlineKeyboardButton(text="💳 FamGateway Status", callback_data="admin_famgateway_status"), 
         InlineKeyboardButton(text="🪙 Binance Setup", callback_data="admin_setup_binance")], 
        [InlineKeyboardButton(text=f"{'🟢' if status_val == 'ON' else '🔴'} Bot Status: {status_val}", 
                               callback_data="admin_toggle_bot")]
    ])

def admin_back_kb(): 
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Back to Admin", callback_data="admin_panel_back")]])

# ==========================================
# 6. ADVANCED NOTIFICATION SYSTEM
# ==========================================
async def send_advanced_notification(user_id, notif_type, amount, product=None, key=None, gateway="UPI"):
    user_info = db_query("SELECT first_name, phone FROM users WHERE user_id=?", (user_id,), fetchone=True)
    name = user_info[0] if user_info else "Unknown"
    phone = user_info[1] if user_info and user_info[1] else "Not Provided"

    try:
        chat = await bot.get_chat(user_id)
        username = f"@{chat.username}" if chat.username else "None"
    except:
        username = "None"

    time_now = datetime.now().strftime("%d-%m-%Y %I:%M %p")

    if notif_type == "ORDER":
        title = "🛒 NEW ORDER! 🛒"
        details = f"📦 Product: {product}\n🔑 Key: <code>{key}</code>\n💰 Amount: ₹{amount}\n📅 Time: {time_now}"
    else:
        title = "💰 NEW DEPOSIT! 💰"
        details = f"💵 Amount Added: ₹{amount}\n🧾 Gateway: {gateway}\n🆔 Reference: <code>{product}</code>\n📅 Time: {time_now}"

    msg = (
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 Name: {name}\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"📱 Phone: {phone}\n"
        f"👤 Username: {username}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{details}"
    )
    try:
        await bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        logging.error(f"Failed to send notif: {e}")

async def send_stock_alert(prod_id, prod_category, prod_name, user_id):
    user_info = db_query("SELECT first_name, phone FROM users WHERE user_id=?", (user_id,), fetchone=True)
    name = user_info[0] if user_info else "Unknown"
    phone = user_info[1] if user_info and user_info[1] else "Not Provided"

    try:
        chat = await bot.get_chat(user_id)
        username = f"@{chat.username}" if chat.username else "None"
    except:
        username = "None"

    msg = (
        f"🚨 <b>⚠️ PRODUCT OUT OF STOCK ⚠️</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Product:</b> {prod_category} ({prod_name})\n"
        f"🆔 <b>Product ID:</b> <code>{prod_id}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Buyer:</b> {name}\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"📱 <b>Phone:</b> {phone}\n"
        f"👤 <b>Username:</b> {username}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⏰ <b>Time:</b> {datetime.now().strftime('%d-%m-%Y %I:%M %p')}"
    )
    try:
        await bot.send_message(ADMIN_ID, msg)
    except Exception as e:
        logging.error(f"Failed to send stock alert: {e}")

# ==========================================
# 9. ONBOARDING & DEEP LINK INTERCEPT
# ==========================================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = db_query("SELECT phone FROM users WHERE user_id=?", (message.from_user.id,), fetchone=True)
    if not user or not user[0]:
        db_query("INSERT OR IGNORE INTO users (user_id, first_name, joined_date) VALUES (?, ?, ?)", 
                 (message.from_user.id, message.from_user.first_name or "User", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        await message.answer("<b>🛡 VERIFICATION REQUIRED</b>\n\nTo safeguard your orders, we need to verify your account.\n👇 <b>Tap the button below:</b>", reply_markup=contact_kb())
    else:
        await send_main_menu(message)

@dp.message(F.contact)
async def handle_contact(message: Message):
    if message.contact.user_id == message.from_user.id:
        db_query("UPDATE users SET phone=? WHERE user_id=?", (message.contact.phone_number, message.from_user.id))
        await message.answer("✅ Verification successful!", reply_markup=ReplyKeyboardRemove())
        await send_main_menu(message)
    else:
        await message.answer("❌ Please share your own contact.")

async def send_main_menu(ctx):
    user_id = ctx.from_user.id
    first_name = ctx.from_user.first_name or "User"

    user_data = db_query("SELECT balance FROM users WHERE user_id=?", (user_id,), fetchone=True)
    balance = user_data[0] if user_data else 0.0

    text = (f"👋 Welcome, <b>{first_name}!</b>\n\n"
            f"⭐ <b>— 𝗥𝗣𝗭 𝗣𝗔𝗡𝗘𝗟 𝗦𝗛𝗢𝗣 —</b>⭐\n\n"
            f"🔑 Premium Game Keys & Panels\n"
            f"⚡ Instant Auto Delivery 24×7\n"
            f"🔒 100% Secure & Trusted Store\n"
            f"💎 Best Prices Guaranteed\n"
            f"🎁 Daily Rewards & Special Offers\n"
            f"☎️ 24/7 Live Support Available\n"
            f"🌹 Trusted by 2000+ of Users\n\n"
            f"👤 <b>User ID:</b> <code>{user_id}</code>\n"
            f"💰 <b>Your Balance:</b> {fmt_curr(balance)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <b>Tap Shop Now to Start!</b>")

    if isinstance(ctx, Message):
        await ctx.answer(text, reply_markup=main_menu_kb())
    else:
        await ctx.message.edit_text(text, reply_markup=main_menu_kb())

@dp.callback_query(F.data == "back_main")
async def back_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await send_main_menu(call)

# ==========================================
# 10. DUAL PAYMENT GATEWAY SYSTEM
# ==========================================
@dp.callback_query(F.data == "menu_add_balance")
async def select_gateway_menu(call: CallbackQuery):
    bal_row = db_query("SELECT balance FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)
    bal = bal_row[0] if bal_row else 0.0
    text = (
    f"✨ <b>ADD BALANCE</b> ✨\n\n"
    f"💳 <b>Current Balance:</b> {fmt_curr(bal)}\n\n"
    "✨ Select Your Preferred Payment Method.\n\n"
    "┣ 💵 <b>UPI</b> — Fast Indian Payments\n"
    "┗ 🪙 <b>Binance</b> — USDT Payments\n\n"
    "✨ Payments are verified securely."
)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 UPI (Auto)", callback_data="gateway_inr")],
        [InlineKeyboardButton(text="🪙 Binance (USDT)", callback_data="gateway_crypto")],
        [InlineKeyboardButton(text="« Back to Menu", callback_data="back_main")]
    ])
    await call.message.edit_text(text, reply_markup=kb)# ---- FAMGATEWAY AUTOMATIC UPI FLOW ----
FAMGATEWAY_BASE_URL = "https://famgateway.in"


async def famgateway_create_order(user_id: int, amount: float):
    if not FAMGATEWAY_API_KEY or FAMGATEWAY_API_KEY == "PASTE_YOUR_FAMGATEWAY_API_KEY_HERE":
        raise RuntimeError("FamGateway API key is not configured")

    user = db_query(
        "SELECT first_name FROM users WHERE user_id=?",
        (user_id,),
        fetchone=True
    )
    customer_name = user[0] if user and user[0] else f"Telegram User {user_id}"

    payload = {
        "amount": round(float(amount), 2),
        "customer_name": customer_name,
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-Api-Key": FAMGATEWAY_API_KEY,
    }

    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(
            f"{FAMGATEWAY_BASE_URL}/api/create-order",
            json=payload,
            headers=headers
        ) as resp:
            raw = await resp.text()
            try:
                data = json.loads(raw)
            except Exception:
                data = {}

            if resp.status != 200 or data.get("status") != "success":
                detail = data.get("message") or data.get("error") or raw[:300]
                raise RuntimeError(f"FamGateway order creation failed ({resp.status}): {detail}")

            order = data.get("data") or {}
            required = ("order_id", "payable_amount", "qr_url", "checkout_url")
            missing = [key for key in required if not order.get(key)]
            if missing:
                raise RuntimeError(f"FamGateway response missing: {', '.join(missing)}")

            return order


async def famgateway_get_status(order_id: str):
    if not FAMGATEWAY_API_KEY or FAMGATEWAY_API_KEY == "PASTE_YOUR_FAMGATEWAY_API_KEY_HERE":
        raise RuntimeError("FamGateway API key is not configured")

    headers = {
        "Accept": "application/json",
        "X-Api-Key": FAMGATEWAY_API_KEY,
    }
    params = {"order_id": order_id}
    timeout = aiohttp.ClientTimeout(total=15)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            f"{FAMGATEWAY_BASE_URL}/api/verify-order.php",
            params=params,
            headers=headers
        ) as resp:
            raw = await resp.text()
            try:
                data = json.loads(raw)
            except Exception:
                data = {}

            if resp.status != 200:
                raise RuntimeError(f"FamGateway verification failed ({resp.status}): {raw[:300]}")

            lifecycle = data.get("status")
            details = data.get("data") or {}

            if lifecycle in ("success", "pending", "expired"):
                details.setdefault("status", lifecycle)

            return details


def credit_famgateway_order_once(order_id: str, verified: dict):
    conn = sqlite3.connect("store.db")
    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """SELECT user_id, amount, credited, status
               FROM famgateway_orders WHERE order_id=?""",
            (order_id,)
        ).fetchone()

        if not row:
            conn.rollback()
            return None

        user_id, expected_amount, credited, current_status = row

        if credited:
            conn.commit()
            return {
                "credited": False,
                "already_credited": True,
                "user_id": user_id,
                "amount": expected_amount,
            }

        paid_amount = float(verified.get("amount") or expected_amount)
        if round(paid_amount, 2) != round(float(expected_amount), 2):
            conn.execute(
                "UPDATE famgateway_orders SET status='amount_mismatch' WHERE order_id=?",
                (order_id,)
            )
            conn.commit()
            logging.error(
                "FamGateway amount mismatch: order=%s expected=%s received=%s",
                order_id, expected_amount, paid_amount
            )
            return {
                "credited": False,
                "amount_mismatch": True,
                "user_id": user_id,
                "amount": expected_amount,
            }

        utr = verified.get("utr")
        transaction_id = verified.get("transaction_id")
        sender_name = verified.get("sender_name")
        paid_at = int(time.time())

        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id=?",
            (expected_amount, user_id)
        )

        conn.execute(
            """UPDATE famgateway_orders
               SET status='success', utr=?, transaction_id=?, sender_name=?,
                   paid_at=?, credited=1
               WHERE order_id=?""",
            (utr, transaction_id, sender_name, paid_at, order_id)
        )

        conn.commit()
        return {
            "credited": True,
            "already_credited": False,
            "user_id": user_id,
            "amount": float(expected_amount),
            "utr": utr,
            "transaction_id": transaction_id,
            "sender_name": sender_name,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def monitor_famgateway_order(
    order_id: str,
    user_id: int,
    amount: float,
    qr_message_id: int | None = None,
):
    for _ in range(100):  # ~5 minutes
        await asyncio.sleep(3)

        try:
            status = await famgateway_get_status(order_id)
            lifecycle = status.get("status")

            if lifecycle == "success" or status.get("is_paid") is True:
                result = credit_famgateway_order_once(order_id, status)

                if result and result.get("credited"):
                    if qr_message_id:
                        try:
                            await bot.delete_message(user_id, qr_message_id)
                        except Exception:
                            pass

                    utr_text = result.get("utr") or "Not returned"
                    await bot.send_message(
                        user_id,
                        f"🎉 <b>PAYMENT VERIFIED AUTOMATICALLY!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"💰 <b>Amount:</b> {fmt_curr(result['amount'])}\n"
                        f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n"
                        f"🧾 <b>UTR:</b> <code>{utr_text}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"✅ Your balance has been updated instantly.",
                        reply_markup=main_menu_kb()
                    )

                    await send_advanced_notification(
                        user_id, "DEPOSIT", result["amount"],
                        product=order_id, gateway="FamGateway UPI"
                    )

                elif result and result.get("amount_mismatch"):
                    if qr_message_id:
                        try:
                            await bot.delete_message(user_id, qr_message_id)
                        except Exception:
                            pass
                    await bot.send_message(
                        user_id,
                        "⚠️ <b>Payment detected but the amount did not match this order.</b>\n\n"
                        "Please contact Admin with your Order ID:\n"
                        f"<code>{order_id}</code>",
                        reply_markup=main_menu_kb()
                    )
                return

            if lifecycle == "expired":
                db_query(
                    "UPDATE famgateway_orders SET status='expired' WHERE order_id=? AND credited=0",
                    (order_id,)
                )
                if qr_message_id:
                    try:
                        await bot.delete_message(user_id, qr_message_id)
                    except Exception:
                        pass
                await bot.send_message(
                    user_id,
                    f"⌛ <b>PAYMENT SESSION EXPIRED</b>\n\n"
                    f"Order <code>{order_id}</code> was not paid within the gateway's payment window.\n"
                    f"Please create a new payment order.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💳 Add Balance", callback_data="menu_add_balance")],
                        [InlineKeyboardButton(text="« Back to Menu", callback_data="back_main")]
                    ])
                )
                return

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.warning("FamGateway polling error for %s: %s", order_id, e)

    db_query(
        "UPDATE famgateway_orders SET status='expired' WHERE order_id=? AND credited=0",
        (order_id,)
    )
    if qr_message_id:
        try:
            await bot.delete_message(user_id, qr_message_id)
        except Exception:
            pass
    try:
        await bot.send_message(
            user_id,
            "⌛ <b>PAYMENT SESSION ENDED</b>\n\nPlease create a new payment order if you still want to add balance.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 Add Balance", callback_data="menu_add_balance")],
                [InlineKeyboardButton(text="« Back to Menu", callback_data="back_main")]
            ])
        )
    except Exception:
        pass


@dp.callback_query(F.data == "gateway_inr")
async def add_balance_inr(call: CallbackQuery):
    if not FAMGATEWAY_API_KEY or FAMGATEWAY_API_KEY == "PASTE_YOUR_FAMGATEWAY_API_KEY_HERE":
        return await call.message.edit_text(
            "⚠️ <b>UPI payments are temporarily unavailable.</b>\n\n"
            "FamGateway API key is not configured on the server.",
            reply_markup=back_kb()
        )

    text = "💵 <b>ADD BALANCE VIA UPI</b> 💵\n\nSelect Amount:"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="₹10", callback_data="pay_10"),
            InlineKeyboardButton(text="₹50", callback_data="pay_50")
        ],
        [
            InlineKeyboardButton(text="₹100", callback_data="pay_100"),
            InlineKeyboardButton(text="₹300", callback_data="pay_300")
        ],
        [InlineKeyboardButton(text="✏️ Enter Custom Amount", callback_data="custom_deposit_btn")],
        [InlineKeyboardButton(text="« Back", callback_data="menu_add_balance")]
    ])
    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "custom_deposit_btn")
async def custom_deposit_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "💰 <b>Custom Deposit</b>\n\n"
        "Please enter the amount in INR:\n"
        "⚠️ <i>Minimum ₹10 is required.</i>",
        reply_markup=back_kb()
    )
    await state.set_state(UserStates.wait_for_custom_amount)


@dp.message(UserStates.wait_for_custom_amount)
async def process_custom_amount(m: Message, state: FSMContext):
    try:
        inr_amount = float(m.text.strip())
        if inr_amount < 10:
            return await m.answer("❌ You must add at least <b>₹10</b>.")
        if inr_amount > 100000:
            return await m.answer("❌ Maximum payment amount is ₹100000.")
        if not inr_amount.is_integer():
            return await m.answer("❌ Please enter a whole INR amount.")
        await state.clear()
        await create_famgateway_payment(m.from_user.id, float(inr_amount), m)
    except ValueError:
        await m.answer("❌ Please type a valid amount.")


@dp.callback_query(F.data.startswith("pay_"))
async def process_amount_selected(call: CallbackQuery):
    inr_amount = float(call.data.split("_")[1])
    await call.answer()
    await create_famgateway_payment(call.from_user.id, inr_amount, call.message)


async def create_famgateway_payment(user_id: int, amount: float, message_obj: Message):
    try:
        order = await famgateway_create_order(user_id, amount)
    except Exception as e:
        logging.exception("FamGateway order creation failed")
        error_text = (
            "❌ <b>Could not create payment order.</b>\n\n"
            "Please try again in a moment."
        )
        logging.error("FamGateway create-order error: %s", e)

        if isinstance(message_obj, Message):
            try:
                await message_obj.edit_text(error_text, reply_markup=back_kb())
            except Exception:
                await message_obj.answer(error_text, reply_markup=back_kb())
        return

    order_id = order["order_id"]
    payable_amount = float(order.get("payable_amount") or amount)
    qr_url = order["qr_url"]
    checkout_url = order["checkout_url"]

    db_query(
        """INSERT INTO famgateway_orders
           (order_id, user_id, amount, status, created_at)
           VALUES (?, ?, ?, 'pending', ?)""",
        (order_id, user_id, payable_amount, int(time.time()))
    )

    text = (
        f"💳 <b>UPI PAYMENT</b>\n\n"
        f"💰 <b>Amount:</b> {fmt_curr(payable_amount)}\n"
        f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n\n"
        f"📲 Scan the QR below or tap <b>Pay Now</b>.\n"
        f"⏳ Payment session is valid for about 5 minutes.\n\n"
        f"✅ After you pay, <b>do nothing</b> — payment will be verified automatically."
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pay Now", url=checkout_url)],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="menu_add_balance")]
    ])

    try:
        await message_obj.delete()
    except Exception:
        pass

    try:
        sent = await bot.send_photo(
            user_id,
            photo=qr_url,
            caption=text,
            reply_markup=kb
        )
    except Exception:
        sent = await bot.send_message(user_id, text, reply_markup=kb)

    asyncio.create_task(
        monitor_famgateway_order(
            order_id=order_id,
            user_id=user_id,
            amount=payable_amount,
            qr_message_id=sent.message_id
        )
    )


async def recover_pending_famgateway_orders():
    rows = db_query(
        """SELECT order_id, user_id, amount
           FROM famgateway_orders
           WHERE status='pending' AND credited=0
           ORDER BY created_at DESC LIMIT 50""",
        fetchall=True
    )

    for order_id, user_id, amount in rows:
        asyncio.create_task(
            monitor_famgateway_order(order_id, user_id, amount)
        )


@dp.message(Command("cancel"))
async def cancel_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("✅ Cancelled.", reply_markup=main_menu_kb())


# ---- BINANCE CRYPTO FLOW ----
@dp.callback_query(F.data == "gateway_crypto")
async def add_balance_crypto(call: CallbackQuery, state: FSMContext):
    address_check = db_query("SELECT value FROM settings WHERE key='binance_address'", fetchone=True)
    if not address_check or not address_check[0]:
        return await call.message.edit_text("⚠️ Binance Gateway is currently offline. Admin has not set a deposit address.", reply_markup=back_kb())

    deposit_address = address_check[0]

    msg = (f"🪙 <b>— BINANCE USDT DEPOSIT —</b> 🪙\n\n"
           f"💵 <b>Exchange Rate:</b> 1 USDT = ₹{USDT_TO_INR}\n"
           f"⚠️ <b>Network:</b> Please send via <b>TRC20</b> or <b>BEP20</b>.\n\n"
           f"👇 <b>Send your USDT to this exact address:</b>\n"
           f"<code>{deposit_address}</code>\n\n"
           f"━━━━━━━━━━━━━━━━━━\n"
           f"✅ <b>After sending the USDT, reply to this message with your exact TxID (Transaction Hash) to instantly claim your balance.</b>\n\n"
           f"<i>Type /cancel to abort.</i>")

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="« Cancel", callback_data="menu_add_balance")]])
    await call.message.edit_text(msg, reply_markup=kb)
    await state.set_state(UserStates.wait_for_crypto_txid)


@dp.message(UserStates.wait_for_crypto_txid)
async def process_crypto_txid(m: Message, state: FSMContext):
    txid = m.text.strip()
    user_id = m.from_user.id

    if len(txid) < 10:
        return await m.answer("❌ That doesn't look like a valid TxID. Please try again or type /cancel.")

    if db_query("SELECT txid FROM crypto_txns WHERE txid=?", (txid,), fetchone=True):
        return await m.answer("⚠️ This Transaction ID has already been claimed!", reply_markup=back_kb())

    api_key_check = db_query("SELECT value FROM settings WHERE key='binance_api'", fetchone=True)
    secret_key_check = db_query("SELECT value FROM settings WHERE key='binance_secret'", fetchone=True)

    if not api_key_check or not secret_key_check:
        return await m.answer("⚠️ Binance API is missing on the server. Contact Admin.", reply_markup=back_kb())

    await m.answer("🔄 <b>Verifying your TxID with Binance Blockchain...</b>\n<i>Please wait...</i>")

    api_key = api_key_check[0]
    secret_key = secret_key_check[0]

    timestamp = int(time.time() * 1000)
    start_time = int((time.time() - 86400) * 1000)
    query_string = f"timestamp={timestamp}&startTime={start_time}"
    signature = hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

    headers = {'X-MBX-APIKEY': api_key}
    url = f"https://api.binance.com/sapi/v1/capital/deposit/hisrec?{query_string}&signature={signature}"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    history = await resp.json()
                    found = False

                    for deposit in history:
                        if deposit.get("txId") == txid and deposit.get("status") == 1:
                            found = True
                            usdt_amount = float(deposit.get("amount"))
                            inr_amount = usdt_amount * USDT_TO_INR

                            # Atomic insert to prevent race condition
                            conn = sqlite3.connect('store.db')
                            try:
                                conn.execute("BEGIN IMMEDIATE")
                                try:
                                    conn.execute("INSERT INTO crypto_txns (txid, user_id, amount_usdt, timestamp) VALUES (?, ?, ?, ?)",
                                                 (txid, user_id, usdt_amount, int(time.time())))
                                except sqlite3.IntegrityError:
                                    conn.rollback()
                                    conn.close()
                                    await m.answer("⚠️ This Transaction ID has already been claimed!", reply_markup=back_kb())
                                    await state.clear()
                                    return
                                conn.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (inr_amount, user_id))
                                conn.commit()
                            finally:
                                conn.close()

                            await m.answer(f"🎉 <b>CRYPTO DEPOSIT SUCCESSFUL!</b>\n\n✅ We received <b>{usdt_amount} USDT</b>.\n💰 <b>{fmt_curr(inr_amount)}</b> has been added to your balance!", reply_markup=main_menu_kb())

                            await send_advanced_notification(user_id, "DEPOSIT", inr_amount, product=txid, gateway="Binance Crypto")
                            await state.clear()
                            break

                    if not found:
                        await m.answer("❌ <b>TxID Not Found or Still Pending!</b>\nMake sure the transaction is fully confirmed on the blockchain and you sent it to the correct address. Try again in 2 minutes.", reply_markup=back_kb())
                else:
                    await m.answer(f"⚠️ <b>Binance Server Error:</b> HTTP {resp.status}. Please tell admin.", reply_markup=back_kb())
        except Exception as e:
            await m.answer(f"⚠️ <b>Connection Error:</b> {str(e)}", reply_markup=back_kb())


# ==========================================
# 11. SHOP & NESTED PRODUCTS UI
# ==========================================
@dp.callback_query(F.data == "menu_shop")
async def shop_categories(call: CallbackQuery):
    cats = db_query("SELECT DISTINCT category FROM products", fetchall=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if not cats:
        kb.inline_keyboard.append([InlineKeyboardButton(text="« Back", callback_data="back_main")])
        await call.message.edit_text("🛒 Store is empty.", reply_markup=kb)
        return

    text = "✨ <b>Available Products</b>\n\n💎 Premium Keys\n⚡ Instant Delivery\n🔒 Secure Payment\n\n🛒 <b>Select a product below:</b>"
    for c in cats: 
        kb.inline_keyboard.append([InlineKeyboardButton(text=f"➪ {str(c[0])}", callback_data=f"cat_{str(c[0])[:40]}")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="« Back to Menu", callback_data="back_main")])
    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("cat_"))
async def view_products(call: CallbackQuery):
    cat_sliced = call.data.split("cat_", 1)[1]
    prods = db_query("SELECT id, name, price_inr, stock FROM products WHERE category LIKE ?", (f"{cat_sliced}%",), fetchall=True)
    if not prods:
        await call.answer("❌ Durations not found.", show_alert=True)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    text = f"🎮 🛒 <b>{cat_sliced.upper()}</b>\n━━━━━━━━━━━━━━━━━━\n\n"

    for p in prods:
        prod_id, duration_name, price_inr, stock = p
        price_usd = price_inr / 90.0  
        stock_status = "✅ In Stock" if stock > 0 else "❌ Out of Stock"

        text += f"⏱ <b>{duration_name}</b>\n💰 ${price_usd:.2f} ({fmt_curr(price_inr)})\n📦 {stock_status}\n\n"

        if stock > 0:
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"📦 Buy {duration_name} - ${price_usd:.2f} ({fmt_curr(price_inr)})", callback_data=f"buy_{prod_id}")])
        else:
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"❌ {duration_name} (Out of Stock)", callback_data="ignore_stock_click")])

    text += "👇 <b>Select duration below:</b>"
    kb.inline_keyboard.append([InlineKeyboardButton(text="« Back to Shop", callback_data="menu_shop")])
    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "ignore_stock_click")
async def ignore_stock_click(call: CallbackQuery):
    await call.answer("⚠️ This duration is Out of Stock!", show_alert=True)


@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(call: CallbackQuery):
    prod_id = int(call.data.split("_")[1])
    prod = db_query("SELECT name, price_inr, stock, apk_link, validity, device_limit, category FROM products WHERE id=?", (prod_id,), fetchone=True)
    user = db_query("SELECT balance FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)

    if not prod: return await call.answer("❌ Item not found!", show_alert=True)

    if user[0] < prod[1]:
        insufficient_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Add Balance", callback_data="menu_add_balance")],
            [InlineKeyboardButton(text="« Back to Shop", callback_data="menu_shop")]
        ])
        await call.message.edit_text(
            f"❌ <b>Insufficient Balance!</b>\n\n"
            f"You need {fmt_curr(prod[1])} to buy this product.\n"
            f"Your current balance: {fmt_curr(user[0])}\n\n"
            f"👉 Please add balance to continue.",
            reply_markup=insufficient_kb
        )
        return

    # Atomic key delivery
    conn = sqlite3.connect('store.db')
    delivered_key = "OUT_OF_STOCK_CONTACT_ADMIN"
    key_acquired = False
    try:
        conn.execute("BEGIN IMMEDIATE")

        bal_row = conn.execute("SELECT balance FROM users WHERE user_id=?", (call.from_user.id,)).fetchone()
        if not bal_row or bal_row[0] < prod[1]:
            conn.rollback()
            return await call.answer("❌ Insufficient balance!", show_alert=True)

        key_row = conn.execute(
            "SELECT id, key_text FROM product_keys WHERE product_id=? AND is_used=0 LIMIT 1",
            (prod_id,)
        ).fetchone()

        if key_row:
            key_id, key_text = key_row
            # Atomic mark-as-used: only succeeds if still is_used=0
            cur = conn.execute(
                "UPDATE product_keys SET is_used=1 WHERE id=? AND is_used=0",
                (key_id,)
            )
            if cur.rowcount == 1:
                delivered_key = key_text
                key_acquired = True
                conn.execute("UPDATE products SET stock=stock-1 WHERE id=?", (prod_id,))
                conn.execute(
                    "UPDATE users SET balance=balance-?, spent=spent+?, orders_count=orders_count+1 WHERE user_id=?",
                    (prod[1], prod[1], call.from_user.id)
                )
                conn.execute(
                    "INSERT INTO orders (user_id, product_name, price_paid, delivered_key, purchase_date) VALUES (?, ?, ?, ?, ?)",
                    (call.from_user.id, f"{prod[6]} ({prod[0]})", prod[1], delivered_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                )
                conn.commit()
        else:
            # No stock; still deduct balance and log
            conn.execute(
                "UPDATE users SET balance=balance-?, spent=spent+?, orders_count=orders_count+1 WHERE user_id=?",
                (prod[1], prod[1], call.from_user.id)
            )
            conn.execute(
                "INSERT INTO orders (user_id, product_name, price_paid, delivered_key, purchase_date) VALUES (?, ?, ?, ?, ?)",
                (call.from_user.id, f"{prod[6]} ({prod[0]})", prod[1], delivered_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
    except Exception as e:
        conn.rollback()
        logging.exception("Buy failed")
        return await call.answer("❌ Purchase failed. Try again.", show_alert=True)
    finally:
        conn.close()

    # Stock alert
    if key_acquired:
        new_stock = db_query("SELECT stock FROM products WHERE id=?", (prod_id,), fetchone=True)[0]
        if new_stock == 0:
            await send_stock_alert(prod_id, prod[6], prod[0], call.from_user.id)

    await send_advanced_notification(call.from_user.id, "ORDER", prod[1], product=f"{prod[6]} ({prod[0]})", key=delivered_key)

    msg = f"✅ <b>PURCHASE SUCCESSFUL!</b>\n━━━━━━━━━━━━━━━━━━\n📦 <b>Product:</b> {prod[6]} ({prod[0]})\n⏳ <b>Validity:</b> {prod[4]}\n📱 <b>Device Limit:</b> {prod[5]}\n━━━━━━━━━━━━━━━━━━\n"
    if prod[3] and prod[3].startswith("http"): msg += f"📥 <b>APK Link:</b> <a href='{prod[3]}'>Download Here</a>\n\n"

    if "OUT_OF_STOCK" in delivered_key:
        msg += f"⚠️ <b>STOCK OUT</b>\nAmount deducted, but key is out of stock. Contact Admin: {ADMIN_CONTACT}\n"
    else:
        msg += f"🔑 <b>Your Key:</b> <code>{delivered_key}</code>\n\n<i>Contact admin for issues: {ADMIN_CONTACT}</i>"

    await call.message.edit_text(msg, reply_markup=back_kb(), disable_web_page_preview=True)


# ==========================================
# 12. USER DASHBOARD & COUPONS
# ==========================================
@dp.callback_query(F.data == "menu_orders")
async def my_orders(call: CallbackQuery):
    orders = db_query("SELECT product_name, delivered_key, purchase_date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 10", (call.from_user.id,), fetchall=True)
    if not orders: return await call.message.edit_text("🧾 You haven't made any purchases yet.", reply_markup=back_kb())
    text = "🧾 <b>— YOUR RECENT ORDERS —</b> 🧾\n\n"
    for o in orders: text += f"📦 {o[0]}\n🔑 <code>{o[1]}</code>\n📅 {o[2]}\n\n"
    await call.message.edit_text(text, reply_markup=back_kb())


@dp.callback_query(F.data == "menu_profile")
async def show_profile(call: CallbackQuery):
    u = db_query("SELECT user_id, first_name, balance, orders_count, spent, joined_date FROM users WHERE user_id=?", (call.from_user.id,), fetchone=True)
    text = (f"👤 <b>— YOUR PROFILE —</b> 👤\n\n🆔 <b>User ID:</b> <code>{u[0]}</code>\n📛 <b>Name:</b> {u[1]}\n\n"
            f"💰 <b>— Balance —</b>\n💳 <b>Current:</b> {fmt_curr(u[2])}\n\n📊 <b>— Statistics —</b>\n📦 <b>Orders:</b> {u[3]}\n💸 <b>Spent:</b> {fmt_curr(u[4])}\n\n📅 <b>Joined:</b> {u[5]}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎟 Redeem Coupon", callback_data="redeem_coupon")], [InlineKeyboardButton(text="« Back to Menu", callback_data="back_main")]])
    await call.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data == "redeem_coupon")
async def redeem_coupon_start(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("🎟 <b>Please enter your redeem code below:</b>", reply_markup=back_kb())
    await state.set_state(UserStates.wait_for_redeem)


@dp.message(UserStates.wait_for_redeem)
async def process_redeem(m: Message, state: FSMContext):
    code = m.text.strip().upper()
    user_id = m.from_user.id

    conn = sqlite3.connect('store.db')
    try:
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute("SELECT 1 FROM redeemed WHERE user_id=? AND code=?", (user_id, code)).fetchone()
        if existing:
            conn.rollback()
            await m.answer("❌ You already redeemed this code!", reply_markup=main_menu_kb())
            await state.clear()
            return

        coupon = conn.execute("SELECT amount, uses_left FROM coupons WHERE code=?", (code,)).fetchone()
        if not coupon:
            conn.rollback()
            await m.answer("❌ Invalid code!", reply_markup=main_menu_kb())
            await state.clear()
            return
        if coupon[1] <= 0:
            conn.rollback()
            await m.answer("❌ Code is fully claimed.", reply_markup=main_menu_kb())
            await state.clear()
            return

        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (coupon[0], user_id))
        conn.execute("UPDATE coupons SET uses_left = uses_left - 1 WHERE code=?", (code,))
        conn.execute("INSERT INTO redeemed (user_id, code) VALUES (?, ?)", (user_id, code))
        conn.commit()

        await m.answer(f"🎉 <b>Success!</b>\nAdded {fmt_curr(coupon[0])} to your balance!", reply_markup=main_menu_kb())

        try:
            user_info = db_query("SELECT first_name FROM users WHERE user_id=?", (user_id,), fetchone=True)
            uname = user_info[0] if user_info else "Unknown User"
            await bot.send_message(ADMIN_ID, f"🎟 <b>COUPON REDEEMED!</b>\n👤 User: {uname} (<code>{user_id}</code>)\n🔖 Code: <b>{code}</b>\n💵 Amount: {fmt_curr(coupon[0])}")
        except Exception:
            pass
    except Exception:
        conn.rollback()
        await m.answer("❌ Something went wrong. Try again.", reply_markup=main_menu_kb())
    finally:
        conn.close()

    await state.clear()


@dp.callback_query(F.data == "menu_how_to")
async def how_to_buy(call: CallbackQuery):
    await call.message.edit_text(
        " 🛒<b>— HOW TO BUY KEY </b> 🛒\n\n1️⃣ Add Balance tutorial \n2️⃣ Open Product Store\n3️⃣ Select Your Panel \n4️⃣ Buy & Receive Key Instantly\n\n📺 Watch the full video",
        reply_markup=InlineKeyboard