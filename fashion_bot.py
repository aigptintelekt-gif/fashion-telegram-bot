"""
Fashion Director 2026 — Интеллектуальный ассистент
Главный модуль управления ботом.
"""

import logging
import asyncio
import requests
import json
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI

# Telegram API
from telegram import Update, constants, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Импорт ваших настроек и парсера
from config import *
from news_parser import get_fashion_news

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, LOG_LEVEL)
)
logger = logging.getLogger(__name__)

# Пул потоков для тяжелых задач (генерация, парсинг), чтобы бот не «зависал»
executor = ThreadPoolExecutor(max_workers=4)

# Инициализация клиента ИИ (Qwen через DashScope)
client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL
)

# Хранилище состояний (в продакшене лучше использовать БД или Redis)
user_faces = {}             # Ссылка на фото лица пользователя
user_pending_prompts = {}   # Текущий промпт для генерации
last_generated_images = {}  # Ссылка на последнее созданное изображение

# ==================== КЛАВИАТУРЫ ====================

def get_main_menu():
    """Главное навигационное меню"""
    keyboard = [
        ['🚀 Тренды 2026', '🏃 Спорт-Эксперт'],
        ['🎨 Создать промпт + Фото', '🗞 Новости моды'],
        ['👔 Одень меня', '🧠 Сброс']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_size_keyboard():
    """Выбор формата изображения"""
    keyboard = [
        [InlineKeyboardButton("Квадрат (1:1)", callback_data="size_1024*1024")],
        [InlineKeyboardButton("Портрет (3:4)", callback_data="size_768*1024")],
        [InlineKeyboardButton("Stories/Reels (9:16)", callback_data="size_720*1280")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_upscale_keyboard():
    """Меню улучшения качества"""
    keyboard = [
        [InlineKeyboardButton("💎 Улучшить до 2K", callback_data="upscale_2k"),
         InlineKeyboardButton("👑 Улучшить до 4K", callback_data="upscale_4k")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ==================== СИСТЕМНЫЕ ФУНКЦИИ ====================

def _simple_text_gen(messages):
    """Универсальная функция для общения с LLM"""
    try:
        res = client.chat.completions.create(
            model="qwen3-max-2026-01-23",  # Или ваша актуальная модель в DashScope
            messages=messages
        )
        return res.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM Error: {e}")
        return f"⚠️ Ошибка ИИ: {str(e)}"

def _generate_image_direct(prompt, size, base_face_url=None):
    """Запрос к модели генерации изображений (Wan 2.6)"""
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DASHSCOPE_API_KEY}"}
    
    # Конструируем контент (текст + опционально фото лица)
    content = [{"text": f"{prompt}, high fashion photography, highly detailed, 8k resolution"}]
    if base_face_url:
        content.append({"image": base_face_url})

    data = {
        "model": "wan2.6-image",
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {"prompt_extend": True, "n": 1, "size": size}
    }
    
    try:
        response = requests.post(IMAGE_API_URL, headers=headers, json=data, timeout=120)
        res_json = response.json()
        return {"url": res_json["output"]["choices"][0]["message"]["content"][0]["image"], "error": None}
    except Exception as e:
        return {"url": None, "error": str(e)}

# ==================== ОБРАБОТЧИКИ СООБЩЕНИЙ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие при запуске /start"""
    welcome_text = (
        "🌟 **Fashion Director 2026**\n"
        "————————————————\n"
        "Ваш персональный аналитик и дизайнер в мире высокой моды.\n\n"
        "✨ **Что я умею:**\n"
        "• Генерировать образы с вашим лицом (просто пришлите фото!)\n"
        "• Писать аналитические обзоры мировых новостей\n"
        "• Прогнозировать тренды на 2026 год\n\n"
        "🗞 *Нажмите на кнопку новостей, чтобы получить свежий дайджест.*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=get_main_menu())

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение лица пользователя для генераций"""
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    photo_file = await update.message.photo[-1].get_file()
    user_faces[update.effective_user.id] = photo_file.file_path
    await update.message.reply_text("👤 **Face-ID подтвержден!**\nТеперь я буду использовать ваше лицо при создании образов.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основная логика обработки текстовых команд"""
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()

    # 1. Системные команды
    if text in ['🧠 Сброс', '🏠 Главное меню']:
        user_pending_prompts[user_id] = None
        await update.message.reply_text("🏠 Мы в главном меню.", reply_markup=get_main_menu())
        return

    # 2. ИНТЕЛЛЕКТУАЛЬНЫЕ НОВОСТИ (Главная фишка)
    if text == '🗞 Новости моды':
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        load_msg = await update.message.reply_text("🔍 *Парсинг мировых подиумов и новостных лент...*", parse_mode="Markdown")
        
        try:
            # Получаем сырые ссылки через ваш парсер
            raw_news = await loop.run_in_executor(executor, get_fashion_news)
            
            if not raw_news:
                await load_msg.edit_text("📭 На данный момент новых событий не зафиксировано."); return

            # Отправляем данные в ИИ для перевода и создания описаний
            ai_prompt = [
                {"role": "system", "content": "Ты — ведущий аналитик моды. Я дам тебе JSON с новостями. "
                                             "Создай из них стильный дайджест на РУССКОМ языке. "
                                             "Для каждой новости: переведи заголовок, напиши 2 предложения сути "
                                             "и сохрани оригинальную ссылку. Используй Markdown (жирный текст, разделители)."},
                {"role": "user", "content": f"Данные: {json.dumps(raw_news, ensure_ascii=False)}"}
            ]
            
            summary = await loop.run_in_executor(executor, _simple_text_gen, ai_prompt)
            await load_msg.delete()
            await update.message.reply_text(summary, parse_mode="Markdown", disable_web_page_preview=False)
            
        except Exception as e:
            logger.error(f"News Error: {e}")
            await load_msg.edit_text("❌ Ошибка при формировании дайджеста.")
        return

    # 3. Режим генерации (активный)
    if user_pending_prompts.get(user_id) == "WAITING":
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        # Переводим и улучшаем запрос пользователя через ИИ
        magic_msg = [
            {"role": "system", "content": "Translate fashion prompt to English and make it more professional for image generation. ONLY output English text."},
            {"role": "user", "content": text}
        ]
        refined_prompt = await loop.run_in_executor(executor, _simple_text_gen, magic_msg)
        user_pending_prompts[user_id] = refined_prompt
        
        await update.message.reply_text(
            f"✨ **Стилизация готова:**\n`{refined_prompt}`\n\nВыберите формат кадра:",
            parse_mode="Markdown", reply_markup=get_size_keyboard()
        )
        return

    # 4. Вход в режим генерации
    if text == '🎨 Создать промпт + Фото':
        user_pending_prompts[user_id] = "WAITING"
        await update.message.reply_text(
            "📽 **Студия дизайна 2026**\n\nОпишите образ, который хотите увидеть. Я дополню его деталями и сгенерирую фото.",
            reply_markup=ReplyKeyboardMarkup([['🏠 Главное меню']], resize_keyboard=True)
        )
        return

    # 5. Прочие аналитические запросы
    if text in ['🚀 Тренды 2026', '🏃 Спорт-Эксперт', '👔 Одень меня']:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        messages = [{"role": "system", "content": "Ты эксперт моды 2026. Отвечай кратко и профессионально на русском."},
                    {"role": "user", "content": text}]
        response = await loop.run_in_executor(executor, _simple_text_gen, messages)
        await update.message.reply_text(response)
        return

    # 6. Свободное общение
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    chat_res = await loop.run_in_executor(executor, _simple_text_gen, [{"role": "user", "content": text}])
    await update.message.reply_text(chat_res)

# ==================== ОБРАБОТЧИК КНОПОК (CALLBACK) ====================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data.startswith("size_"):
        size = data.replace("size_", "")
        await query.edit_message_text(f"🎨 **Рендеринг образа ({size})...**")
        
        prompt = user_pending_prompts.get(user_id)
        face_url = user_faces.get(user_id)
        
        # Запуск генерации
        result = await asyncio.get_running_loop().run_in_executor(executor, _generate_image_direct, prompt, size, face_url)
        
        if result["url"]:
            last_generated_images[user_id] = result["url"]
            await query.message.reply_photo(
                result["url"], 
                caption="📸 **Ваш эксклюзивный концепт готов!**",
                reply_markup=get_upscale_keyboard()
            )
        else:
            await query.message.reply_text(f"❌ Ошибка генерации: {result['error']}")

    elif data.startswith("upscale_"):
        # Логика отправки документа (без сжатия)
        img_url = last_generated_images.get(user_id)
        await query.message.reply_document(img_url, caption="✨ Версия в высоком качестве (без сжатия)")

# ==================== ЗАПУСК БОТА ====================

if __name__ == "__main__":
    logger.info("🚀 Fashion Director 2026 поднимает системы...")
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Регистрация обработчиков
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("✅ Бот в эфире!")
    app.run_polling()
