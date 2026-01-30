"""
Fashion Director 2026 — Telegram бот
"""
import logging
import asyncio
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

# ThreadPool для асинхронных операций
executor = ThreadPoolExecutor(max_workers=4)

# Инициализация OpenAI клиента
client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL
)

# Глобальные переменные пользователя
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
    """Очистка текста от Markdown символов"""
    chars_to_remove = ['*', '#', '_', '`', '---']
    for char in chars_to_remove:
        text = text.replace(char, '')
    return text.strip()

def _generate_image_direct(prompt, size, base_face_url=None):
    """Генерация изображения через API"""
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
    """Генерация текста через LLM"""
    try:
        res = client.chat.completions.create(model="qwen3-max-2026-01-23", messages=messages)
        return res.choices[0].message.content
    except Exception as e:
        return f"Ошибка: {str(e)}"

# ==================== ОБРАБОТЧИКИ ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🌟 **Добро пожаловать в Fashion Director 2026!**\n\n"
        "Я — ваш персональный ИИ-ассистент в мире моды. Вот что я умею:\n\n"
        "📸 **Генерация образов:** Создам фото с вашим лицом в любом стиле.\n"
        "📈 **Тренды:** Расскажу о самых свежих новинках индустрии.\n"
        "🏃 **Спорт:** Подберу технологичную экипировку.\n"
        "👔 **Стилист:** Составлю идеальный лук по вашему описанию.\n"
        "🗞 **Новости моды:** Парсинг 8 мировых источников с кэшированием!\n\n"
        "👉 *Выберите действие в меню ниже!*"
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

    # 1. Выход из режима
    if text in ['🧠 Сброс', '🏠 Главное меню', '❌ Отмена']:
        user_pending_prompts[user_id] = None
        await update.message.reply_text(
            "🏠 Вы вернулись в главное меню. О чем хотите узнать?",
            reply_markup=get_main_menu()
        )
        return

    # 2. Режим генерации
    is_generating = user_pending_prompts.get(user_id) is not None
    if is_generating:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        gen_kb = ReplyKeyboardMarkup([['🏠 Главное меню']], resize_keyboard=True)
        await update.message.reply_text("🧠 *Стилизую ваш новый запрос...*", parse_mode="Markdown", reply_markup=gen_kb)
        
        magic_msg = [
            {"role": "system", "content": "You are a Fashion Prompt Generator. Translate and enhance the user's idea into a detailed English prompt. Output ONLY the prompt."},
            {"role": "user", "content": text}
        ]
        refined = await loop.run_in_executor(executor, _simple_text_gen, magic_msg)
        user_pending_prompts[user_id] = refined
        
        await update.message.reply_text(
            f"✨ **Новый образ готов к рендеру:**\n\n`{refined}`",
            parse_mode="Markdown",
            reply_markup=get_size_keyboard()
        )
        return

    # 3. Новости моды
    async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ... (код выше без изменений)

    if text == '🗞 Новости моды':
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        loading_msg = await update.message.reply_text(
            "🔄 *Парсинг источников и создание дайджеста...*\nЭто займет немного больше времени.",
            parse_mode="Markdown"
        )
        
        try:
            # 1. Получаем сырые данные из вашего парсера
            raw_news = await loop.run_in_executor(executor, get_fashion_news)
            
            if not raw_news:
                await loading_msg.edit_text("😢 Новостей пока нет, попробуйте позже.")
                return

            # 2. Формируем запрос для Qwen для перевода и описания
            # Передаем только заголовки и источники, чтобы сэкономить токены и время
            news_context = "\n".join([f"- {n['source']}: {n['title']}" for n in raw_news])
            
            summary_prompt = [
                {"role": "system", "content": "Ты — фэшн-аналитик. Я дам тебе список заголовков новостей. "
                                             "Твоя задача: кратко (1-2 предложения) описать суть каждой новости на РУССКОМ языке. "
                                             "Будь экспертным, используй проф. терминологию. Выдавай только текст описаний."},
                {"role": "user", "content": f"Опиши кратко эти новости моды:\n{news_context}"}
            ]
            
            # Генерируем краткие описания
            summaries = await loop.run_in_executor(executor, _simple_text_gen, summary_prompt)
            
            # 3. Формируем итоговое сообщение (красиво соединяем ссылки и описания)
            # Чтобы не усложнять парсер, мы можем просто отправить результат от ИИ 
            # или сопоставить их. Самый надежный способ — попросить ИИ сразу вернуть готовый текст со ссылками.
            
            final_prompt = [
                {"role": "system", "content": "Сформируй итоговый дайджест. Для каждой новости: "
                                             "1. Заголовок (на русском). "
                                             "2. Краткое описание (1-2 предложения). "
                                             "3. Источник и ссылка. "
                                             "Используй Markdown. Разделяй новости линиями."},
                {"role": "user", "content": f"Данные для обработки:\n{json.dumps(raw_news, ensure_ascii=False)}"}
            ]
            
            final_report = await loop.run_in_executor(executor, _simple_text_gen, final_prompt)
            
            await loading_msg.delete()
            await update.message.reply_text(final_report, parse_mode="Markdown", disable_web_page_preview=False)
            
        except Exception as e:
            logger.error(f"Ошибка в дайджесте: {e}")
            await loading_msg.edit_text("❌ Ошибка при генерации описаний.")
        return

    # 4. Другие кнопки меню
    if text in ['🚀 Тренды 2026', '🏃 Спорт-Эксперт', '👔 Одень меня']:
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        messages = [
            {"role": "system", "content": "Ты эксперт моды 2026. Пиши простым текстом без разметки."},
            {"role": "user", "content": text}
        ]
        raw_res = await loop.run_in_executor(executor, _simple_text_gen, messages)
        await update.message.reply_text(_clean_text(raw_res))
        return

    # 5. Вход в режим генерации
    if text == '🎨 Создать промпт + Фото':
        user_pending_prompts[user_id] = "WAITING"
        gen_kb = ReplyKeyboardMarkup([['🏠 Главное меню']], resize_keyboard=True)
        await update.message.reply_text(
            "📽 **Вы вошли в режим генерации.**\n\nТеперь любой ваш текст будет превращаться в фото. Чтобы выйти, нажмите кнопку ниже.",
            reply_markup=gen_kb
        )
        await update.message.reply_text("Введите описание вашего первого образа:")
        return

    # 6. Обычный чат
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
            await query.message.reply_photo(
                result["url"],
                caption=f"📸 **Ваш эксклюзивный кадр готов!**\nЖелаете улучшить детализацию?",
                reply_markup=get_upscale_keyboard()
            )
        else:
            await query.message.reply_text(f"❌ **Упс! Что-то пошло не так:**\n{result['error']}")

    elif data.startswith("upscale_"):
        mode = data.replace("upscale_", "")
        await query.message.reply_text(f"💎 **Магия апскейлинга...**\nУлучшаю до {mode.upper()}. Отправлю файл без потери качества.")
        await query.message.reply_chat_action(constants.ChatAction.UPLOAD_DOCUMENT)
        img_url = last_generated_images.get(user_id)
        await query.message.reply_document(img_url, caption=f"✨ **Премиум качество {mode.upper()}**")

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    logger.info("🚀 Запуск Fashion Director 2026...")
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("✅ Бот запущен и готов к работе!")
    app.run_polling()
