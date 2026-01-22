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

# DashScope
import dashscope
from dashscope import ImageSynthesis
from openai import OpenAI

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

# Хранилища
user_histories = {}
user_faces = {} # Новое: храним URL последней фотографии пользователя

STYLIST_PERSONALITY = (
    "Ты — Fashion-директор. Твоя специализация: Sport-Tech и Active Luxury. "
    "Ты создаешь образы уровня 2026 года, фокусируясь на европейской премиальной эстетике."
)

def get_main_menu():
    keyboard = [['🚀 Тренды 2026', '🏃 Спорт-Эксперт'], ['🎨 Создать промпт + Фото', '🗞 Новости моды'], ['👔 Одень меня', '🧠 Сброс']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- УЛУЧШЕННАЯ ГЕНЕРАЦИЯ С УЧЕТОМ ЛИЦА ---

def _generate_image_with_face(prompt, base_face_url=None):
    try:
        # Если есть фото лица, добавляем его как референс (Image-to-Image / Face Ref)
        extra_params = {}
        if base_face_url:
            # Для модели Wanx использование ref_img позволяет сохранить сходство
            extra_params = {
                "ref_img": base_face_url,
                "ref_mode": "face_ref" # Специальный режим удержания лица
            }

        rsp = ImageSynthesis.call(
            model="wanx-v1", # Wanx лучше справляется с референсами
            prompt=f"Professional fashion photography, {prompt}, high detail, masterpiece",
            n=1,
            size='1024*1024',
            **extra_params
        )
        if rsp.status_code == HTTPStatus.OK:
            return rsp.output.results[0].url
        return None
    except Exception as e:
        logger.error(f"Image Gen Error: {e}")
        return None

def _simple_text_gen(messages):
    try:
        res = client.chat.completions.create(model="qwen-plus", messages=messages)
        return res.choices[0].message.content
    except: return "Ошибка текста."

# --- ОБРАБОТЧИКИ ---

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    
    # Получаем URL фото
    photo_file = await update.message.photo[-1].get_file()
    user_faces[user_id] = photo_file.file_path # Сохраняем лицо
    
    await update.message.reply_text(
        "👤 **Лицо зафиксировано!**\nТеперь при создании образов я буду использовать твою внешность. "
        "Попробуй нажать '🎨 Создать промпт + Фото' или напиши запрос.",
        reply_markup=get_main_menu()
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()
    mode = context.user_data.get('mode', 'normal')

    if text == '🧠 Сброс':
        user_histories[user_id] = []
        user_faces[user_id] = None
        context.user_data['mode'] = 'normal'
        await update.message.reply_text("🧠 Память и лицо очищены.", reply_markup=get_main_menu())
        return

    if text == '🎨 Создать промпт + Фото':
        context.user_data['mode'] = 'prompt_gen'
        await update.message.reply_text("📽 **Опиши концепцию.** Я интегрирую твоё лицо в этот образ.")
        return

    # Логика генерации
    if mode == 'prompt_gen' or any(kw in text.lower() for kw in ["фото", "образ"]):
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        
        # 1. Улучшаем промпт
        magic_prompt = [{"role": "system", "content": "Create a high-fashion prompt in English. Focused on European style."}, {"role": "user", "content": text}]
        refined_text = await loop.run_in_executor(executor, _simple_text_gen, magic_prompt)
        
        # 2. Генерируем с лицом или без
        await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        face_url = user_faces.get(user_id)
        
        if face_url:
            await update.message.reply_text("🎭 **Применяю твои черты лица к новому образу...**")
        
        img_url = await loop.run_in_executor(executor, _generate_image_with_face, refined_text, face_url)
        
        if img_url:
            caption = "📸 Твой персональный образ 2026" if face_url else "📸 Стилизация образа"
            await update.message.reply_photo(img_url, caption=caption)
        else:
            await update.message.reply_text("Ошибка генерации.")
        return

    # Обычный ответ
    res = await loop.run_in_executor(executor, _simple_text_gen, [{"role": "user", "content": text}])
    await update.message.reply_text(res)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start if 'start' in locals() else None))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 Бот с поддержкой Face-Reference запущен!")
    app.run_polling()
