# ----------------- imports -----------------
import os
import base64
import io

# OpenAI совместимый клиент (DeepSeek)
from openai import OpenAI

# Telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.constants import ChatAction

# Pillow (на будущее)
from PIL import Image

# ----------------- Переменные окружения -----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

print("TELEGRAM_TOKEN:", TELEGRAM_TOKEN)
print("DEEPSEEK_API_KEY:", DEEPSEEK_API_KEY)

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("❌ Не найдены токены! Добавьте TELEGRAM_TOKEN и DEEPSEEK_API_KEY в Heroku Config Vars")

# ----------------- DeepSeek -----------------
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

FASHION_SYSTEM_PROMPT = """Ты — экспертный fashion-стилист. 
Даешь точный, структурированный, экспертный разбор стиля, одежды, сочетаний и рекомендаций.
Отвечаешь уверенно, как профессиональный стилист.
"""

# ----------------- Хранилище истории -----------------
user_conversations = {}

# ----------------- Обработчики -----------------
async def start(update, context):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    user_conversations[user_id] = []

    welcome_message = f"""👋 Привет, {user_name}! Я — твой Fashion AI Agent на базе DeepSeek.
Спроси что угодно о стиле, образах, одежде, сочетаниях и трендах."""
    await update.message.reply_text(welcome_message)


async def help_command(update, context):
    help_text = """💡 Примеры запросов:
— Подскажи стиль под мои параметры
— Как собрать образ для свидания?
— Как сочетаются коричневые ботинки?
— Какой стиль подходит под офис?
— Как улучшить мой гардероб?
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

        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
        )

        assistant_message = response.choices[0].message.content
        user_conversations[user_id].append(
            {"role": "assistant", "content": assistant_message}
        )

        # Храним только 20 последних сообщений
        if len(user_conversations[user_id]) > 20:
            user_conversations[user_id] = user_conversations[user_id][-20:]

        await update.message.reply_text(assistant_message)

    except Exception as e:
        await update.message.reply_text(f"😔 Ошибка: {e}\nПопробуйте /clear.")
        print(f"Error: {e}")


# ----------------- Фото сообщения -----------------
async def handle_photo(update, context):
    await update.message.reply_text(
        "📸 DeepSeek API пока **не поддерживает анализ изображений**.\n"
        "Если хочешь, могу настроить гибридную версию: DeepSeek для текста + Groq Vision для фото."
    )


# ----------------- Основная функция -----------------
def main():
    print("=" * 50)
    print("🚀 Запуск Fashion AI Telegram Bot (DeepSeek)")
    print("=" * 50)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_history))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("✅ Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
