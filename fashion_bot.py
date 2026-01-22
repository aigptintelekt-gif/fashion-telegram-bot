import os
import logging
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from http import HTTPStatus

# Telegram
from telegram import Update, constants, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# DashScope / OpenAI
from openai import OpenAI
import dashscope
from dashscope import ImageSynthesis

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

# --- ПАМЯТЬ И ЛИЧНОСТЬ ---
user_histories = {}
HISTORY_LIMIT = 8

STYLIST_PERSONALITY = (
    "Ты — ведущий эксперт в Sport-Tech моде и Active Luxury. Твой фокус: кроссовки, умные ткани, мембраны. "
    "Стиль: лаконичный, профессиональный. НЕ используй '***' и много эмодзи. "
    "Ты всегда фокусируешься на европейских типажах внешности (Caucasian features)."
)

# --- МЕНЮ ---
def get_main_menu():
    keyboard = [
        ['🚀 Тренды 2026', '🏃 Спорт-Эксперт'],
        ['🎨 Создать промпт + Фото', '🗞 Новости моды'],
        ['👔 Одень меня', '🧠 Сброс']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- ТЕХНИЧЕСКИЕ ФУНКЦИИ ---

def _simple_text_gen(messages):
    """Базовая функция генерации текста через Qwen-Plus"""
    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Text Error: {e}")
        return "Ошибка при генерации текста."

def _generate_image_sync(prompt):
    """Генерация изображения через qwen-image-plus"""
    try:
        # Промпт уже приходит улучшенным от текстовой модели
        rsp = ImageSynthesis.call(
            model="qwen-image-plus",
            prompt=prompt,
            n=1,
            size='1024*1024'
        )
        if rsp.status_code == HTTPStatus.OK:
            return rsp.output.results[0].url
        return None
    except Exception as e:
        logger.error(f"Image Error: {e}")
        return None

def _analyze_photo_with_vision(photo_url, user_caption):
    """Анализ фото через Qwen-VL-Plus"""
    try:
        response = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Analyze this person and suggest a 2026 style makeover (Caucasian/European style). Request: {user_caption}"},
                    {"type": "image_url", "image_url": {"url": photo_url}}
                ],
            }]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Vision error: {e}")
        return f"Fashion trend 2026, {user_caption}"

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = [{"role": "system", "content": STYLIST_PERSONALITY}]
    context.user_data['mode'] = 'normal'
    
    await update.message.reply_text(
        "✨ **ИИ-Стилист 2026 готов к работе.**\n\nЯ помогу тебе создать профессиональный образ. "
        "Теперь я использую улучшенные промпты для генерации европейских моделей.",
        reply_markup=get_main_menu(), parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.caption or "трендовый образ"
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    await update.message.reply_text("📸 Анализирую внешность...")
    
    photo_file = await update.message.photo[-1].get_file()
    photo_url = photo_file.file_path
    loop = asyncio.get_running_loop()

    analysis = await loop.run_in_executor(executor, _analyze_photo_with_vision, photo_url, caption)
    await update.message.reply_text(f"🔍 **Анализ:**\n\n{analysis}")
    
    await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
    img_url = await loop.run_in_executor(executor, _generate_image_sync, f"Caucasian European model, {analysis}")
    if img_url:
        await update.message.reply_photo(img_url, caption="🌟 Твой новый образ")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()
    current_mode = context.user_data.get('mode', 'normal')

    # СБРОС И КНОПКИ
    if text == '🧠 Сброс':
        user_histories[user_id] = [{"role": "system", "content": STYLIST_PERSONALITY}]
        context.user_data['mode'] = 'normal'
        await update.message.reply_text("🧠 Память очищена.", reply_markup=get_main_menu())
        return

    if text == '🏃 Спорт-Эксперт':
        context.user_data['mode'] = 'sport'
        await update.message.reply_text("🏃 Режим Sport-Tech активирован. Жду вопросы о трендах и новостях.")
        return

    # НОВЫЙ РЕЖИМ: ПРОМПТ-ИНЖЕНЕР
    if text == '🎨 Создать промпт + Фото':
        context.user_data['mode'] = 'prompt_gen'
        await update.message.reply_text("📝 **Пришли идею для образа.**\nЯ превращу её в качественный промпт и создам фото (European Style).")
        return

    # Логика работы в режиме prompt_gen
    if current_mode == 'prompt_gen':
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        
        # 1. Текстовая модель делает "Магическое улучшение"
        magic_prompt = [
            {"role": "system", "content": (
                "You are an expert AI Prompt Engineer for fashion photography. "
                "Transform the user's idea into a detailed professional English prompt. "
                "CRITICAL: Always specify 'Caucasian features, European model'. "
                "Add details: lighting (softbox or sunset), camera (Sony A7R IV, 85mm), clothing materials. "
                "Return ONLY the English text of the prompt."
            )},
            {"role": "user", "content": text}
        ]
        refined_text = await loop.run_in_executor(executor, _simple_text_gen, magic_prompt)
        
        # Показываем промпт пользователю для удобства
        await update.message.reply_text(f"✨ **Сгенерированный промпт:**\n\n`{refined_text}`", parse_mode="Markdown")
        
        # 2. Модель генерации сразу рисует фото
        await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        img_url = await loop.run_in_executor(executor, _generate_image_sync, refined_text)
        
        if img_url:
            await update.message.reply_photo(img_url, caption="✅ Образ по вашему запросу готов.")
        else:
            await update.message.reply_text("❌ Ошибка при создании фото.")
        return

    # ОБЫЧНАЯ ЛОГИКА ДИАЛОГА
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    if user_id not in user_histories:
        user_histories[user_id] = [{"role": "system", "content": STYLIST_PERSONALITY}]

    user_histories[user_id].append({"role": "user", "content": text})
    
    bot_response = await loop.run_in_executor(executor, _simple_text_gen, user_histories[user_id])
    
    try:
        await update.message.reply_text(bot_response, parse_mode="Markdown")
    except:
        await update.message.reply_text(bot_response)

    # Если в обычном режиме или спорте попросили фото
    image_keywords = ["фото", "нарисуй", "образ", "стиль", "photo"]
    if any(kw in text.lower() for kw in image_keywords) or current_mode == 'sport':
        await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        img_url = await loop.run_in_executor(executor, _generate_image_sync, f"Caucasian European model, {bot_response[:200]}")
        if img_url:
            await update.message.reply_photo(img_url, caption="📊 Визуализация идеи")

    # Обновление истории
    user_histories[user_id].append({"role": "assistant", "content": bot_response})
    if len(user_histories[user_id]) > HISTORY_LIMIT:
        user_histories[user_id] = [user_histories[user_id][0]] + user_histories[user_id][-(HISTORY_LIMIT-1):]

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🚀 Бот запущен! Промпт-инженер и европейские модели активны.")
    app.run_polling()
