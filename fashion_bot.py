# ----------------- imports -----------------
import os
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

# ----------------- Переменные окружения -----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

print("TELEGRAM_TOKEN:", TELEGRAM_TOKEN)
print("GROQ_API_KEY:", GROQ_API_KEY)

if not TELEGRAM_TOKEN or not GROQ_API_KEY:
    raise ValueError("❌ Не найдены токены! Добавьте TELEGRAM_TOKEN и GROQ_API_KEY в Heroku Config Vars")

# ----------------- Groq -----------------
client = Groq(api_key=GROQ_API_KEY)

FASHION_SYSTEM_PROMPT = """Ты — экспертный AI-агент в области fashion-индустрии...
(тут оставляем весь текст без изменений)
"""

# ----------------- Хранилище истории -----------------
user_conversations = {}

# ----------------- Обработчики -----------------
async def start(update, context):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    user_conversations[user_id] = []

    welcome_message = f"""👋 Привет, {user_name}! Я — твой Fashion AI Agent! ..."""
    await update.message.reply_text(welcome_message)


async def help_command(update, context):
    help_text = """💡 Примеры вопросов: ..."""
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
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.7,
            max_tokens=1024,
            top_p=0.9,
        )

        assistant_message = response.choices[0].message.content
        user_conversations[user_id].append({"role": "assistant", "content": assistant_message})

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

        image = Image.open(io.BytesIO(photo_bytes))
        image = image.convert("RGB")
        image.thumbnail((1024, 1024))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        photo_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        caption = update.message.caption or "Проанализируй этот образ детально"
        user_conversations[user_id].append(
            {"role": "user", "content": f"{caption}\n[Фото прикреплено]"}
        )

        await update.message.chat.send_action(ChatAction.TYPING)

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
