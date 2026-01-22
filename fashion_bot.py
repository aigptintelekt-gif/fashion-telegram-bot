import os
import logging
import asyncio
from datetime import datetime
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

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

# --- ПАМЯТЬ И ЛИЧНОСТЬ ---
user_histories = {}
HISTORY_LIMIT = 8

STYLIST_PERSONALITY = (
    "Ты — ведущий эксперт в Sport-Tech моде и Active Luxury. Твой фокус: кроссовки, умные ткани, мембраны. "
    "Стиль: лаконичный, профессиональный. НЕ используй '***' и много эмодзи. "
    "Если пользователь просит образ или фото — опиши его как профессиональный стилист."
)

# --- МЕНЮ ---
def get_main_menu():
    keyboard = [
        ['🚀 Тренды 2026', '🏃 Спорт-Эксперт'],
        ['👔 Одень меня', '🗞 Новости моды'],
        ['🧠 Сброс']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- ТЕХНИЧЕСКИЕ ФУНКЦИИ ---

def _generate_text_sync(messages):
    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Text Error: {e}")
        return "Ошибка при генерации текста."

def _generate_image_sync(prompt):
    try:
        # ДОБАВЛЕНА КОРРЕКЦИЯ: Caucasian/European для избежания азиатских лиц
        european_prompt = f"Caucasian appearance, European model, {prompt}, professional fashion photography, 8k, highly detailed, realistic style"
        
        rsp = ImageSynthesis.call(
            model="qwen-image-plus",
            prompt=european_prompt,
            n=1,
            size='1024*1024'
        )
        if rsp.status_code == HTTPStatus.OK:
            return rsp.output.results[0].url
        return None
    except Exception as e:
        logger.error(f"Image Error: {e}")
        return None

def _analyze_photo_with_vision(photo_url, user_caption):
    try:
        response = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Analyze this person. Maintain Caucasian/European traits in response. Request: {user_caption}"},
                    {"type": "image_url", "image_url": {"url": photo_url}}
                ],
            }]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Vision error: {e}")
        return f"Fashion trend 2026, {user_caption}"

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = [{"role": "system", "content": STYLIST_PERSONALITY}]
    context.user_data['mode'] = 'normal'
    
    await update.message.reply_text(
        "✨ **ИИ-Стилист 2026 на связи.**\n\nЯ помню наш диалог. Теперь я настроен на европейские тренды и готов к работе.",
        reply_markup=get_main_menu(), parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.caption or "трендовый образ"
    
    # ИНТЕРАКТИВ: Показываем статус "ищет локацию" (для фото используем UPLOAD_PHOTO)
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    await update.message.reply_text("📸 Анализирую внешность и подбираю европейский стайлинг...")
    
    photo_file = await update.message.photo[-1].get_file()
    photo_url = photo_file.file_path
    loop = asyncio.get_running_loop()

    # Анализ зрения
    analysis = await loop.run_in_executor(executor, _analyze_photo_with_vision, photo_url, caption)
    await update.message.reply_text(f"🔍 **Анализ стиля:**\n\n{analysis}")
    
    # Генерация картинки
    await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
    img_url = await loop.run_in_executor(executor, _generate_image_sync, analysis)
    
    if img_url:
        await update.message.reply_photo(img_url, caption="🌟 Твой персонализированный образ 2026 (European Style)")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()
    user_mode = context.user_data.get('mode', 'normal')

    # СБРОС
    if text == '🧠 Сброс':
        user_histories[user_id] = [{"role": "system", "content": STYLIST_PERSONALITY}]
        context.user_data['mode'] = 'normal'
        await update.message.reply_text("🧠 Память очищена.", reply_markup=get_main_menu())
        return

    # СПОРТ-ЭКСПЕРТ
    if text == '🏃 Спорт-Эксперт':
        context.user_data['mode'] = 'sport'
        await update.message.reply_text("🏃 Режим Sport-Tech активирован. Жду твой запрос по кроссовкам или технологиям.")
        return

    # Список триггеров для фото
    image_keywords = ["пришли фото", "покажи фото", "нарисуй", "сгенерируй", "photo", "образ", "стиль"]
    is_drawing_request = any(word in text.lower() for word in image_keywords)

    # ИНТЕРАКТИВ: Постоянно имитируем набор текста, пока бот думает
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    
    if user_id not in user_histories:
        user_histories[user_id] = [{"role": "system", "content": STYLIST_PERSONALITY}]

    user_histories[user_id].append({"role": "user", "content": text})

    # Генерируем текст
    bot_response = await loop.run_in_executor(executor, _generate_text_sync, user_histories[user_id])
    
    # Отправляем текстовый ответ
    try:
        await update.message.reply_text(bot_response, parse_mode="Markdown")
    except:
        await update.message.reply_text(bot_response)

    # Если нужно фото
    if is_drawing_request or user_mode == 'sport':
        # ИНТЕРАКТИВ: Статус отправки фото
        await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        
        # Генерируем картинку с учетом European-тега внутри функции _generate_image_sync
        img_url = await loop.run_in_executor(executor, _generate_image_sync, bot_response[:200])
        
        if img_url:
            await update.message.reply_photo(img_url, caption="📊 Визуализация образа (European Concept)")
    
    user_histories[user_id].append({"role": "assistant", "content": bot_response})
    
    # Обрезка истории
    if len(user_histories[user_id]) > HISTORY_LIMIT:
        user_histories[user_id] = [user_histories[user_id][0]] + user_histories[user_id][-(HISTORY_LIMIT-1):]

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 Бот запущен! Интерактив и European-модели активны.")
    app.run_polling()
