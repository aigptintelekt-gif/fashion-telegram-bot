import os
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from http import HTTPStatus

# Telegram
from telegram import Update, constants, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# DashScope (Model Studio)
import dashscope
from dashscope import ImageSynthesis
from openai import OpenAI

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# Настройка эндпоинта для Сингапура / International
dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

user_faces = {} 
user_pending_prompts = {}

# --- ФУНКЦИЯ ГЕНЕРАЦИИ С ОТЛАДКОЙ ---

def _generate_image_advanced(prompt, size, base_face_url=None):
    try:
        model = "wanx-v1" 
        
        params = {
            "model": model,
            "input": {
                "prompt": f"{prompt}, European appearance, high fashion photography, professional lighting, 8k"
            },
            "parameters": {
                "size": size,
                "n": 1
            }
        }

        if base_face_url:
            params["input"]["ref_img"] = base_face_url
            params["input"]["ref_mode"] = "face_ref"

        rsp = ImageSynthesis.call(**params)

        if rsp.status_code == HTTPStatus.OK:
            return {"url": rsp.output.results[0].url, "error": None}
        else:
            # Возвращаем детали ошибки
            error_details = f"Code: {rsp.code}\nMsg: {rsp.message}\nReqID: {rsp.request_id}"
            return {"url": None, "error": error_details}
            
    except Exception as e:
        return {"url": None, "error": str(e)}

# --- ТЕКСТОВАЯ ГЕНЕРАЦИЯ ---

def _simple_text_gen(messages):
    try:
        res = client.chat.completions.create(model="qwen-plus", messages=messages)
        return res.choices[0].message.content
    except Exception as e:
        return f"Error: {str(e)}"

# --- ОБРАБОТЧИКИ ---

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo_file = await update.message.photo[-1].get_file()
    user_faces[user_id] = photo_file.file_path 
    await update.message.reply_text("👤 **Лицо сохранено в базе.**")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()

    if text == '🧠 Сброс':
        user_faces[user_id] = None
        user_pending_prompts[user_id] = None
        await update.message.reply_text("🧠 Память очищена.")
        return

    if text == '🎨 Создать промпт + Фото' or user_pending_prompts.get(user_id) == "WAITING":
        if text == '🎨 Создать промпт + Фото':
            user_pending_prompts[user_id] = "WAITING"
            await update.message.reply_text("📽 Опиши концепцию (например: 'костюм из белого нейлона в стиле киберпанк'):")
            return

        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        magic_msg = [
            {"role": "system", "content": "Create a professional fashion prompt in English for a European model."},
            {"role": "user", "content": text}
        ]
        refined = await loop.run_in_executor(executor, _simple_text_gen, magic_msg)
        user_pending_prompts[user_id] = refined
        
        kb = [
            [InlineKeyboardButton("Квадрат (1:1)", callback_data="size_1024*1024")],
            [InlineKeyboardButton("Stories (9:16)", callback_data="size_720*1280")]
        ]
        await update.message.reply_text(f"✨ **Промпт:** `{refined}`", 
                                       parse_mode="Markdown", 
                                       reply_markup=InlineKeyboardMarkup(kb))
        return

    res = await loop.run_in_executor(executor, _simple_text_gen, [{"role": "user", "content": text}])
    await update.message.reply_text(res)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    size = query.data.replace("size_", "")
    await query.answer()

    prompt = user_pending_prompts.get(user_id)
    face_url = user_faces.get(user_id)
    
    await query.edit_message_text(f"🎨 Начинаю рендеринг ({size})...")
    
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _generate_image_advanced, prompt, size, face_url)
    
    if result["url"]:
        await query.message.reply_photo(result["url"], caption="📸 Готово!")
    else:
        # Прямой вывод ошибки пользователю в чат
        await query.message.reply_text(f"❌ **Ошибка API:**\n\n`{result['error']}`", parse_mode="Markdown")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 Бот с Debug-режимом запущен!")
    app.run_polling()
