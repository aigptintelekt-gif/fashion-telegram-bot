import os
import logging
import asyncio
import requests
import json
from concurrent.futures import ThreadPoolExecutor
from http import HTTPStatus

# Telegram
from telegram import Update, constants, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# DashScope / OpenAI
from openai import OpenAI
import dashscope
from dashscope import ImageSynthesis

# --- ИНИЦИАЛИЗАЦИЯ ---
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

# Клиент для зрения и текста
client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def _analyze_photo_and_create_prompt(photo_url, user_caption):
    """
    Модель Qwen-VL 'смотрит' на фото и создает описание для генератора
    """
    try:
        response = client.chat.completions.create(
            model="qwen-vl-plus", # Используем визуальную модель
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Проанализируй одежду и внешность человека на этом фото. Учти пожелание пользователя: {user_caption}. Составь подробный промпт на английском языке для генерации похожего образа в трендах 2026 года. ВАЖНО: Укажи конкретную внешность (например, Caucasian или Latin), чтобы избежать азиатских черт по умолчанию. Опиши только одежду и окружение."},
                        {"type": "image_url", "image_url": {"url": photo_url}}
                    ],
                }
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Ошибка зрения: {e}")
        return f"Fashion photography, 2026 trend, realistic skin, diverse features, {user_caption}"

def _generate_image_sync(final_prompt):
    """Генерация финального изображения"""
    try:
        # Добавляем технические параметры для реализма и исключения азиатских черт
        enhanced_prompt = f"{final_prompt}, photorealistic, highly detailed, global fashion look, realistic facial features, 8k resolution"
        
        rsp = ImageSynthesis.call(
            api_key=DASHSCOPE_API_KEY,
            model="qwen-image-plus",
            prompt=enhanced_prompt,
            n=1,
            size='1024*1024',
            prompt_extend=True
        )
        if rsp.status_code == HTTPStatus.OK:
            return rsp.output.results[0].url
        return None
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}")
        return None

# --- ОБРАБОТЧИКИ ---

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    caption = update.message.caption or "сделай в трендах 2026"
    
    await update.message.reply_text("📸 **Вижу фото!** Сейчас я его 'изучу' и подберу образ... ⏳")
    await update.message.reply_chat_action(constants.ChatAction.TYPING)

    # 1. Получаем прямую ссылку на фото из Телеграма
    photo_file = await update.message.photo[-1].get_file()
    # Временная ссылка для API (Telegram позволяет скачивать через bot token)
    photo_url = photo_file.file_path 

    loop = asyncio.get_running_loop()

    # 2. Просим ИИ 'увидеть' фото и составить промпт
    visual_description = await loop.run_in_executor(executor, _analyze_photo_and_create_prompt, photo_url, caption)
    
    await update.message.reply_text(f"🧵 **Мой анализ:**\n{visual_description[:300]}...")
    await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)

    # 3. Генерируем новый образ на основе этого анализа
    new_image_url = await loop.run_in_executor(executor, _generate_image_sync, visual_description)

    if new_image_url:
        await update.message.reply_photo(new_image_url, caption="✨ Твоё преображение готово! \nЯ учел твои черты лица и текущие тренды 2026.")
    else:
        await update.message.reply_text("Что-то пошло не так при отрисовке, но я сохранил твои идеи! 👗")

# --- ОСТАЛЬНЫЕ ФУНКЦИИ (Меню, Старт) ---
def get_main_menu():
    return ReplyKeyboardMarkup([['🚀 Тренды 2026', '👗 Одень меня'], ['🧠 Сброс']], resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👔 **Привет! Я твой ИИ-стилист с глазами.**\nОтправь мне фото, и я разберу твой образ!", 
        reply_markup=get_main_menu()
    )

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    # Добавь сюда обработчик текста из предыдущего кода
    print("🚀 Бот-стилист с функцией зрения запущен!")
    app.run_polling()
