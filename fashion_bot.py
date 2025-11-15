# ----------------- imports -----------------
import os
import io
import base64
import json
import httpx
from PIL import Image

# Telegram
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from telegram.constants import ChatAction

# ----------------- Переменные окружения -----------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

print("TELEGRAM_TOKEN:", TELEGRAM_TOKEN)
print("DEEPSEEK_API_KEY:", DEEPSEEK_API_KEY)

if not TELEGRAM_TOKEN or not DEEPSEEK_API_KEY:
    raise ValueError("❌ Не найдены токены! Добавьте TELEGRAM_TOKEN и DEEPSEEK_API_KEY в Heroku Config Vars")

# ----------------- Настройки DeepSeek -----------------
API_URL = "https://api.deepseek.com/v1/chat/completions"
FASHION_SYSTEM_PROMPT = """Ты — экспертный AI-агент в области fashion-индустрии. 
Давай детально анализировать образы, давать советы и рекомендации."""

# ----------------- Хранилище истории -----------------
user_conversations = {}

# ----------------- Обработчики -----------------
async def start(update: Update, context):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    user_conversations[user_id] = []

    welcome_message = f"""👋 Привет, {user_name}! Я — твой Fashion AI Agent! 
Отправь мне текстовое сообщение или фото, чтобы я дал совет по стилю."""
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context):
    help_text = """💡 Примеры вопросов:
- Как мне подобрать одежду на вечер?
- Оцени мой образ на фото.
- Дай советы по стилю для зимы."""
    await update.message.reply_text(help_text)


async def clear_history(update: Update, context):
    user_id = update.effective_user.id
    user_conversations[user_id] = []
    await update.message.reply_text("✨ История диалога очищена!")

# ----------------- Вспомогательная функция для DeepSeek -----------------
def call_deepseek(messages):
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "your-model-name",  # замените на актуальную модель DeepSeek
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 1024
    }

    response = httpx.post(API_URL, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    # Ответ DeepSeek находится обычно в choices[0].message.content
    return data["choices"][0]["message"]["content"]

# ----------------- Обработка текстовых сообщений -----------------
async def handle_message(update: Update, context):
    user_id = update.effective_user.id
    user_message = update.message.text

    if user_id not in user_conversations:
        user_conversations[user_id] = []

    user_conversations[user_id].append({"role": "user", "content": user_message})
    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        messages = [{"role": "system", "content": FASHION_SYSTEM_PROMPT}] + user_conversations[user_id]
        assistant_message = call_deepseek(messages)

        user_conversations[user_id].append({"role": "assistant", "content": assistant_message})
        if len(user_conversations[user_id]) > 20:
            user_conversations[user_id] = user_conversations[user_id][-20:]

        await update.message.reply_text(assistant_message)

    except Exception as e:
        await update.message.reply_text(f"😔 Произошла ошибка: {e}\nПопробуйте /clear")
        print(f"Error: {e}")

# ----------------- Обработка фото сообщений -----------------
async def handle_photo(update: Update, context):
    user_id = update.effective_user.id
    if user_id not in user_conversations:
        user_conversations[user_id] = []

    await update.message.chat.send_action(ChatAction.UPLOAD_PHOTO)

    try:
        photo = update.message.photo[-1]
        photo_file = await photo.get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        image = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
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
        assistant_message = call_deepseek(messages)

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
    print("🚀 Запускаю Fashion AI Telegram Bot (DeepSeek)")
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
