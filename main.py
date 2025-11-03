# backend/main.py
import os
import sqlite3
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException
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
    c.execute("""CREATE TABLE IF NOT EXISTS user_settings (
        user_id INTEGER PRIMARY KEY,
        currency TEXT,
        start_balance REAL
    );""")
    c.execute("""CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        type TEXT
    );""")
    c.execute("""CREATE TABLE IF NOT EXISTS finance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        amount REAL,
        description TEXT,
        category_id INTEGER,
        created_at TEXT
    );""")
    # default categories
    c.execute("SELECT COUNT(*) FROM categories")
    if c.fetchone()[0] == 0:
        default_categories = [
            ("Зарплата", "income"),
            ("Подарки", "income"),
            ("Прочее", "income"),
            ("Еда", "expense"),
            ("Транспорт", "expense"),
            ("Жильё", "expense"),
            ("Развлечения", "expense"),
            ("Прочее", "expense"),
        ]
        c.executemany("INSERT INTO categories (name, type) VALUES (?, ?)", default_categories)
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
    allow_origins=["https://frontend-nine-phi-39.vercel.app/"],  # на dev можно *, потом лучше указать фронтенд URL
    allow_methods=["*"],
    allow_headers=["*"],
)

class AddRecordRequest(BaseModel):
    init_data: str = None
    user_id: int = None
    type: str
    amount: float
    description: str = ""
    category_id: int = None

def get_conn():
    return sqlite3.connect(DB_PATH)

@app.post("/api/add")
async def api_add(record: AddRecordRequest):
    user_id = record.user_id or None
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "INSERT INTO finance (user_id, type, amount, description, category_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, record.type, record.amount, record.description, record.category_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()

    if user_id:
        asyncio.create_task(send_message_to_user(user_id, f"✅ Запись добавлена: {record.type} {record.amount}"))

    return {"status": "ok"}

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
    elif period == "year":
        start = now - timedelta(days=365)
        label = f"{(now - timedelta(days=365)).strftime('%d.%m.%Y')} — {now.strftime('%d.%m.%Y')}"
    else:
        raise HTTPException(status_code=400, detail="unknown period")

    conn = get_conn()
    c = conn.cursor()
    if user_id:
        c.execute("SELECT type, SUM(amount) FROM finance WHERE user_id = ? AND datetime(created_at) BETWEEN ? AND ? GROUP BY type",
                  (user_id, start.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d %H:%M:%S")))
    else:
        c.execute("SELECT type, SUM(amount) FROM finance WHERE datetime(created_at) BETWEEN ? AND ? GROUP BY type",
                  (start.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d %H:%M:%S")))
    rows = c.fetchall()
    conn.close()

    income = sum(r[1] for r in rows if r[0] == "income")
    expense = sum(r[1] for r in rows if r[0] == "expense")
    return {"period_label": label, "income": income or 0.0, "expense": expense or 0.0, "data": rows}

@app.get("/api/health")
async def health():
    return {"status": "ok"}

# ===================== Запуск =====================
if __name__ == "__main__":
    import uvicorn
    loop = asyncio.get_event_loop()
    loop.create_task(dp.start_polling())  # запускаем бот
    uvicorn.run(app, host="0.0.0.0", port=8000)  # запускаем FastAPI
