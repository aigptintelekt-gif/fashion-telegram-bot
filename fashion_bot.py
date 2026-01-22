import os
import logging
import asyncio
import requests # Не забудьте добавить в импорты в начало файла
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# Telegram
from telegram import Update, constants
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# DashScope / OpenAI
from openai import OpenAI
import dashscope
from dashscope import ImageSynthesis
# Настройка для СИНГАПУРСКОГО региона (International)
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY") # Ваш ключ из этой консоли
dashscope.base_http_api_url = 'https://dashscope-intl.aliyuncs.com/api/v1'
# --- КОНФИГУРАЦИЯ ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
# ПРОВЕРКА: Напечатаем первые 5 символов ключа в консоль при запуске (для отладки)
if DASHSCOPE_API_KEY:
    print(f"Ключ загружен: {DASHSCOPE_API_KEY[:5]}***")
else:
    print("ОШИБКА: Ключ не найден в .env!")
dashscope.api_key = DASHSCOPE_API_KEY
# Проверка ключей
if not TELEGRAM_TOKEN or not DASHSCOPE_API_KEY:
    raise ValueError("ОШИБКА: Проверьте файл .env. Не найдены ключи!")

dashscope.api_key = DASHSCOPE_API_KEY

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Настройка клиента для текста (Qwen)
text_client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)

# Пул потоков для выполнения тяжелых запросов без блокировки бота
executor = ThreadPoolExecutor(max_workers=4)

# --- ПАМЯТЬ (Хранилище в оперативной памяти) ---
user_histories = {}
HISTORY_LIMIT = 10  # Сколько сообщений хранить

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (Синхронные) ---

def _generate_text_sync(messages):
    """Отправляет историю переписки в Qwen-Plus"""
    try:
        response = text_client.chat.completions.create(
            model="qwen-plus",
            messages=messages,
            temperature=0.7 # Сделаем ответы чуть более креативными
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Text Gen Error: {e}")
        return "Прости, произошла ошибка при генерации ответа."


import dashscope
from dashscope import ImageSynthesis

import requests
import json
import time

def _generate_image_sync(prompt):
    api_key = os.getenv("DASHSCOPE_API_KEY")
    # Правильный международный URL для создания задачи
    url = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json" # Включаем асинхронный режим
    }
    
    payload = {
        "model": "wan2.6-image",
        "input": {"prompt": prompt},
        "parameters": {"n": 1, "size": "1024*1024"}
    }

    try:
        logger.info(f"Отправка прямого запроса к API Intl... Prompt: {prompt[:30]}...")
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        
        if response.status_code != 200:
            logger.error(f"Ошибка API: {response.status_code} - {response.text}")
            return None
            
        result = response.json()
        # В синхронном ответе ссылка лежит здесь:
        image_url = result.get("output", {}).get("results", [{}])[0].get("url")
        
        if image_url:
            logger.info(f"Изображение готово: {image_url}")
            return image_url
        
        logger.error(f"Не удалось найти URL в ответе: {result}")
        return None
    except Exception as e:
        logger.error(f"Ошибка в генерации: {e}")
        return None
# --- ОБРАБОТЧИКИ TELEGRAM ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = [] # Сброс памяти при старте
    
    await update.message.reply_text(
        "Привет! Я твой личный ИИ-стилист.\n\n"
        "🧠 **Я помню наш диалог.** Просто пиши мне.\n"
        "✨ **Я могу создавать образы!** Запроси, например: `Покажи мужской трендовый образ зима 2026`.\n"
        "🔄 `/reset` — чтобы очистить память и начать новую тему."
    , parse_mode="Markdown")

async def reset_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("🧠 Память очищена! О чем поговорим теперь?")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    loop = asyncio.get_running_loop()

    if not user_text:
        return

    # 1. Список слов, которые сигнализируют о желании увидеть картинку
    image_keywords = ["пришли фото", "покажи фото", "нарисуй", "сгенерируй", "photo", "картинка", "фото:", "образ", "стиль"]
    
    # Проверяем, есть ли хоть одно слово из списка в сообщении пользователя
    # Игнорируем "фото:" здесь, т.к. его можно убрать отдельно ниже
    is_drawing_request = any(word in user_text.lower() for word in image_keywords)

    if is_drawing_request:
        # --- ЛОГИКА ДЛЯ ГЕНЕРАЦИИ ТЕКСТА + КАРТИНКИ ---
        await update.message.reply_chat_action(constants.ChatAction.TYPING) # Показываем "печатает..."
        
        # Подготавливаем промпт для текстовой модели, чтобы она сгенерировала описание
        # Если пользователь просил "пришли фото ...", убираем "пришли фото"
        text_generation_prompt = user_text
        for keyword in ["пришли фото", "покажи фото", "нарисуй", "сгенерируй", "photo:", "картинка:"]:
            text_generation_prompt = text_generation_prompt.lower().replace(keyword, "").strip()
        
        if not text_generation_prompt: # Если осталось пусто после очистки
            text_generation_prompt = user_text 
        
        # Добавляем инструкцию для стилиста
        full_text_prompt_messages = [
            {"role": "system", "content": "Ты модный стилист. Подробно опиши трендовый образ, который пользователь запросил. Не упоминай, что ты ИИ, и что ты не можешь показывать фото. Просто дай описание, как профессионал.Пиши кратко и по делу, не более 2000 знаков"},
            {"role": "user", "content": f"Опиши трендовый образ на тему: {text_generation_prompt}"}
        ]
    
        # Генерируем подробное текстовое описание
        # 1. Генерируем описание
        stylist_description = await loop.run_in_executor(executor, _generate_text_sync, full_text_prompt_messages)
        
        # 2. ОЧЕНЬ ВАЖНО: Безопасная отправка текста
        try:
            # Пытаемся отправить с Markdown
            await update.message.reply_text(stylist_description, parse_mode="Markdown")
        except Exception as e:
            # Если Markdown сломался (как в вашем логе), отправляем просто чистый текст
            logger.warning(f"Markdown error at offset, sending plain text: {e}")
            await update.message.reply_text(stylist_description, parse_mode=None)

        # 3. Переходим к генерации картинки
        await update.message.reply_chat_action(constants.ChatAction.UPLOAD_PHOTO)
        
        # Для промпта картинки лучше использовать короткую версию, 
        # чтобы модель не путалась в длинных описаниях
        image_prompt = f"Трендовый образ: {text_generation_prompt}. Professional fashion photography, male model, winter 2026 trend, high detail."
        
        image_url = await loop.run_in_executor(executor, _generate_image_sync, image_prompt)
        
        if image_url:
            await update.message.reply_photo(image_url, caption="✨ Визуализация вашего образа 2026")
        else:
            await update.message.reply_text("Не удалось сгенерировать изображение, но описание выше!")
        
        # Важно: После генерации фото и текста - очищаем историю для этой конкретной "фотки"
        # Чтобы дальнейший диалог не был засорен промптом стилиста
        if user_id in user_histories:
            user_histories[user_id] = [user_histories[user_id][0]] # Оставляем только системный промпт
        return

    # --- ЛОГИКА ТЕКСТА (если это просто беседа и не было запроса на картинку) ---
    if user_id not in user_histories:
        # Системный промпт для общего диалога
        user_histories[user_id] = [{
            "role": "system", 
            "content": "Ты полезный и умный ассистент. Отвечай на вопросы пользователя и веди диалог."
        }]

    user_histories[user_id].append({"role": "user", "content": user_text})
    
    # Ограничение памяти
    if len(user_histories[user_id]) > HISTORY_LIMIT:
        user_histories[user_id] = [user_histories[user_id][0]] + user_histories[user_id][-(HISTORY_LIMIT-1):]

    await update.message.reply_chat_action(constants.ChatAction.TYPING)
    bot_response = await loop.run_in_executor(executor, _generate_text_sync, user_histories[user_id])
    
    user_histories[user_id].append({"role": "assistant", "content": bot_response})
    
    try:
        await update.message.reply_text(bot_response, parse_mode="Markdown")
    except:
        await update.message.reply_text(bot_response)

# --- ЗАПУСК ---
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_memory))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Бот запущен! Нажмите Ctrl+C для остановки.")
    app.run_polling()
