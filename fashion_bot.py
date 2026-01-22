import os
import logging
import asyncio
import requests
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from http import HTTPStatus

# Telegram
from telegram import Update, constants, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# DashScope / OpenAI
from openai import OpenAI
import dashscope
from dashscope import ImageSynthesis

# --- ИНИЦИАЛИЗАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# Настройка DashScope для международного региона
dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

if not TELEGRAM_TOKEN or not DASHSCOPE_API_KEY:
    raise ValueError("Критическая ошибка: Ключи API не найдены!")

# Логирование
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Текстовый клиент (Qwen)
text_client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

executor = ThreadPoolExecutor(max_workers=4)
user_histories = {}
HISTORY_LIMIT = 8

# --- ГЛАВНОЕ МЕНЮ ---
def get_main_menu():
    keyboard = [
        ['🚀 Тренды 2026', '👔 Одень меня'],
        ['🗞 Новости моды', '🧠 Сброс памяти']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- СИНХРОННЫЕ ФУНКЦИИ (ДЛЯ EXECUTOR) ---

def _generate_text_sync(messages):
    try:
        response = text_client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
            temperature=0.8
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка текста: {e}")
        return "❌ Прости, мой модный процессор перегрелся. Попробуй позже!"

def _generate_image_sync(prompt):
    try:
        logger.info(f"Генерация образа 2026 для: {prompt[:30]}")
        rsp = ImageSynthesis.call(
            api_key=DASHSCOPE_API_KEY,
            model="qwen-image-plus",
            prompt=f"High-end fashion photography, 2026 trend, cinematic lighting, editorial style: {prompt}",
            n=1,
            size='1024*1024',
            prompt_extend=True
        )
        if rsp.status_code == HTTPStatus.OK:
            return rsp.output.results[0].url
        return None
    except Exception as e:
        logger.error(f"Ошибка картинки: {e}")
        return None

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text(
        "✨ **Добро пожаловать в мир моды 2026!** ✨\n\n"
        "Я твой персональный ИИ-кутюрье. Я знаю всё о тканях будущего и текущих подиумах.\n\n"
        "Что я умею:\n"
        "1️⃣ **Анализ ссылок**: Пришли ссылку на новость, и я сделаю саммари.\n"
        "2️⃣ **Стиль по фото**: Пришли свое фото, и я подберу образ.\n"
        "3️⃣ **Генерация**: Просто опиши лук, и я его отрисую.\n\n"
        "Используй меню ниже! 👇",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Вижу твой стиль! Анализирую пропорции для трендов 2026 года... 🔥")
    await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
    
    loop = asyncio.get_running_loop()
    caption = update.message.caption or "стильный осенний образ"
    
    prompt = f"Futuristic outfit inspired by user photo, trend 2026, cyberpunk elegant, high detailed fabric: {caption}"
    image_url = await loop.run_in_executor(executor, _generate_image_sync, prompt)
    
    if image_url:
        await update.message.reply_photo(image_url, caption="✨ Твой эксклюзивный образ 'Осень 2026' готов! Как тебе такое преображение? 😍")
    else:
        await update.message.reply_text("❌ Не удалось создать визуализацию, но ты выглядишь потрясающе!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    loop = asyncio.get_running_loop()

    if not user_text: return

    # Обработка кнопок и специальных команд
    if user_text == '🚀 Тренды 2026':
        user_text = "Расскажи кратко о самых горячих трендах моды на текущий момент 2026 года со смайликами"
    elif user_text == '🗞 Новости моды':
        user_text = "Дай краткую сводку последних новостей индустрии моды за неделю"
    elif user_text == '👔 Одень меня':
        await update.message.reply_text("Просто пришли мне свое фото, и я подберу тебе лук! 😉")
        return
    elif user_text == '🧠 Сброс памяти':
        user_histories[user_id] = []
        await update.message.reply_text("🧠 Память очищена! Готов к новым экспериментам.", reply_markup=get_main_menu())
        return

    # Логика анализа ссылок
    if "http" in user_text:
        await update.message.reply_text("🔎 **Сканирую ресурс на наличие трендов...**")
        prompt = f"Проанализируй этот сайт и выдели главные модные новинки 2026 года: {user_text}"
        res = await loop.run_in_executor(executor, _generate_text_sync, [{"role": "user", "content": prompt}])
        await update.message.reply_text(f"🧵 **Вот мой анализ:**\n\n{res}")
        return

    # Логика генерации (если есть ключевые слова)
    image_keywords = ["фото", "нарисуй", "образ", "стиль", "сгенерируй", "одень", "лук"]
    is_drawing = any(word in user_text.lower() for word in image_keywords)

    if is_drawing:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        
        # 1. Текстовое описание от стилиста
        system_msg = "Ты — топ-стилист 🎩. Опиши кратко и эффектно образ для пользователя на основе его запроса. Используй смайлики."
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_text}
        ]
        stylist_note = await loop.run_in_executor(executor, _generate_text_sync, messages)
        await update.message.reply_text(f"👔 **Мнение эксперта:**\n\n{stylist_note}")

        # 2. Визуализация
        await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        image_url = await loop.run_in_executor(executor, _generate_image_sync, user_text)
        
        if image_url:
            await update.message.reply_photo(image_url, caption="📸 Визуализация тренда 2026 для тебя")
        else:
            await update.message.reply_text("❌ Не удалось отрисовать, но описание выше!")
        return

    # Обычный диалог
    if user_id not in user_histories:
        user_histories[user_id] = [{"role": "system", "content": "Ты модный эксперт-стилист 2026 года. Отвечай кратко, стильно и со смайликами."}]
    
    user_histories[user_id].append({"role": "user", "content": user_text})
    
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    bot_res = await loop.run_in_executor(executor, _generate_text_sync, user_histories[user_id])
    
    user_histories[user_id].append({"role": "assistant", "content": bot_res})
    
    # Ограничение памяти
    if len(user_histories[user_id]) > HISTORY_LIMIT:
        user_histories[user_id] = [user_histories[user_id][0]] + user_histories[user_id][-5:]

    try:
        await update.message.reply_text(bot_res, parse_mode="Markdown")
    except:
        await update.message.reply_text(bot_res)

# --- ЗАПУСК ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", handle_message)) # Можно и через команду
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🚀 ИИ-стилист 2026 запущен!")
    app.run_polling()
