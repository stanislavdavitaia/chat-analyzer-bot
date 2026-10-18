import os
import asyncio
from datetime import datetime
from collections import deque
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.enums import ChatAction
import aiohttp
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={GEMINI_API_KEY}"

bot = Bot(token=BOT_TOKEN) if BOT_TOKEN else None
dp = Dispatcher()

messages_db = {}
MAX_MESSAGES_PER_CHAT = 100
ANALYSIS_INTERVAL_MINUTES = 30


def init_storage(chat_id: int):
    if chat_id not in messages_db:
        messages_db[chat_id] = deque(maxlen=MAX_MESSAGES_PER_CHAT)


@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот-аналитик чата.\n\n"
        "Я читаю сообщения и раз в 30 минут генерирую идеи, размышления и подсказки.\n\n"
        "Команды:\n"
        "/analyze — проанализировать чат сейчас\n"
        "/stats — статистика чата\n"
        "/help — помощь"
    )


@dp.message(Command("help"))
async def help_cmd(message: types.Message):
    await message.answer(
        "🤖 <b>Как я работаю:</b>\n\n"
        "• Читаю все сообщения в чате\n"
        "• Храню последние 100 сообщений\n"
        "• Раз в 30 минут сам анализирую и пишу идеи\n"
        "• Команда /analyze — анализ по запросу\n\n"
        "<b>Настройка:</b>\n"
        "1. Добавь меня в чат\n"
        "2. Дай права админа (читать сообщения)\n"
        "3. Жди или нажми /analyze",
        parse_mode="HTML"
    )


@dp.message(Command("stats"))
async def stats(message: types.Message):
    chat_id = message.chat.id
    init_storage(chat_id)
    msgs = messages_db[chat_id]
    if not msgs:
        await message.answer("📊 Сообщений пока нет.")
        return

    users = {}
    for _, user, _ in msgs:
        users[user] = users.get(user, 0) + 1

    top = sorted(users.items(), key=lambda x: -x[1])[:5]
    text = f"📊 <b>Статистика чата</b>\n\n"
    text += f"Всего сообщений: {len(msgs)}\n"
    text += f"Уникальных авторов: {len(users)}\n\n"
    text += "<b>Топ-5 авторов:</b>\n"
    for user, count in top:
        text += f"  • {user}: {count}\n"

    await message.answer(text, parse_mode="HTML")


async def call_gemini(prompt: str) -> str:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": 800
        }
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(GEMINI_URL, json=payload) as resp:
            if resp.status != 200:
                error = await resp.text()
                logger.error(f"Gemini error: {error}")
                return None
            data = await resp.json()
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                return None


def build_prompt(messages: list) -> str:
    text = "\n".join([f"[{u}]: {t}" for _, u, t in messages[-50:]])
    return f"""Ты — умный ассистент, который анализирует переписку в чате.

Вот последние сообщения из чата:

{text}

Твоя задача — предложить 3-5 интересных идей/размышлений/подсказок на основе обсуждения.
Пиши кратко, по делу, на русском. Используй эмодзи. Не повторяй чужие сообщения, а развивай идеи.
Если в чате нет интересных тем — так и скажи.

Формат ответа:
💡 <b>Идея:</b> ...
🤔 <b>Размышление:</b> ...
👉 <b>Подсказка:</b> ...
"""


@dp.message(Command("analyze"))
async def analyze(message: types.Message):
    chat_id = message.chat.id
    init_storage(chat_id)
    msgs = list(messages_db[chat_id])

    if len(msgs) < 5:
        await message.answer("⏳ Пока мало сообщений. Надо минимум 5.")
        return

    await message.answer("🤔 Анализирую...")
    await bot.send_chat_action(chat_id, ChatAction.TYPING)

    prompt = build_prompt(msgs)
    result = await call_gemini(prompt)

    if result:
        await message.answer(result, parse_mode="HTML")
    else:
        await message.answer("❌ Ошибка анализа. Проверь GEMINI_API_KEY.")


@dp.message()
async def store_message(message: types.Message):
    if message.chat.type in ["group", "supergroup"]:
        chat_id = message.chat.id
        init_storage(chat_id)
        user = message.from_user.first_name or "Аноним"
        text = message.text or "[медиа]"
        messages_db[chat_id].append((datetime.now(), user, text))


async def periodic_analyzer():
    while True:
        await asyncio.sleep(ANALYSIS_INTERVAL_MINUTES * 60)
        for chat_id, msgs in messages_db.items():
            if len(msgs) >= 10:
                try:
                    prompt = build_prompt(list(msgs))
                    result = await call_gemini(prompt)
                    if result:
                        await bot.send_message(chat_id, "⏰ <b>Анализ чата за полчаса:</b>\n\n" + result, parse_mode="HTML")
                except Exception as e:
                    logger.error(f"Periodic analysis error: {e}")


async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан!")
        return
    if not GEMINI_API_KEY:
        logger.error("GEMINI_API_KEY не задан!")
        return

    asyncio.create_task(periodic_analyzer())
    logger.info("Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
