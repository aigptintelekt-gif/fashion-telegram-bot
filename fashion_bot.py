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
from dashscope import MultiModalGeneration # Используем мультимодальный класс

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

user_faces = {} 
user_pending_prompts = {}

# --- ГЕНЕРАЦИЯ ДЛЯ WAN 2.6 ---

def _generate_image_wan26(prompt, size, base_face_url=None):
    try:
        # Контент для сообщения
        content = [{"text": f"{prompt}, European appearance, high fashion photography, professional lighting, 8k"}]
        
        # Если пользователь прислал фото лица, добавляем его как визуальный референс
        if base_face_url:
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
            # В Wan 2.6 путь к результату может немного отличаться
            return {"url": responses.output.choices[0].message.content[0]["image"], "error": None}
        else:
            error_details = f"Status: {responses.status_code}\nCode: {responses.code}\nMsg: {responses.message}"
            return {"url": None, "error": error_details}
            
    except Exception as e:
        return {"url": None, "error": str(e)}

# --- ОБРАБОТЧИКИ ---

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo_file = await update.message.photo[-1].get_file()
    # Ссылка от Telegram API
    user_faces[user_id] = photo_file.file_path 
    await update.message.reply_text("👤 **Face Reference (Wan 2.6) загружен.**")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    # Преобразуем формат под требования Wan 2.6 (он любит квадратные или стандартные разрешения)
    size = query.data.replace("size_", "")
    await query.answer()

    prompt = user_pending_prompts.get(user_id)
    face_url = user_faces.get(user_id)
    
    await query.edit_message_text(f"🎨 Рендеринг Wan 2.6 ({size})...")
    
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _generate_image_wan26, prompt, size, face_url)
    
    if result["url"]:
        await query.message.reply_photo(result["url"], caption="📸 Готово (Model: Wan 2.6)")
    else:
        await query.message.reply_text(f"❌ **Ошибка генерации:**\n\n`{result['error']}`", parse_mode="Markdown")

# (Функции start, handle_text и main остаются прежними из прошлого сообщения)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # Добавь также CommandHandler("start", start)
    print("🚀 Бот на базе Wan 2.6 готов к работе!")
    app.run_polling()
