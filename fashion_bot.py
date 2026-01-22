import os
import logging
import asyncio
import requests
import json
import time
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

# --- ИНИЦИАЛИЗАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

# Клиент для OpenAI-совместимого режима (Зрение и Текст)
client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

# --- МЕНЮ ---
def get_main_menu():
    keyboard = [['🚀 Тренды 2026', '👔 Одень меня'], ['🗞 Новости моды', '🧠 Сброс']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- ТЕХНИЧЕСКИЕ ФУНКЦИИ (СИНХРОННЫЕ) ---

def _analyze_photo_with_vision(photo_url, user_caption):
    """Qwen-VL анализирует фото и создает промпт для переодевания"""
    try:
        prompt = (
            f"Analyze this person. User wants: {user_caption}. "
            "Describe the person's ethnicity, hair color, and gender exactly as they appear. "
            "Then, create a highly detailed fashion prompt for 2026 autumn style. "
            "The prompt must be in English, focus on 'Full body shot, high fashion editorial'. "
            "Crucial: specify the ethnicity (e.g. Caucasian, Hispanic, etc.) to prevent default Asian features."
        )
        
        response = client.chat.completions.create(
            model="qwen-vl-plus",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": photo_url}}
                ],
            }]
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Vision error: {e}")
        return f"Fashion photography, 2026 trend, high detail, {user_caption}"

def _generate_face_ref_image(prompt, ref_image_url):
    """Генерация Wanx с использованием ссылки на лицо (Face Reference)"""
    try:
        # Режим face_ref позволяет сохранить лицо с оригинала
        rsp = ImageSynthesis.call(
            model="wanx-v1",
            prompt=f"{prompt}, realistic skin, masterwork, 8k",
            extra_input={"ref_image": ref_image_url},
            parameters={
                "ref_mode": "face_ref", # КЛЮЧЕВОЙ ПАРАМЕТР для сохранения лица
                "n": 1,
                "size": "1024*1024"
            }
        )
        if rsp.status_code == HTTPStatus.OK:
            return rsp.output.results[0].url
        logger.error(f"Wanx error: {rsp.message}")
        return None
    except Exception as e:
        logger.error(f"Generation error: {e}")
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
        return f"Ошибка: {e}"

# --- ОБРАБОТЧИКИ ТЕЛЕГРАМ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✨ **ИИ-стилист 2026 приветствует тебя!** ✨\n\n"
        "Я научился **сохранять твоё лицо** при переодевании. Просто пришли фото и напиши, что хочешь примерить!",
        reply_markup=get_main_menu(), parse_mode="Markdown"
    )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    caption = update.message.caption or "трендовый образ 2026"
    
    await update.message.reply_text("🔎 **Изучаю твою внешность и стиль...**")
    
    # Получаем путь к фото
    photo_file = await update.message.photo[-1].get_file()
    photo_url = photo_file.file_path # Ссылка для ИИ
    
    loop = asyncio.get_running_loop()
    
    # 1. Анализируем фото (Зрение)
    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    styled_prompt = await loop.run_in_executor(executor, _analyze_photo_with_vision, photo_url, caption)
    
    # 2. Генерируем новый лук с сохранением лица
    await update.message.reply_text("👗 **Примеряю новый образ... Сохраняю твои черты лица.**")
    await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
    
    final_image = await loop.run_in_executor(executor, _generate_face_ref_image, styled_prompt, photo_url)
    
    if final_image:
        await update.message.reply_photo(final_image, caption="🌟 Твой новый образ готов! \nЯ сохранил твоё лицо и адаптировал стиль под 2026 год. 😍")
    else:
        await update.message.reply_text("❌ Ошибка при примерке. Попробуй другое фото!")

from datetime import datetime

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    loop = asyncio.get_running_loop()
    now = datetime.now()
    current_date_str = now.strftime("%d января %Y года")

    if text == '🗞 Новости моды':
        # 1. Мгновенный ответ, чтобы пользователь не ждал
        await update.message.reply_text(
            f"👠 **Связываюсь с редакцией в Париже и Милане...**\n"
            f"Подбираю самые свежие материалы на {current_date_str}.\n"
            f"Как только подготовлю статью и ссылки — я сразу тебя оповещу! Подожди пару секунд... ⚡️"
        )
        
        await update.message.reply_chat_action(constants.ChatAction.TYPING)

        # Инструкция для ИИ
        news_prompt = [
            {"role": "system", "content": f"Ты фэшн-журналист. Напиши 3 новости моды на {current_date_str}. "
                                          "Каждая новость: Заголовок, краткий текст и ссылка на источник (Vogue, Hypebeast или BoF). "
                                          "НЕ используй символы '***'. Текст должен быть чистым и профессиональным."},
            {"role": "user", "content": "Дай сводку главных событий."}
        ]

        # 2. Генерируем текст всех новостей
        news_text = await loop.run_in_executor(executor, _simple_text_gen, news_prompt)
        
        # Разбиваем на блоки по новостям
        news_blocks = [block.strip() for block in news_text.split('\n\n') if len(block.strip()) > 20][:3]

        # 3. Цикл отправки: картинка + текст для каждой новости
        for i, block in enumerate(news_blocks, 1):
            await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
            
            # Берем первую строку блока как тему для генерации фото
            topic = block.split('\n')[0]
            img_url = await loop.run_in_executor(executor, _generate_image_sync, f"Professional fashion photography, 2026 trend: {topic}")

            if img_url:
                await update.message.reply_photo(
                    img_url, 
                    caption=f"📰 **Новость №{i}**\n\n{block}", 
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(f"📰 **Новость №{i}**\n\n{block}", parse_mode="Markdown")
            
            # Небольшая пауза, чтобы Telegram не заблокировал за спам
            await asyncio.sleep(1)

        await update.message.reply_text("✅ **Дайджест на сегодня готов!** Приятного чтения. ☕️👠")
        return

    # Остальная логика (Тренды, Фото и прочее)...
    # Остальная логика (Тренды, Фото и т.д.) без изменений...

# --- ЗАПУСК ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🚀 Бот-стилист 'Face-Keep' запущен!")
    app.run_polling()
