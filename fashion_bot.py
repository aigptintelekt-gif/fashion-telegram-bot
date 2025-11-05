# ----------------- imports -----------------
from dotenv import load_dotenv
import os
from pathlib import Path
import base64
import io

# Groq API
from groq import Groq

# Telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.constants import ChatAction

# Pillow для уменьшения фото
from PIL import Image

# ----------------- .env -----------------
#env_path = Path(__file__).parent / ".env"
#load_dotenv(dotenv_path=env_path)

#print("Файл существует?", env_path.exists())
#print("Содержимое файла:", env_path.read_text())

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

print(os.getenv("TELEGRAM_TOKEN"))
print("TELEGRAM_TOKEN:", TELEGRAM_TOKEN)
print("GROQ_API_KEY:", GROQ_API_KEY)

if not TELEGRAM_TOKEN or not GROQ_API_KEY:
    raise ValueError("❌ Не найдены токены! Проверь файл .env")

# ----------------- Groq -----------------
client = Groq(api_key=GROQ_API_KEY)

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
• Консультации по продюсированию

💡 **Как использовать:**
• Отправь фото для анализа
• Задай вопрос о стиле или трендах
• Попроси помочь спланировать проект

**Команды:**
/start - Начать сначала
/clear - Очистить историю диалога
/help - Примеры вопросов

🚀 Работает на Groq AI"""
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
        messages = [{"role": "system", "content": FASHION_SYSTEM_PROMPT}]
        messages.extend(user_conversations[user_id])

        # Текстовая модель
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            top_p=0.9,
        )

        assistant_message = response.choices[0].message.content
        user_conversations[user_id].append({"role": "assistant", "content": assistant_message})

        # Ограничиваем историю последних 20 сообщений
        if len(user_conversations[user_id]) > 20:
            user_conversations[user_id] = user_conversations[user_id][-20:]

        await update.message.reply_text(assistant_message)

    except Exception as e:
        await update.message.reply_text(f"😔 Произошла ошибка: {e}\nПопробуйте /clear.")
        print(f"Error: {e}")


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
        image = image.convert("RGB")
        image.thumbnail((1024, 1024))  # ограничиваем размер
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        photo_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        caption = update.message.caption or "Проанализируй этот образ детально"

        # Добавляем сообщение пользователя как текст (с меткой фото)
        user_conversations[user_id].append(
            {"role": "user", "content": f"{caption}\n[Фото прикреплено]"}
        )

        await update.message.chat.send_action(ChatAction.TYPING)

        # Модель с фото
        messages = [{"role": "system", "content": FASHION_SYSTEM_PROMPT}] + user_conversations[user_id]

        response = client.chat.completions.create(
            model="meta-llama/llama-guard-4-12b",
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            top_p=0.9,
        )

        assistant_message = response.choices[0].message.content
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
    print("🚀 Запускаю Fashion AI Telegram Bot (Groq)")
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
