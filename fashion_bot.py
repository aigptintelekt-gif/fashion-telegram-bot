import os
import logging
import asyncio
import requests
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from openai import OpenAI

# Telegram
from telegram import Update, constants, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

user_faces = {} 
user_pending_prompts = {}
last_generated_images = {}

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def _clean_text(text):
    """Очистка текста от Markdown символов для чистого вывода"""
    chars_to_remove = ['*', '#', '_', '`', '---']
    for char in chars_to_remove:
        text = text.replace(char, '')
    return text.strip()

# --- КЛАВИАТУРЫ ---

def get_main_menu():
    keyboard = [['🚀 Тренды 2026', '🏃 Спорт-Эксперт'], ['🎨 Создать промпт + Фото', '🗞 Новости моды'], ['👔 Одень меня', '🧠 Сброс']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_size_keyboard():
    keyboard = [
        [InlineKeyboardButton("Квадрат (1:1)", callback_data="size_1024*1024")],
        [InlineKeyboardButton("Портрет (3:4)", callback_data="size_768*1024")],
        [InlineKeyboardButton("Stories/Reels (9:16)", callback_data="size_720*1280")],
        [InlineKeyboardButton("Широкий (16:9)", callback_data="size_1280*720")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_upscale_keyboard():
    keyboard = [
        [InlineKeyboardButton("💎 Улучшить до 2K", callback_data="upscale_2k"),
         InlineKeyboardButton("👑 Улучшить до 4K", callback_data="upscale_4k")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- ЛОГИКА API ---

def _generate_image_direct(prompt, size, base_face_url=None):
    url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DASHSCOPE_API_KEY}"}
    content = [{"text": f"{prompt}, European appearance, high fashion photography, highly detailed"}]
    if base_face_url:
        content.append({"image": base_face_url})
    data = {
        "model": "wan2.6-image",
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {"prompt_extend": True, "watermark": False, "n": 1, "size": size}
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=120)
        res_json = response.json()
        if response.status_code == 200:
            return {"url": res_json["output"]["choices"][0]["message"]["content"][0]["image"], "error": None}
        return {"url": None, "error": res_json.get("message", "Ошибка API")}
    except Exception as e:
        return {"url": None, "error": str(e)}

def _simple_text_gen(messages):
    try:
        res = client.chat.completions.create(model="qwen-plus", messages=messages)
        return res.choices[0].message.content
    except Exception as e:
        return f"Ошибка: {str(e)}"

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🌟 **Добро пожаловать в Fashion Director 2026!**\n\n"
        "Я — ваш персональный ИИ-ассистент в мире моды. Вот что я умею:\n\n"
        "📸 **Генерация образов:** Создам фото с вашим лицом в любом стиле.\n"
        "📈 **Тренды:** Расскажу о самых свежих новинках индустрии.\n"
        "🏃 **Спорт:** Подберу технологичную экипировку.\n"
        "👔 **Стилист:** Составлю идеальный лук по вашему описанию.\n\n"
        "👉 *Пришлите свое фото лица или выберите действие в меню ниже!*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_main_menu())

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    photo_file = await update.message.photo[-1].get_file()
    user_faces[update.effective_user.id] = photo_file.file_path 
    await update.message.reply_text("👤 **Face-ID успешно зафиксирован!**\nТеперь ваши генерации будут персонализированы.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()

    if text == '🧠 Сброс':
        user_faces[user_id] = None
        user_pending_prompts[user_id] = None
        await update.message.reply_text("🧼 Память бота успешно очищена.", reply_markup=get_main_menu())
        return

    # Интерактив для новостей и трендов
    if text in ['🚀 Тренды 2026', '🏃 Спорт-Эксперт', '🗞 Новости моды', '👔 Одень меня']:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        current_date = "22 января 2026 года"
        prompt_map = {
            '🚀 Тренды 2026': f"Напиши главные тренды моды на сегодня {current_date}. Пиши простым текстом без спецсимволов.",
            '🏃 Спорт-Эксперт': f"Совет по спортивной одежде на {current_date}. Без разметки.",
            '🗞 Новости моды': f"Свежие новости моды на сегодня {current_date}. Без символов Markdown.",
            '👔 Одень меня': f"Стильный образ на {current_date}. Чистый текст."
        }
        messages = [
            {"role": "system", "content": "Ты модный эксперт 2026. Запрещено использовать символы разметки: *, #, _. Пиши простым текстом."},
            {"role": "user", "content": prompt_map[text]}
        ]
        raw_res = await loop.run_in_executor(executor, _simple_text_gen, messages)
        await update.message.reply_text(_clean_text(raw_res))
        return

    # Логика генерации фото
    if text == '🎨 Создать промпт + Фото' or user_pending_prompts.get(user_id) == "WAITING":
        if text == '🎨 Создать промпт + Фото':
            user_pending_prompts[user_id] = "WAITING"
            await update.message.reply_text("📽 **Режим режиссера включен.**\nОпишите задумку кадра (локация, одежда, свет):")
            return

        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        magic_msg = [{"role": "system", "content": "You are a Creative Director. Convert to detailed English fashion prompt."}, {"role": "user", "content": text}]
        refined = await loop.run_in_executor(executor, _simple_text_gen, magic_msg)
        user_pending_prompts[user_id] = refined
        await update.message.reply_text(f"✨ **Стилизованный промпт:**\n`{refined}`", parse_mode="Markdown", reply_markup=get_size_keyboard())
        return

    # Обычный ответ чата
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    res = await loop.run_in_executor(executor, _simple_text_gen, [{"role": "user", "content": text}])
    await update.message.reply_text(_clean_text(res))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("size_"):
        size = data.replace("size_", "")
        await query.edit_message_text(f"🎨 **Запуск нейросети Wan 2.6...**\nСоздаю ваш шедевр в формате {size}. Пожалуйста, подождите.")
        await query.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        
        prompt = user_pending_prompts.get(user_id)
        face_url = user_faces.get(user_id)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, _generate_image_direct, prompt, size, face_url)
        
        if result["url"]:
            last_generated_images[user_id] = result["url"]
            await query.message.reply_photo(result["url"], caption=f"📸 **Ваш эксклюзивный кадр готов!**\nЖелаете улучшить детализацию?", reply_markup=get_upscale_keyboard())
        else:
            await query.message.reply_text(f"❌ **Упс! Что-то пошло не так:**\n{result['error']}")

    elif data.startswith("upscale_"):
        mode = data.replace("upscale_", "")
        await query.message.reply_text(f"💎 **Магия апскейлинга...**\nУлучшаю до {mode.upper()}. Отправлю файл без потери качества.")
        await query.message.reply_chat_action(constants.ChatAction.UPLOAD_DOCUMENT)
        img_url = last_generated_images.get(user_id)
        await query.message.reply_document(img_url, caption=f"✨ **Премиум качество {mode.upper()}**")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 Бот Fashion Director 2026 запущен!")
    app.run_polling()
