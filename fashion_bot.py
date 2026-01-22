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

# --- ЛИЧНОСТЬ: КРЕАТИВНЫЙ ДИРЕКТОР СЪЕМОК ---
STYLIST_PERSONALITY = (
    "Ты — Fashion-директор и ведущий стилист на съемочной площадке. Твоя специализация: Sport-Tech и Active Luxury. "
    "Ты мыслишь кадрами, освещением и текстурами. Твой стиль общения: экспертный, лаконичный, с использованием "
    "профессионального сленга (look, layering, silhouette, set design). "
    "Всегда ориентируешься на европейские модели и премиальный уровень исполнения."
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
    try:
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

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = [{"role": "system", "content": STYLIST_PERSONALITY}]
    context.user_data['mode'] = 'normal'
    
    await update.message.reply_text(
        "🎬 **Creative Director на площадке.**\n\nГотов к созданию визуального контента уровня 2026 года. "
        "Используй меню для аналитики или выбери режим генерации промптов для съемок.",
        reply_markup=get_main_menu(), parse_mode="Markdown"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    loop = asyncio.get_running_loop()
    current_mode = context.user_data.get('mode', 'normal')

    if text == '🧠 Сброс':
        user_histories[user_id] = [{"role": "system", "content": STYLIST_PERSONALITY}]
        context.user_data['mode'] = 'normal'
        await update.message.reply_text("🧠 Площадка очищена. Жду новых задач.", reply_markup=get_main_menu())
        return

    # РЕЖИМ ПРОФЕССИОНАЛЬНОГО ПРОМПТА
    if text == '🎨 Создать промпт + Фото':
        context.user_data['mode'] = 'prompt_gen'
        await update.message.reply_text("📽 **Опиши концепцию съемки.**\nЯ разработаю техническое задание для камеры и стилизацию кадра.")
        return

    if current_mode == 'prompt_gen':
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        
        # 1. Генерация промпта + совета
        combined_prompt = [
            {"role": "system", "content": (
                "You are a Creative Director for a high-end fashion shoot. "
                "Step 1: Generate a technical English prompt for an AI image generator. "
                "Specify: European model, Phase One XF camera, 80mm lens, studio or urban tech lighting, "
                "detailed fabric textures (Gore-Tex, technical silk). "
                "Step 2: Add a short 'Backstage Advice' in Russian for the stylist on set. "
                "Format: [PROMPT] text [/PROMPT] [ADVICE] text [/ADVICE]"
            )},
            {"role": "user", "content": text}
        ]
        
        raw_res = await loop.run_in_executor(executor, _simple_text_gen, combined_prompt)
        
        # Парсинг ответа
        try:
            p_start, p_end = raw_res.find("[PROMPT]") + 8, raw_res.find("[/PROMPT]")
            a_start, a_end = raw_res.find("[ADVICE]") + 8, raw_res.find("[/ADVICE]")
            refined_text = raw_res[p_start:p_end].strip()
            advice_text = raw_res[a_start:a_end].strip()
        except:
            refined_text, advice_text = raw_res, "Держи фокус на динамике образа."

        # Отправка промпта и совета
        await update.message.reply_text(f"✨ **Technical Prompt:**\n\n`{refined_text}`", parse_mode="Markdown")
        await update.message.reply_text(f"💡 **Совет со съемок:**\n_{advice_text}_", parse_mode="Markdown")
        
        # 2. Генерация изображения
        await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        img_url = await loop.run_in_executor(executor, _generate_image_sync, refined_text)
        
        if img_url:
            await update.message.reply_photo(img_url, caption="📸 Финальный кадр (Shot on Set 2026)")
        return

    # ОБЫЧНАЯ ЛОГИКА (ТРЕНДЫ, СПОРТ И Т.Д.)
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    if user_id not in user_histories:
        user_histories[user_id] = [{"role": "system", "content": STYLIST_PERSONALITY}]
    
    user_histories[user_id].append({"role": "user", "content": text})
    bot_response = await loop.run_in_executor(executor, _simple_text_gen, user_histories[user_id])
    
    await update.message.reply_text(bot_response, parse_mode="Markdown" if "*" in bot_response else None)
    
    # Авто-фото для спорта или при упоминании фото
    if any(kw in text.lower() for kw in ["фото", "образ", "style"]) or context.user_data.get('mode') == 'sport':
        await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        img_url = await loop.run_in_executor(executor, _generate_image_sync, f"Caucasian European model, fashion photography, {bot_response[:200]}")
        if img_url:
            await update.message.reply_photo(img_url, caption="🎬 Визуализация лука")

# (Функции handle_photo и прочие остаются из предыдущих версий)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # Не забудь добавить app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("🚀 Режим Съемки активирован!")
    app.run_polling()
