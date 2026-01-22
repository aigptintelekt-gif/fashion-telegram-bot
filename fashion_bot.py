import os
import logging
import asyncio
import requests
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from telegram import Update, constants, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

user_faces = {} 
user_pending_prompts = {}

# --- ПРЯМОЙ ЗАПРОС К API (Замена SDK) ---

def _generate_image_wan26_direct(prompt, size, base_face_url=None):
    url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}"
    }
    
    # Формируем контент как в твоем curl
    content = [{"text": f"{prompt}, European appearance, high quality fashion shot"}]
    if base_face_url:
        content.append({"image": base_face_url})
        
    data = {
        "model": "wan2.6-image",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": content
                }
            ]
        },
        "parameters": {
            "prompt_extend": True,
            "watermark": False,
            "n": 1,
            "size": size
        }
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=60)
        res_json = response.json()
        
        if response.status_code == 200:
            # Путь к картинке в ответе Wan 2.6
            img_url = res_json["output"]["choices"][0]["message"]["content"][0]["image"]
            return {"url": img_url, "error": None}
        else:
            return {"url": None, "error": f"API Error: {res_json.get('message', 'Unknown error')}"}
    except Exception as e:
        return {"url": None, "error": str(e)}

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_pending_prompts[user_id] = None
    kb = [['🎨 Создать промпт + Фото', '🧠 Сброс']]
    await update.message.reply_text(
        "🎬 **Fashion Director Mode (Direct API).**\n\nПришли фото лица или опиши идею.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo_file = await update.message.photo[-1].get_file()
    user_faces[user_id] = photo_file.file_path 
    await update.message.reply_text("👤 **Face-ID сохранен.**")

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
            await update.message.reply_text("📽 Опиши концепцию (можно по-русски):")
            return

        user_pending_prompts[user_id] = text # Для теста используем текст напрямую
        
        kb = [
            [InlineKeyboardButton("Квадрат (1:1)", callback_data="size_1024*1024")],
            [InlineKeyboardButton("Stories (9:16)", callback_data="size_720*1280")]
        ]
        await update.message.reply_text(f"✨ **Идея принята:** `{text}`\nВыбери формат:", 
                                       reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    size = query.data.replace("size_", "")
    await query.answer()

    prompt = user_pending_prompts.get(user_id)
    face_url = user_faces.get(user_id)
    
    await query.edit_message_text(f"🎨 API запрос отправлен ({size})...")
    
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, _generate_image_wan26_direct, prompt, size, face_url)
    
    if result["url"]:
        await query.message.reply_photo(result["url"], caption=f"📸 Готово!\nFormat: {size}")
    else:
        await query.message.reply_text(f"❌ **Ошибка:**\n`{result['error']}`")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🚀 Бот запущен через Direct API Requests!")
    app.run_polling()
