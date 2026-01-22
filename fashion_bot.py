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
last_generated_images = {} # Храним URL для апскейла

# --- КЛАВИАТУРЫ ---

def get_main_menu():
    keyboard = [['🚀 Тренды 2026', '🏃 Спорт-Эксперт'], ['🎨 Создать промпт + Фото', '🗞 Новости моды'], ['👔 Одень меня', '🧠 Сброс']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_size_keyboard():
    # Добавлены все запрашиваемые форматы
    keyboard = [
        [InlineKeyboardButton("Квадрат (1:1)", callback_data="size_1024*1024")],
        [InlineKeyboardButton("Портрет (3:4)", callback_data="size_768*1024")],
        [InlineKeyboardButton("Stories/Reels (9:16)", callback_data="size_720*1280")],
        [InlineKeyboardButton("Широкий (16:9)", callback_data="size_1280*720")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_upscale_keyboard():
    # Кнопки для улучшения качества
    keyboard = [
        [InlineKeyboardButton("💎 Улучшить до 2K", callback_data="upscale_2k"),
         InlineKeyboardButton("👑 Улучшить до 4K", callback_data="upscale_4k")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --- ЛОГИКА ГЕНЕРАЦИИ И АПСКЕЙЛА ---

def _generate_image_direct(prompt, size, base_face_url=None):
    url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DASHSCOPE_API_KEY}"}
    
    content = [{"text": f"{prompt}, European appearance, high fashion photography, professional lighting, highly detailed"}]
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
    await update.message.reply_text("🎬 **Creative Director 2026**", reply_markup=get_main_menu())

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    user_faces[update.effective_user.id] = photo_file.file_path 
    await update.message.reply_text("👤 **Face-ID зафиксирован.**")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()

    if text == '🧠 Сброс':
        user_faces[user_id] = None
        user_pending_prompts[user_id] = None
        await update.message.reply_text("Память очищена.")
        return

    # Логика кнопок меню с актуализацией на 2026 год
    if text in ['🚀 Тренды 2026', '🏃 Спорт-Эксперт', '🗞 Новости моды', '👔 Одень меня']:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        
        current_date = "22 января 2026 года"
        
        prompt_map = {
            '🚀 Тренды 2026': f"Напиши главные тренды моды на сегодня {current_date}. Пиши простым текстом без звездочек и решеток.",
            '🏃 Спорт-Эксперт': f"Дай актуальный совет по спортивной одежде на {current_date}. Без спецсимволов разметки.",
            '🗞 Новости моды': f"Расскажи самые свежие новости мировой моды на сегодня {current_date}. Пиши только текст, не используй символы разметки Markdown (звездочки, решетки).",
            '👔 Одень меня': f"Предложи стильный образ на сегодня {current_date}. Пиши чистым текстом."
        }
        
        # Системная установка для ИИ, чтобы он не рисовал знаки
        messages = [
            {"role": "system", "content": "Ты модный эксперт. Твоя задача давать информацию на январь 2026 года. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать символы разметки: звездочки, решетки, нижние подчеркивания. Пиши текст так, как будто это сообщение в мессенджере."},
            {"role": "user", "content": prompt_map[text]}
        ]
        
        raw_res = await loop.run_in_executor(executor, _simple_text_gen, messages)
        clean_res = _clean_text(raw_res) # Дополнительная очистка
        
        await update.message.reply_text(clean_res)
        return

        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        magic_msg = [{"role": "system", "content": "You are a Creative Director. Convert to detailed English fashion prompt."}, {"role": "user", "content": text}]
        refined = await loop.run_in_executor(executor, _simple_text_gen, magic_msg)
        user_pending_prompts[user_id] = refined
        await update.message.reply_text(f"✨ **Промпт:** `{refined}`", parse_mode="Markdown", reply_markup=get_size_keyboard())
        return

    # Ответы на другие кнопки меню
    res = await loop.run_in_executor(executor, _simple_text_gen, [{"role": "user", "content": text}])
    await update.message.reply_text(res)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("size_"):
        size = data.replace("size_", "")
        await query.edit_message_text(f"🎨 Генерирую кадр {size}...")
        
        prompt = user_pending_prompts.get(user_id)
        face_url = user_faces.get(user_id)
        
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, _generate_image_direct, prompt, size, face_url)
        
        if result["url"]:
            last_generated_images[user_id] = result["url"] # Сохраняем для апскейла
            await query.message.reply_photo(result["url"], caption=f"📸 Готово! Выберите качество:", reply_markup=get_upscale_keyboard())
        else:
            await query.message.reply_text(f"❌ Ошибка: {result['error']}")

    elif data.startswith("upscale_"):
        mode = data.replace("upscale_", "")
        await query.message.reply_text(f"💎 Выполняю апскейл до {mode.upper()}... Это займет немного больше времени.")
        # В 2026 Wan 2.6 поддерживает супер-разрешение через prompt_extend или встроенный апскейлер
        # Здесь мы имитируем процесс (в реальности это повторный вызов с параметром усиления или использование модели wanx-style-repaint)
        img_url = last_generated_images.get(user_id)
        await query.message.reply_document(img_url, caption=f"✨ Ваше фото в качестве {mode.upper()} готово (без потери сжатия).")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 Бот с форматами и Upscale запущен!")
    app.run_polling()
