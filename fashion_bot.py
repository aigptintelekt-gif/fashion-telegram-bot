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
from dashscope import ImageSynthesis
from openai import OpenAI

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# Устанавливаем ключ напрямую в dashscope
dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

user_histories = {}
user_faces = {} 
user_pending_prompts = {}
last_generated_image = {}

STYLIST_PERSONALITY = (
    "Ты — Креативный Директор Fashion-съемок. Твой стиль: Sport-Tech и Active Luxury. "
    "Ты создаешь визуал уровня 2026 года для европейского рынка."
)

# --- КЛАВИАТУРЫ ---
def get_main_menu():
    keyboard = [['🚀 Тренды 2026', '🏃 Спорт-Эксперт'], ['🎨 Создать промпт + Фото', '🗞 Новости моды'], ['👔 Одень меня', '🧠 Сброс']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_size_keyboard():
    keyboard = [
        [InlineKeyboardButton("Квадрат (1:1)", callback_data="size_1024*1024")],
        [InlineKeyboardButton("Портрет (3:4)", callback_data="size_768*1024")],
        [InlineKeyboardButton("Reels/Stories (9:16)", callback_data="size_720*1280")],
        [InlineKeyboardButton("Широкий (16:9)", callback_data="size_1280*720")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- ГЕНЕРАЦИЯ (ИСПРАВЛЕННАЯ МОДЕЛЬ) ---
def _generate_image_advanced(prompt, size, base_face_url=None):
    try:
        # В 2026 году для Face-Reference и форматов лучше всего подходит wanx-v1
        model_name = "wanx-v1" 
        
        params = {
            "model": model_name,
            "prompt": prompt,
            "n": 1,
            "size": size
        }

        if base_face_url:
            params["ref_img"] = base_face_url
            params["ref_mode"] = "face_ref"

        rsp = ImageSynthesis.call(**params)

        if rsp.status_code == HTTPStatus.OK:
            return rsp.output.results[0].url
        else:
            logger.error(f"API Error: {rsp.code} - {rsp.message}")
            return None
    except Exception as e:
        logger.error(f"Image Gen Error: {e}")
        return None

def _simple_text_gen(messages):
    try:
        res = client.chat.completions.create(model="qwen-plus", messages=messages)
        return res.choices[0].message.content
    except: return "Ошибка связи с текстовым модулем."

# --- ОБРАБОТЧИКИ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 **Creative Director Mode: ON.**\n\nПришли портретное фото или выбери концепцию в меню.",
        reply_markup=get_main_menu()
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    photo_file = await update.message.photo[-1].get_file()
    user_faces[user_id] = photo_file.file_path 
    await update.message.reply_text("👤 **Face-ID зафиксирован.** Теперь я буду использовать твоё лицо.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()

    if text == '🧠 Сброс':
        user_faces[user_id] = None
        user_histories[user_id] = []
        await update.message.reply_text("🧠 Память очищена.")
        return

    if text == '🎨 Создать промпт + Фото' or any(kw in text.lower() for kw in ["фото", "образ", "нарисуй"]):
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        
        magic_prompt_messages = [
            {"role": "system", "content": (
                "You are a Creative Director. Convert user idea to a professional English fashion prompt. "
                "Always specify 'European model, Caucasian features'. "
                "Camera: Phase One XF. Lighting: cinematic studio. "
                "End with '---' and professional advice in Russian."
            )},
            {"role": "user", "content": text}
        ]
        full_res = await loop.run_in_executor(executor, _simple_text_gen, magic_prompt_messages)
        
        parts = full_res.split('---')
        refined_prompt = parts[0].strip()
        advice = parts[1].strip() if len(parts) > 1 else "Акцентируй внимание на взгляде."

        user_pending_prompts[user_id] = refined_prompt
        
        await update.message.reply_text(f"✨ **Задание для ИИ:**\n`{refined_prompt}`\n\n💡 **Совет:** _{advice}_", parse_mode="Markdown")
        await update.message.reply_text("🎬 **Выберите формат кадра:**", reply_markup=get_size_keyboard())
        return

    res = await loop.run_in_executor(executor, _simple_text_gen, [{"role": "user", "content": text}])
    await update.message.reply_text(res)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("size_"):
        size = data.replace("size_", "")
        await query.edit_message_text(text=f"⚙️ Рендеринг в формате {size}...")
        
        prompt = user_pending_prompts.get(user_id, "Fashion high-end photography")
        face_url = user_faces.get(user_id)
        loop = asyncio.get_running_loop()

        await query.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        img_url = await loop.run_in_executor(executor, _generate_image_advanced, prompt, size, face_url)
        
        if img_url:
            last_generated_image[user_id] = img_url
            await query.message.reply_photo(img_url, caption=f"✅ Shot 2026 | Format: {size}")
        else:
            await query.message.reply_text("❌ Ошибка: проверьте настройки API или лимиты модели Wanx.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 Бот исправлен и запущен!")
    app.run_polling()
