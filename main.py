# backend/main.py
import os
import sqlite3
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from aiogram import Bot, Dispatcher, types

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://frontend-nine-phi-39.vercel.app/")
DB_PATH = "finance.db"

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in .env")

# ===================== База данных =====================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Таблица операций
    c.execute("""
        CREATE TABLE IF NOT EXISTS finance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount REAL,
            description TEXT,
            category_id INTEGER,
            created_at TEXT
        );
    """)
    # Таблица настроек пользователя
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            currency TEXT DEFAULT '₽',
            start_balance REAL DEFAULT 0
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ===================== aiogram =====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("💻 Открыть Mini App", web_app=types.WebAppInfo(url=WEBAPP_URL)))
    await message.answer("Привет! Открой Mini App из меню бота или нажми кнопку.", reply_markup=kb)

async def send_message_to_user(user_id: int, text: str):
    try:
        await bot.send_message(chat_id=user_id, text=text)
    except Exception as e:
        print("send_message error:", e)

# ===================== FastAPI =====================
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://frontend-nine-phi-39.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class AddRecordRequest(BaseModel):
    user_id: int
    type: str
    amount: float
    description: str = ""
    category_id: int = None

class UpdateRecordRequest(BaseModel):
    type: str
    amount: float

def get_conn():
    return sqlite3.connect(DB_PATH)

# ====== Эндпоинты настроек пользователя ======
@app.post("/api/init_user")
async def api_init_user(data: dict = Body(...)):
    user_id = data.get("user_id")
    currency = data.get("currency", "₽")
    start_balance = float(data.get("start_balance", 0))

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO user_settings (user_id, currency, start_balance)
        VALUES (?, ?, ?)
    """, (user_id, currency, start_balance))
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/get_user")
async def api_get_user(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT currency, start_balance FROM user_settings WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"currency": row[0], "start_balance": row[1]}
    return {"currency": "₽", "start_balance": 0}

# ===== Добавить операцию =====
@app.post("/api/add")
async def api_add(record: AddRecordRequest):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO finance (user_id, type, amount, description, category_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (record.user_id, record.type, record.amount, record.description, record.category_id,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

    asyncio.create_task(send_message_to_user(record.user_id, f"✅ Добавлено: {record.type} {record.amount}"))
    return {"status": "ok"}

# ===== Список операций =====
@app.get("/api/operations")
async def get_operations(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT id, type, amount, created_at
        FROM finance
        WHERE user_id = ?
        ORDER BY datetime(created_at) DESC
    """, (user_id,))
    rows = [{"id": r[0], "type": r[1], "amount": r[2], "created_at": r[3]} for r in c.fetchall()]
    conn.close()
    return rows

# ===== Обновить операцию =====
@app.put("/api/operations/{record_id}")
async def update_operation(record_id: int, data: UpdateRecordRequest):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE finance SET type = ?, amount = ? WHERE id = ?", (data.type, data.amount, record_id))
    conn.commit()
    conn.close()
    return {"success": True}

# ===== Отчёты =====
@app.get("/api/report")
async def api_report(period: str = "day", user_id: int = None):
    now = datetime.now()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = now.strftime("%d.%m.%Y")
    elif period == "week":
        start = now - timedelta(days=7)
        label = f"{(now - timedelta(days=7)).strftime('%d.%m.%Y')} — {now.strftime('%d.%m.%Y')}"
    elif period == "month":
        start = now - timedelta(days=30)
        label = f"{(now - timedelta(days=30)).strftime('%d.%m.%Y')} — {now.strftime('%d.%m.%Y')}"
    else:
        start = now - timedelta(days=365)
        label = f"{(now - timedelta(days=365)).strftime('%d.%m.%Y')} — {now.strftime('%d.%m.%Y')}"
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT type, SUM(amount)
        FROM finance
        WHERE user_id = ? AND datetime(created_at) BETWEEN ? AND ?
        GROUP BY type
    """, (user_id, start.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d %H:%M:%S")))
    rows = c.fetchall()

    # Получаем стартовый баланс пользователя
    c.execute("SELECT start_balance FROM user_settings WHERE user_id = ?", (user_id,))
    start_balance_row = c.fetchone()
    start_balance = start_balance_row[0] if start_balance_row else 0

    conn.close()

    income = sum(r[1] for r in rows if r[0] == "income")
    expense = sum(r[1] for r in rows if r[0] == "expense")
    balance = start_balance + (income or 0) - (expense or 0)

    return {
        "period_label": label,
        "income": income or 0.0,
        "expense": expense or 0.0,
        "balance": balance,
        "start_balance": start_balance,
        "data": rows
    }

@app.get("/api/records")
async def api_records(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, type, amount, created_at FROM finance WHERE user_id = ? ORDER BY datetime(created_at) DESC LIMIT 50", (user_id,))
    rows = [{"id": r[0], "type": r[1], "amount": r[2], "created_at": r[3]} for r in c.fetchall()]
    conn.close()
    return rows

@app.put("/api/update/{record_id}")
async def api_update(record_id: int, data: dict):
    conn = get_conn()
    c = conn.cursor()
    c.execute("UPDATE finance SET amount = ? WHERE id = ?", (data["amount"], record_id))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/health")
async def health():
    return {"status": "ok"}

# ===== Запуск =====
if __name__ == "__main__":
    import uvicorn
    loop = asyncio.get_event_loop()
    loop.create_task(dp.start_polling())
    uvicorn.run(app, host="0.0.0.0", port=8000)
