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

# --- ЛИЧНОСТЬ СПОРТ-ЭКСПЕРТА ---
STYLIST_PERSONALITY = (
    "Ты — эксперт в Sport-Tech моде. Твой фокус: кроссовки, мембраны, носимые технологии и Active Luxury. "
    "Стиль: лаконичный, без лишних эмодзи и без символов '***'. "
    "Если тебя просят прислать тренд или новость — пиши профессионально и коротко."
)

# --- МЕНЮ ---
def get_main_menu():
    keyboard = [
        ['🚀 Тренды 2026', '🏃 Спорт-Эксперт'],
        ['👔 Одень меня', '🗞 Новости моды'],
        ['🧠 Сброс']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- ФУНКЦИИ ГЕНЕРАЦИИ ---

def _generate_image_sync(prompt):
    try:
        # Используем wan2.6 или wanx-v1 в зависимости от доступности
        rsp = ImageSynthesis.call(
            model="wanx-v1", 
            prompt=f"{prompt}, high-tech sportswear, professional photography, 8k",
            n=1,
            size='1024*1024'
        )
        if rsp.status_code == HTTPStatus.OK:
            return rsp.output.results[0].url
        return None
    except Exception as e:
        logger.error(f"Image Error: {e}")
        return None

def _simple_text_gen(messages):
    try:
        response = client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Ошибка связи: {e}"

# --- ОБРАБОТЧИКИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['mode'] = 'normal'
    await update.message.reply_text(
        "✨ **ИИ-стилист 2026 приветствует тебя!**\n\nВыбери режим работы в меню ниже.",
        reply_markup=get_main_menu(), parse_mode="Markdown"
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_mode = context.user_data.get('mode', 'normal')
    loop = asyncio.get_running_loop()
    current_date = datetime.now().strftime("%d %B %Y")

    # 1. ПЕРЕКЛЮЧЕНИЕ В РЕЖИМ СПОРТ-ЭКСПЕРТА
    if text == '🏃 Спорт-Эксперт':
        context.user_data['mode'] = 'sport'
        await update.message.reply_text(
            "🏃 **Режим Спорт-Эксперта активирован.**\n\n"
            "Я на связи. Спрашивай о трендах, новостях индустрии или технологиях. "
            "Например: 'Пришли тренд и новость на сегодня'.",
            reply_markup=get_main_menu()
        )
        return

    # 2. СБРОС
    if text == '🧠 Сброс':
        context.user_data['mode'] = 'normal'
        await update.message.reply_text("🧠 Память очищена, режим сброшен до стандартного.", reply_markup=get_main_menu())
        return

    # 3. ДИАЛОГ В РЕЖИМЕ СПОРТ-ЭКСПЕРТА
    if user_mode == 'sport':
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        
        prompt = [
            {"role": "system", "content": STYLIST_PERSONALITY},
            {"role": "user", "content": f"Сегодня {current_date}. Запрос пользователя: {text}. Выполни его кратко и экспертно."}
        ]
        
        res_text = await loop.run_in_executor(executor, _simple_text_gen, prompt)
        
        # Сначала отправляем текст
        await update.message.reply_text(f"🏅 **Sport-Analytic:**\n\n{res_text}")
        
        # Затем автоматически генерируем иллюстрацию к ответу
        await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        img_url = await loop.run_in_executor(executor, _generate_image_sync, f"Futuristic sport fashion concept based on: {res_text[:100]}")
        
        if img_url:
            await update.message.reply_photo(img_url, caption="📊 Визуализация концепта")
        return

    # 4. ОБЫЧНАЯ ЛОГИКА (НОВОСТИ, ТРЕНДЫ)
    if text == '🗞 Новости моды':
        # ... (код из прошлых этапов)
        await update.message.reply_text("👠 Загружаю общие новости моды...")
        # (здесь твой старый код для новостей)
        
    elif text == '🚀 Тренды 2026':
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        res = await loop.run_in_executor(executor, _simple_text_gen, [{"role": "user", "content": "3 тренда моды 2026"}])
        await update.message.reply_text(res)

    else:
        # Обычный чат
        await update.message.reply_chat_action(constants.ChatAction.TYPING)
        res = await loop.run_in_executor(executor, _simple_text_gen, [{"role": "user", "content": text}])
        await update.message.reply_text(res)

# Обработчик фото остается без изменений (handle_photo)
# ...

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # Добавь сюда handle_photo из предыдущего кода
    app.run_polling()
