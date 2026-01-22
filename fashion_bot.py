import os
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from http import HTTPStatus

# Telegram
from telegram import Update, constants, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# DashScope
import dashscope
from dashscope import MultiModalGeneration
from openai import OpenAI

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

# Клиент для перевода и улучшения промптов
client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

user_faces = {} 
user_pending_prompts = {}

# --- ГЕНЕРАЦИЯ ДЛЯ WAN 2.6 ---

def _generate_image_wan26(prompt, size, base_face_url=None):
    try:
        content = [{"text": f"{prompt}, European appearance, high fashion photography, professional lighting, 8k"}]
        
        if base_face_url:
            # Важно: URL фотографии должен быть публично доступным для API Alibaba
            content.append({"image": base_face_url})

        responses = MultiModalGeneration.call(
            model="wan2.6-image",
            input={
                "messages": [
                    {
                        "role": "user",
                        "content": content
                    }
                ]
            },
            parameters={
                "size": size,
                "n": 1,
                "prompt_extend": True,
                "watermark": False
            }
        )

        if responses.status_code == HTTPStatus.OK:
            # Корректный путь к URL изображения для модели Wan 2.6
            return {"url": responses.output.choices[0].message.content[0]["image"], "error": None}
        else:
            return {"url": None, "error": f"Status: {responses.status_code}\nCode: {responses.code}\nMsg: {responses.message}"}
            
    except Exception as e:
        return {"url": None, "error": str(e)}

def _improve_prompt(text):
    """Переводит и обогащает промпт через LLM"""
    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=[
                {"role": "system", "content": "You are a professional fashion photographer. Translate and enhance the user's idea into a detailed English prompt for an image generator. Focus on lighting, fabric textures, and model posture."},
                {"role": "user", "content": text}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM Error: {e}")
        return text

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_pending_prompts[update.effective_user.id] = None
    keyboard = [['🎨 Создать промпт + Фото', '🧠 Сброс']]
    await update.message.reply_text(
        "🚀 **Wan 2.6 Creative Suite запущен.**\n\n1. Пришли фото лица (опционально).\n2. Напиши идею образа.",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo_file = await update.message.photo[-1].get_file()
    user_faces[user_id] = photo_file.file_path 
    await update.message.reply_text("👤 **Face Reference сохранен.**")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    if text == '🧠 Сброс':
        user_faces[user_id] = None
        user_pending_prompts[user_id] = None
        await update.message.reply_text("🧠 Память очищена.")
        return

    if text == '🎨 Создать промпт + Фото' or user_pending_prompts.get(user_id) == "WAITING":
        if text == '🎨 Создать промпт + Фото':
            user_pending_prompts[user_id] = "WAITING"
            await update.message.reply_text("📽 Опишите вашу идею для съемки:")
            return

        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        loop = asyncio.get_running_loop()
        
        # Улучшаем промпт
        refined_prompt = await loop.run_in_executor(executor, _improve_prompt, text)
        user_pending_prompts[user_id] = refined_prompt
        
        # Кнопки выбора формата
        kb = [
            [InlineKeyboardButton("Квадрат (1:1)", callback_data="size_1024*1024")],
            [InlineKeyboardButton("Stories (9:16)", callback_data="size_720*1280")],
            [InlineKeyboardButton("Широкий (16:9)", callback_data="size_1280*720")]
        ]
        await update.message.reply_text(
            f"✨ **Улучшенный промпт:**\n`{refined_prompt}`\n\nВыберите формат кадра:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    size = query.data.replace("size_", "")
    await query.answer()

    prompt = user_pending_prompts.get(user_id)
    if not prompt:
        await query.message.reply_text("❌ Ошибка: промпт не найден. Введите описание заново.")
        return

    face_url = user_faces.get(user_id)
    await query.edit_message_text(f"🎨 Wan 2.6 рендерит кадр в формате {size}...")
    
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _generate_image_wan26, prompt, size, face_url)
    
    if result["url"]:
        await query.message.reply_photo(result["url"], caption=f"📸 Ready! Format: {size}\nModel: Wan 2.6")
    else:
        await query.message.reply_text(f"❌ **Ошибка генерации:**\n\n`{result['error']}`")

# --- ЗАПУСК ---

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🚀 Бот на базе Wan 2.6 запущен и готов к работе!")
    app.run_polling()
