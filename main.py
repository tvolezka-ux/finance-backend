# backend/main.py
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
import asyncio
from aiogram import Bot, Dispatcher, types
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://frontend-nine-phi-39.vercel.app/")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://finance_db_zrvy_user:p7ltpFIAhntlJwV6hpzElONWb5xWmrec@dpg-d45hl5be5dus73c5cev0-a/finance_db_zrvy")

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in .env")

# ===================== База данных =====================
def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS finance (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            type TEXT,
            amount REAL,
            description TEXT,
            category_id INTEGER,
            created_at TIMESTAMP
        );
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id BIGINT PRIMARY KEY,
            currency TEXT DEFAULT '₽',
            start_balance REAL DEFAULT 0
        );
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name TEXT
        );
    """)
    conn.commit()
    c.close()
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
    description: str = ""
    category_id: int = None

# ====== Эндпоинты пользователя ======
@app.post("/api/init_user")
async def api_init_user(data: dict = Body(...)):
    user_id = data.get("user_id")
    currency = data.get("currency", "₽")
    start_balance = float(data.get("start_balance", 0))

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO user_settings (user_id, currency, start_balance)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET currency = EXCLUDED.currency, start_balance = EXCLUDED.start_balance
    """, (user_id, currency, start_balance))
    conn.commit()
    c.close()
    conn.close()
    return {"status": "ok"}

@app.get("/api/get_user")
async def api_get_user(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT currency, start_balance FROM user_settings WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    c.close()
    conn.close()
    if row:
        return {"currency": row["currency"], "start_balance": row["start_balance"]}
    return {"currency": "₽", "start_balance": 0}

# ===== Категории =====
@app.get("/api/categories")
async def api_categories():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, name FROM categories")
    rows = c.fetchall()
    c.close()
    conn.close()
    return [{"id": r["id"], "name": r["name"]} for r in rows]

@app.post("/api/add_category")
async def api_add_category(name: str = Body(..., embed=True)):
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO categories (name) VALUES (%s)", (name,))
    conn.commit()
    c.close()
    conn.close()
    return {"status": "ok"}

# ===== Добавить операцию =====
@app.post("/api/add")
async def api_add(record: AddRecordRequest):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO finance (user_id, type, amount, description, category_id, created_at)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (record.user_id, record.type, record.amount, record.description, record.category_id,
          datetime.now()))
    conn.commit()
    c.close()
    conn.close()

    asyncio.create_task(send_message_to_user(record.user_id, f"✅ {record.type.capitalize()} {record.amount}"))
    return {"status": "ok"}

# ===== Список операций =====
@app.get("/api/records")
async def api_records(user_id: int):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT f.id, f.type, f.amount, f.description, f.category_id, f.created_at, c.name AS category_name
        FROM finance f
        LEFT JOIN categories c ON f.category_id = c.id
        WHERE f.user_id = %s
        ORDER BY f.created_at DESC LIMIT 50
    """, (user_id,))
    rows = c.fetchall()
    c.close()
    conn.close()
    return rows

# ===== Обновить операцию =====
@app.put("/api/update/{record_id}")
async def api_update(record_id: int, data: UpdateRecordRequest):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE finance
        SET type = %s, amount = %s, description = %s, category_id = %s
        WHERE id = %s
    """, (data.type, data.amount, data.description, data.category_id, record_id))
    conn.commit()
    c.close()
    conn.close()
    return {"status": "ok"}

# ===== Отчёты =====
@app.get("/api/report")
async def api_report(period: str = "day", user_id: int = None):
    now = datetime.now()
    if period == "day":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = now.strftime("%d.%m.%Y")
    elif period == "week":
        start = now - timedelta(days=7)
        label = f"{(now - timedelta(days=7)).strftime('%d.%m')} — {now.strftime('%d.%m')}"
    elif period == "month":
        start = now - timedelta(days=30)
        label = f"{(now - timedelta(days=30)).strftime('%d.%m')} — {now.strftime('%d.%m')}"
    else:
        start = now - timedelta(days=365)
        label = f"{(now - timedelta(days=365)).strftime('%d.%m.%Y')} — {now.strftime('%d.%m.%Y')}"

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT type, SUM(amount) AS total
        FROM finance
        WHERE user_id = %s AND created_at BETWEEN %s AND %s
        GROUP BY type
    """, (user_id, start, now))
    rows = c.fetchall()

    income = sum(r["total"] for r in rows if r["type"] == "income")
    expense = sum(r["total"] for r in rows if r["type"] == "expense")

    c.execute("SELECT start_balance FROM user_settings WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    start_balance = row["start_balance"] if row else 0

    current_balance = start_balance + (income or 0) - (expense or 0)

    c.close()
    conn.close()

    return {
        "period_label": label,
        "income": income or 0.0,
        "expense": expense or 0.0,
        "balance": current_balance,
        "start_balance": start_balance
    }

@app.get("/api/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    loop = asyncio.get_event_loop()
    loop.create_task(dp.start_polling())
    uvicorn.run(app, host="0.0.0.0", port=8000)
