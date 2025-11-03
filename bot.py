from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")  # ссылка на фронтенд WebApp

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# Создаем inline-клавиатуру с WebApp кнопкой
def finance_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton(
        text="Открыть финансы",
        web_app=types.WebAppInfo(url=WEBAPP_URL)
    ))
    return keyboard

# Команда /start
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer(
        "Привет! 👋\nНажми кнопку ниже, чтобы открыть финансовый WebApp:",
        reply_markup=finance_keyboard()
    )

# Любое сообщение оставляет кнопку
@dp.message_handler()
async def echo(message: types.Message):
    await message.answer(
        "Нажми кнопку ниже, чтобы открыть финансовый WebApp:",
        reply_markup=finance_keyboard()
    )

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
