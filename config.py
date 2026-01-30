"""
Конфигурация бота
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

# DashScope API
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# API для генерации изображений
IMAGE_API_URL = "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"

# Настройки парсинга
PARSER_CACHE_TTL_HOURS = 1
PARSER_TIMEOUT = 10

# Логирование
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
