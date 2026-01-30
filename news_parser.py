"""
Fashion Director 2026 — Модуль парсинга и аналитики
—————————————————————————————————————————————————
Этот модуль отвечает за сбор данных с 8 мировых источников.
Основные технологии: BeautifulSoup (парсинг), JSON (кэширование), re (очистка).
"""

import requests
from bs4 import BeautifulSoup
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import os

# Настройка логирования для отслеживания работы парсера в консоли
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ ---
CACHE_FILE = "news_cache.json"
CACHE_TTL_HOURS = 1  # Кэш обновляется раз в час, чтобы не нагружать сайты и API

# Реестр источников: URL, название и соответствующая функция-обработчик
FASHION_SITES = [
    {"url": "https://www.businessoffashion.com/", "name": "Business of Fashion", "parser": "_parse_businessoffashion"},
    {"url": "https://wwd.com/", "name": "WWD", "parser": "_parse_wwd"},
    {"url": "https://www.sports.ru/style/", "name": "Sports.ru Style", "parser": "_parse_sports_style"},
    {"url": "https://theblueprint.ru/", "name": "The Blueprint", "parser": "_parse_theblueprint"},
    {"url": "https://about.nike.com/en/newsroom", "name": "Nike Newsroom", "parser": "_parse_nike_newsroom"},
    {"url": "https://www.footyheadlines.com/", "name": "Footy Headlines", "parser": "_parse_footyheadlines"},
    {"url": "https://coloro.com/", "name": "Coloro", "parser": "_parse_coloro"},
    {"url": "https://www.wgsn.com/en", "name": "WGSN", "parser": "_parse_wgsn"}
]

# Заголовки для имитации браузера (защита от блокировок)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ==================== СИСТЕМА КЭШИРОВАНИЯ ====================
# Кэширование позволяет боту мгновенно отвечать пользователю, 
# не запуская долгий процесс сканирования сайтов при каждом запросе.

def _is_cache_valid(cache_time: str) -> bool:
    """Проверяет, не устарел ли файл кэша."""
    try:
        cache_dt = datetime.fromisoformat(cache_time)
        return datetime.now() - cache_dt < timedelta(hours=CACHE_TTL_HOURS)
    except:
        return False

def _save_cache(news_data: List[Dict]) -> None:
    """Записывает свежие новости в JSON файл с меткой времени."""
    cache_data = {
        "timestamp": datetime.now().isoformat(),
        "news": news_data
    }
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

def _load_cache() -> Optional[Dict]:
    """Загружает данные из файла, если он существует."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def _clean_html(text: str) -> str:
    """Удаляет мусор, лишние пробелы и HTML-теги из заголовков."""
    if not text: return ""
    text = re.sub(r'<[^>]+>', '', str(text))
    return " ".join(text.split())

def _safe_request(url: str):
    """Безопасно выполняет HTTP-запрос."""
    try:
        return requests.get(url, headers=HEADERS, timeout=10)
    except Exception as e:
        logger.error(f"Ошибка доступа к {url}: {e}")
        return None

# ==================== ПАРСЕРЫ (ПРИМЕРЫ) ====================
# Каждый сайт имеет свою структуру HTML, поэтому для каждого — свой метод поиска тегов.

def _parse_generic(url: str, source_name: str, domain: str) -> List[Dict]:
    """Универсальный парсер для большинства сайтов (H2/H3 заголовки)."""
    response = _safe_request(url)
    if not response: return []
    
    soup = BeautifulSoup(response.text, 'html.parser')
    news = []
    # Ищем заголовки в тегах article или div с типичными классами
    for article in soup.find_all(['article', 'div'], class_=re.compile('post|item|article|news'), limit=5):
        tag = article.find(['h2', 'h3', 'a'])
        if tag:
            title = _clean_html(tag.get_text())
            link = article.find('a', href=True)['href'] if article.find('a', href=True) else ''
            if link and not link.startswith('http'): link = domain + link
            if title and len(title) > 10:
                news.append({'title': title, 'link': link, 'source': source_name})
    return news[:3]

# Маппинг функций парсинга для совместимости с вашим списком FASHION_SITES
def _parse_businessoffashion(): return _parse_generic("https://www.businessoffashion.com/", "BoF", "https://www.businessoffashion.com")
def _parse_wwd(): return _parse_generic("https://wwd.com/", "WWD", "https://wwd.com")
def _parse_sports_style(): return _parse_generic("https://www.sports.ru/style/", "Sports Style", "https://www.sports.ru")
def _parse_theblueprint(): return _parse_generic("https://theblueprint.ru/", "The Blueprint", "https://theblueprint.ru")
def _parse_nike_newsroom(): return _parse_generic("https://about.nike.com/en/newsroom", "Nike", "https://about.nike.com")
def _parse_footyheadlines(): return _parse_generic("https://www.footyheadlines.com/", "Footy Headlines", "https://www.footyheadlines.com")
def _parse_coloro(): return _parse_generic("https://coloro.com/", "Coloro", "https://coloro.com")
def _parse_wgsn(): return _parse_generic("https://www.wgsn.com/en", "WGSN", "https://www.wgsn.com")

# ==================== ГЛАВНЫЙ ИНТЕРФЕЙС ====================

def get_fashion_news(force_refresh: bool = False) -> List[Dict]:
    """
    Основная точка входа. 
    Сначала проверяет кэш, если он свежий — отдает его. 
    Иначе — запускает обход всех 8 сайтов.
    """
    if not force_refresh:
        cache = _load_cache()
        if cache and _is_cache_valid(cache.get("timestamp", "")):
            logger.info("📡 Данные взяты из локального кэша.")
            return cache.get("news", [])

    logger.info("🌐 Кэш устарел. Запуск глобального парсинга...")
    all_news = []
    
    for site in FASHION_SITES:
        try:
            # Динамический вызов функции парсера по имени из конфига
            parser_func = globals().get(site['parser'])
            if parser_func:
                site_news = parser_func()
                all_news.extend(site_news)
                logger.info(f"✅ {site['name']}: получено {len(site_news)} новостей.")
        except Exception as e:
            logger.error(f"❌ Ошибка в {site['name']}: {e}")

    # Сохраняем результат, чтобы не мучить сайты следующий час
    _save_cache(all_news)
    return all_news

def format_news_message(news_list: List[Dict]) -> str:
    """
    Превращает список словарей в красивый текст для Telegram.
    Используется в Fashion Director, если ИИ-аналитик временно недоступен.
    """
    if not news_list:
        return "⚠️ *Новостей пока нет.* Попробуйте обновить позже."

    message = f"🌟 **Fashion Digest — {datetime.now().strftime('%d.%m')}**\n"
    message += "————————————————\n\n"
    
    for i, item in enumerate(news_list[:12], 1):
        message += f"{i}. **{item['title']}**\n"
        message += f"   └ 📡 _{item['source']}_ | [Читать]({item['link']})\n\n"
        
    message += "————————————————\n"
    message += "💡 _Нажмите «Новости моды» снова для обновления._"
    return message
