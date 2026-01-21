# ----------------- imports -----------------
from dotenv import load_dotenv
import os
from pathlib import Path
import base64
import io
import requests

# Telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.constants import ChatAction

# Pillow для уменьшения фото
from PIL import Image

# ----------------- .env -----------------
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

print("Файл существует?", env_path.exists())
if env_path.exists():
    print("Содержимое файла:", env_path.read_text())

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

print("TELEGRAM_TOKEN:", TELEGRAM_TOKEN)
print("DASHSCOPE_API_KEY:", DASHSCOPE_API_KEY)

if not TELEGRAM_TOKEN or not DASHSCOPE_API_KEY:
    raise ValueError("❌ Не найдены токены! Проверь файл .env")

# ----------------- DashScope API -----------------
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

QWEN_MODEL_NAME = "qwen-vl-max"  # или другая модель, например qwen-vl-plus

# ----------------- System Prompt -----------------
FASHION_SYSTEM_PROMPT = """Ты — экспертный AI-агент в области fashion-индустрии, сочетающий роли профессионального стилиста и продюсера.

🎨 КАК СТИЛИСТ:
- Анализируй образы с профессиональной точки зрения
- Давай конкретные, применимые советы по стилю
- Учитывай типы фигур, цветотипы, lifestyle клиента
- Создавай капсульные гардеробы и луки
- Рекомендуй сочетания вещей и аксессуаров
- Следи за актуальными трендами

🎬 КАК ПРОДЮСЕР:
- Помогай планировать fashion-проекты
- Консультируй по бюджету и таймингу съемок
- Давай советы по выбору команды
- Помогай с концепцией и настроением проекта
- Консультируй по локациям и реквизиту

СТИЛЬ ОБЩЕНИЯ:
- Профессиональный, дружелюбный, вдохновляющий
- Используй модную терминологию, но объясняй сложные понятия
- Будь конкретным
- Эмодзи умеренно (✨, 👗, 💫, 🎨)

При анализе фото:
- Детально описывай что видишь
- Выделяй удачные элементы
- Предлагай улучшения тактично
- Рекомендуй конкретные альтернативы
"""

# ----------------- Хранилище истории -----------------
user_conversations = {}

# ----------------- Вспомогательная функция для вызова Qwen API -----------------
def call_qwen_api(messages, is_vision=False):
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": QWEN_MODEL_NAME,
        "input": {
            "messages": messages
        },
        "parameters": {
            "temperature": 0.7,
            "max_tokens": 1024,
            "top_p": 0.9
        }
    }

    response = requests.post(DASHSCOPE_BASE_URL, headers=headers, json=payload)
    response.raise_for_status()
    result = response.json()

    # Извлечение текста из ответа (может отличаться, проверьте документацию)
    text = result.get('output', {}).get('choices', [{}])[0].get('message', {}).get('content', '')
    return text


# ----------------- Обработчики -----------------
async def start(update, context):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    user_conversations[user_id] = []

    welcome_message = f"""👋 Привет, {user_name}! Я — твой Fashion AI Agent!

✨ **Мои специализации:**
• Анализ образов
• Капсульные гардеробы
• Советы по трендам и сочетаниям
• Планирование fashion-проектов
• Консультирую по продюсированию

💡 **Как использовать:**
• Отправь фото для анализа
• Задай вопрос о стиле или трендах
• Попроси помочь спланировать проект

**Команды:**
/start - Начать сначала
/clear - Очистить историю диалога
/help - Примеры вопросов

🚀 Работает на Qwen AI (Alibaba Cloud)"""
    await update.message.reply_text(welcome_message)


async def help_command(update, context):
    help_text = """💡 **Примеры вопросов:**
• "Помоги создать капсульный гардероб для весны"
• "Какие цвета мне подойдут?"
• "Как собрать образ для собеседования?"
• "Что носить с джинсами?"
• "Проанализируй мой образ на фото"
• "Как спланировать fashion-съемку с бюджетом 50к?"
• "Какие тренды актуальны сейчас?"
"""
    await update.message.reply_text(help_text)


async def clear_history(update, context):
    user_id = update.effective_user.id
    user_conversations[user_id] = []
    await update.message.reply_text("✨ История диалога очищена!")


# ----------------- Текстовые сообщения -----------------
async def handle_message(update, context):
    user_id = update.effective_user.id
    user_message = update.message.text

    if user_id not in user_conversations:
        user_conversations[user_id] = []

    user_conversations[user_id].append({"role": "user", "content": user_message})
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        # Подготовка сообщений для Qwen (только текст)
        messages = [
            {"role": "system", "content": FASHION_SYSTEM_PROMPT},
        ]
        messages.extend(user_conversations[user_id])

        assistant_message = call_qwen_api(messages, is_vision=False)

        user_conversations[user_id].append({"role": "assistant", "content": assistant_message})

        # Ограничиваем историю последних 20 сообщений
        if len(user_conversations[user_id]) > 20:
            user_conversations[user_id] = user_conversations[user_id][-20:]

        await update.message.reply_text(assistant_message)

    except Exception as e:
        await update.message.reply_text(f"😔 Произошла ошибка: {e}\nПопробуйте /clear.")
        print(f"Text error: {e}")


# ----------------- Фото сообщения -----------------
async def handle_photo(update, context):
    user_id = update.effective_user.id
    if user_id not in user_conversations:
        user_conversations[user_id] = []

    await update.message.chat.send_action(ChatAction.UPLOAD_PHOTO)

    try:
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        # Уменьшаем изображение
        image = Image.open(io.BytesIO(photo_bytes))
        image = image.convert("RGB")  # Убедимся, что это RGB
        image.thumbnail((1024, 1024))  # ограничиваем размер
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        photo_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        caption = update.message.caption or "Проанализируй этот образ детально."

        # Подготовка сообщений для Qwen (текст + изображение)
        messages = [
            {"role": "system", "content": FASHION_SYSTEM_PROMPT},
        ]

        # Добавляем предыдущие сообщения (если есть)
        messages.extend(user_conversations[user_id][:-1])  # все кроме последнего

        # Последнее сообщение пользователя: текст + изображение
        last_message_with_image = {
            "role": "user",
            "content": [
                {"text": caption},
                {"image": f"data:image/jpeg;base64,{photo_base64}"}
            ]
        }
        messages.append(last_message_with_image)

        await update.message.chat.send_action(ChatAction.TYPING)

        # Вызов Qwen API с изображением
        assistant_message = call_qwen_api(messages, is_vision=True)

        user_conversations[user_id].append({"role": "assistant", "content": assistant_message})

        # Ограничиваем историю последних 20 сообщений
        if len(user_conversations[user_id]) > 20:
            user_conversations[user_id] = user_conversations[user_id][-20:]

        await update.message.reply_text(assistant_message)

    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка обработки фото: {e}\nПопробуйте отправить уменьшенное фото.")
        print(f"Photo error: {e}")


# ----------------- Основная функция -----------------
def main():
    print("=" * 50)
    print("🚀 Запускаю Fashion AI Telegram Bot (Qwen)")
    print("=" * 50)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("✅ Бот успешно запущен и готов к работе!")
    app.run_polling()


if __name__ == "__main__":
    main()
