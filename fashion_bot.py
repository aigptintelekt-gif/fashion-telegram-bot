"""
Fashion Director 2026 — Главный модуль
"""
import logging
import asyncio
import requests
import json
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI

# Telegram
from telegram import Update, constants, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Модули проекта
from config import *
from news_parser import get_fashion_news, format_news_message, get_cache_info

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL)
)
logger = logging.getLogger(__name__)

executor = ThreadPoolExecutor(max_workers=4)

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL
)

user_faces = {}
user_pending_prompts = {}
last_generated_images = {}

# ==================== КЛАВИАТУРЫ ====================

def get_main_menu():
    keyboard = [
        ['🚀 Тренды 2026', '🏃 Спорт-Эксперт'],
        ['🎨 Создать промпт + Фото', '🗞 Новости моды'],
        ['👔 Одень меня', '🧠 Сброс']
    ]
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

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def _clean_text(text):
    chars_to_remove = ['*', '#', '_', '`', '---']
    for char in chars_to_remove:
        text = text.replace(char, '')
    return text.strip()

def _generate_image_direct(prompt, size, base_face_url=None):
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
        response = requests.post(IMAGE_API_URL, headers=headers, json=data, timeout=120)
        res_json = response.json()
        if response.status_code == 200:
            return {"url": res_json["output"]["choices"][0]["message"]["content"][0]["image"], "error": None}
        return {"url": None, "error": res_json.get("message", "Ошибка API")}
    except Exception as e:
        return {"url": None, "error": str(e)}

def _simple_text_gen(messages):
    try:
        # Используем актуальную модель 2026 года
        res = client.chat.completions.create(model="qwen3-max-2026-01-23", messages=messages)
        return res.choices[0].message.content
    except Exception as e:
        return f"Ошибка: {str(e)}"

# ==================== ОБРАБОТЧИКИ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🌟 **Добро пожаловать в Fashion Director 2026!**\n\n"
        "Я — ваш персональный ИИ-ассистент. Я не просто кидаю ссылки, "
        "я анализирую главные мировые повестки в реальном времени.\n\n"
        "🗞 **Новости моды:** Теперь с кратким пересказом на русском языке!\n"
        "📸 **Генерация:** Попробуйте создать образ со своим лицом.\n\n"
        "👉 *Выберите действие ниже!*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_main_menu())

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    photo_file = await update.message.photo[-1].get_file()
    user_faces[update.effective_user.id] = photo_file.file_path
    await update.message.reply_text("👤 **Face-ID зафиксирован!**\nТеперь генерации будут персонализированы.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()

    # 1. Сброс / Меню
    if text in ['🧠 Сброс', '🏠 Главное меню', '❌ Отмена']:
        user_pending_prompts[user_id] = None
        await update.message.reply_text("🏠 Главное меню", reply_markup=get_main_menu())
        return

    # 2. НОВОСТИ МОДЫ (С ИИ-САММАРИ)
    if text == '🗞 Новости моды':
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        loading_msg = await update.message.reply_text(
            "🔄 *Парсинг 8 мировых источников и создание дайджеста...*\nЭто займет 15-20 секунд.",
            parse_mode="Markdown"
        )
        
        try:
            # Получаем сырые данные из news_parser.py
            raw_news = await loop.run_in_executor(executor, get_fashion_news)
            
            if not raw_news:
                await loading_msg.edit_text("😢 Не удалось собрать новости. Попробуйте позже.")
                return

            # Формируем запрос для ИИ для создания красивого отчета
            final_prompt = [
                {"role": "system", "content": "Ты — профессиональный модный обозреватель. "
                                             "Я дам тебе JSON с новостями (заголовки и ссылки). "
                                             "Твоя задача: Составить краткий дайджест на РУССКОМ языке. "
                                             "Для каждой новости: Напиши яркий заголовок, краткое описание сути (2 предложения) "
                                             "и сохрани оригинальную ссылку. Используй Markdown для оформления (жирный текст, разделители)."},
                {"role": "user", "content": f"Сделай дайджест из этих данных:\n{json.dumps(raw_news, ensure_ascii=False)}"}
            ]
            
            final_report = await loop.run_in_executor(executor, _simple_text_gen, final_prompt)
            
            await loading_msg.delete()
            await update.message.reply_text(final_report, parse_mode="Markdown", disable_web_page_preview=False)
            
        except Exception as e:
            logger.error(f"Ошибка в блоке новостей: {e}")
            await loading_msg.edit_text("❌ Произошла ошибка при обработке новостей.")
        return

    # 3. Режим генерации (активный)
    is_generating = user_pending_prompts.get(user_id) is not None
    if is_generating:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        magic_msg = [
            {"role": "system", "content": "You are a Fashion Prompt Generator. Output ONLY English prompt."},
            {"role": "user", "content": text}
        ]
        refined = await loop.run_in_executor(executor, _simple_text_gen, magic_msg)
        user_pending_prompts[user_id] = refined
        await update.message.reply_text(f"✨ **Образ готов:**\n\n`{refined}`", 
                                       parse_mode="Markdown", reply_markup=get_size_keyboard())
        return

    # 4. Другие кнопки (Тренды и т.д.)
    if text in ['🚀 Тренды 2026', '🏃 Спорт-Эксперт', '👔 Одень меня']:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        messages = [{"role": "system", "content": "Ты эксперт моды 2026. Без разметки."}, {"role": "user", "content": text}]
        raw_res = await loop.run_in_executor(executor, _simple_text_gen, messages)
        await update.message.reply_text(_clean_text(raw_res))
        return

    # 5. Вход в режим генерации
    if text == '🎨 Создать промпт + Фото':
        user_pending_prompts[user_id] = "WAITING"
        await update.message.reply_text(
            "📽 **Режим генерации.**\nОпишите желаемый образ (например: 'в стиле киберпанк на неделе моды'):",
            reply_markup=ReplyKeyboardMarkup([['🏠 Главное меню']], resize_keyboard=True)
        )
        return

    # 6. Обычный чат
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    res = await loop.run_in_executor(executor, _simple_text_gen, [{"role": "user", "content": text}])
    await update.message.reply_text(_clean_text(res))

# Обработчик Callback-запросов и запуск бота остаются без изменений...
# (Скопируйте их из вашего предыдущего кода)
