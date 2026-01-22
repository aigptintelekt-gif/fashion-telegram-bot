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
# Если прямой импорт не срабатывает, используем более глубокий путь или вызов через основной модуль
try:
    from dashscope import MultiModalGeneration
except ImportError:
    # Резервный способ доступа к классу в некоторых версиях SDK
    MultiModalGeneration = dashscope.MultiModalGeneration

# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

dashscope.api_key = DASHSCOPE_API_KEY
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'

# Ограничим логирование для чистоты консоли Heroku
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
executor = ThreadPoolExecutor(max_workers=4)

# ... остальная часть кода остается прежней ...

def _generate_image_wan26(prompt, size, base_face_url=None):
    try:
        content_list = [{"text": f"{prompt}, European appearance, high fashion, 8k"}]
        if base_face_url:
            content_list.append({"image": base_face_url})

        # Используем вызов напрямую через dashscope.MultiModalGeneration
        responses = dashscope.MultiModalGeneration.call(
            model="wan2.6-image",
            input={
                "messages": [
                    {
                        "role": "user",
                        "content": content_list
                    }
                ]
            },
            parameters={
                "size": size,
                "n": 1,
                "prompt_extend": True
            }
        )

        if responses.status_code == HTTPStatus.OK:
            # Обработка вложенной структуры ответа
            image_url = responses.output.choices[0].message.content[0]["image"]
            return {"url": image_url, "error": None}
        else:
            return {"url": None, "error": f"API Error: {responses.message}"}
            
    except Exception as e:
        return {"url": None, "error": f"Runtime Error: {str(e)}"}
