"""
Модуль парсинга новостей моды с кэшированием
"""
import requests
from bs4 import BeautifulSoup
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import os

logger = logging.getLogger(__name__)

# Константы
CACHE_FILE = "news_cache.json"
CACHE_TTL_HOURS = 1  # Кэш живёт 1 час

# Список сайтов для парсинга
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

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================

def _clean_html(text: str) -> str:
    """Удаление HTML тегов и лишних пробелов"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', str(text))
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def _is_cache_valid(cache_time: str) -> bool:
    """Проверка актуальности кэша"""
    try:
        cache_dt = datetime.fromisoformat(cache_time)
        return datetime.now() - cache_dt < timedelta(hours=CACHE_TTL_HOURS)
    except:
        return False

def _load_cache() -> Optional[Dict]:
    """Загрузка кэша из файла"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Ошибка загрузки кэша: {e}")
    return None

def _save_cache(news_data: List[Dict]) -> None:
    """Сохранение кэша в файл"""
    try:
        cache_data = {
            "timestamp": datetime.now().isoformat(),
            "news": news_data
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        logger.info(f"Кэш сохранён: {len(news_data)} новостей")
    except Exception as e:
        logger.error(f"Ошибка сохранения кэша: {e}")

def _get_cached_news() -> Optional[List[Dict]]:
    """Получение новостей из кэша, если актуально"""
    cache = _load_cache()
    if cache and _is_cache_valid(cache.get("timestamp", "")):
        logger.info("Используется кэш новостей")
        return cache.get("news")
    return None

# ==================== ПАРСЕРЫ САЙТОВ ====================

def _parse_businessoffashion() -> List[Dict]:
    """Парсинг Business of Fashion"""
    try:
        response = requests.get("https://www.businessoffashion.com/", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news = []
        articles = soup.find_all('article', class_=re.compile('article|post|story'), limit=5)
        
        for article in articles[:3]:
            try:
                title_tag = article.find('h2') or article.find('h3') or article.find('a', class_=re.compile('title|headline'))
                if not title_tag:
                    continue
                    
                title = _clean_html(title_tag.get_text())
                link_tag = article.find('a', href=True)
                link = link_tag['href'] if link_tag else ''
                if link and not link.startswith('http'):
                    link = 'https://www.businessoffashion.com' + link
                
                news.append({
                    'title': title,
                    'link': link,
                    'source': 'Business of Fashion'
                })
            except Exception as e:
                continue
                
        return news[:3]
    except Exception as e:
        logger.error(f"Ошибка парсинга BoF: {e}")
        return []

def _parse_wwd() -> List[Dict]:
    """Парсинг WWD"""
    try:
        response = requests.get("https://wwd.com/", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news = []
        articles = soup.find_all('article', limit=5)
        
        for article in articles[:3]:
            try:
                title_tag = article.find('h2') or article.find('h3')
                if not title_tag:
                    continue
                    
                title = _clean_html(title_tag.get_text())
                link_tag = article.find('a', href=True)
                link = link_tag['href'] if link_tag else ''
                if link and not link.startswith('http'):
                    link = 'https://wwd.com' + link
                
                news.append({
                    'title': title,
                    'link': link,
                    'source': 'WWD'
                })
            except Exception as e:
                continue
                
        return news[:3]
    except Exception as e:
        logger.error(f"Ошибка парсинга WWD: {e}")
        return []

def _parse_sports_style() -> List[Dict]:
    """Парсинг Sports.ru Style"""
    try:
        response = requests.get("https://www.sports.ru/style/", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news = []
        articles = soup.find_all('div', class_=re.compile('short|news|article'), limit=5)
        
        for article in articles[:3]:
            try:
                title_tag = article.find('a', class_=re.compile('title|name|link'))
                if not title_tag:
                    continue
                    
                title = _clean_html(title_tag.get_text())
                link = title_tag.get('href', '')
                if link and not link.startswith('http'):
                    link = 'https://www.sports.ru' + link
                
                news.append({
                    'title': title,
                    'link': link,
                    'source': 'Sports.ru Style'
                })
            except Exception as e:
                continue
                
        return news[:3]
    except Exception as e:
        logger.error(f"Ошибка парсинга Sports.ru: {e}")
        return []

def _parse_theblueprint() -> List[Dict]:
    """Парсинг The Blueprint"""
    try:
        response = requests.get("https://theblueprint.ru/", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news = []
        articles = soup.find_all('article', limit=5)
        
        for article in articles[:3]:
            try:
                title_tag = article.find('h2') or article.find('h3')
                if not title_tag:
                    continue
                    
                title = _clean_html(title_tag.get_text())
                link_tag = article.find('a', href=True)
                link = link_tag['href'] if link_tag else ''
                if link and not link.startswith('http'):
                    link = 'https://theblueprint.ru' + link
                
                news.append({
                    'title': title,
                    'link': link,
                    'source': 'The Blueprint'
                })
            except Exception as e:
                continue
                
        return news[:3]
    except Exception as e:
        logger.error(f"Ошибка парсинга The Blueprint: {e}")
        return []

def _parse_nike_newsroom() -> List[Dict]:
    """Парсинг Nike Newsroom"""
    try:
        response = requests.get("https://about.nike.com/en/newsroom", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news = []
        articles = soup.find_all('div', class_=re.compile('news|article|story'), limit=5)
        
        for article in articles[:3]:
            try:
                title_tag = article.find('h2') or article.find('h3') or article.find('a')
                if not title_tag:
                    continue
                    
                title = _clean_html(title_tag.get_text())
                link_tag = article.find('a', href=True)
                link = link_tag['href'] if link_tag else ''
                if link and not link.startswith('http'):
                    link = 'https://about.nike.com' + link
                
                news.append({
                    'title': title,
                    'link': link,
                    'source': 'Nike Newsroom'
                })
            except Exception as e:
                continue
                
        return news[:3]
    except Exception as e:
        logger.error(f"Ошибка парсинга Nike: {e}")
        return []

def _parse_footyheadlines() -> List[Dict]:
    """Парсинг Footy Headlines"""
    try:
        response = requests.get("https://www.footyheadlines.com/", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news = []
        articles = soup.find_all('article', limit=5)
        
        for article in articles[:3]:
            try:
                title_tag = article.find('h2') or article.find('h3')
                if not title_tag:
                    continue
                    
                title = _clean_html(title_tag.get_text())
                link_tag = article.find('a', href=True)
                link = link_tag['href'] if link_tag else ''
                if link and not link.startswith('http'):
                    link = 'https://www.footyheadlines.com' + link
                
                news.append({
                    'title': title,
                    'link': link,
                    'source': 'Footy Headlines'
                })
            except Exception as e:
                continue
                
        return news[:3]
    except Exception as e:
        logger.error(f"Ошибка парсинга Footy Headlines: {e}")
        return []

def _parse_coloro() -> List[Dict]:
    """Парсинг Coloro"""
    try:
        response = requests.get("https://coloro.com/", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news = []
        sections = soup.find_all(['section', 'div'], class_=re.compile('news|blog|trend|color|article'), limit=5)
        
        for section in sections[:3]:
            try:
                title_tag = section.find('h2') or section.find('h3') or section.find('a')
                if not title_tag:
                    continue
                    
                title = _clean_html(title_tag.get_text())
                link_tag = section.find('a', href=True)
                link = link_tag['href'] if link_tag else ''
                if link and not link.startswith('http'):
                    link = 'https://coloro.com' + link
                
                news.append({
                    'title': title,
                    'link': link,
                    'source': 'Coloro'
                })
            except Exception as e:
                continue
                
        return news[:3]
    except Exception as e:
        logger.error(f"Ошибка парсинга Coloro: {e}")
        return []

def _parse_wgsn() -> List[Dict]:
    """Парсинг WGSN"""
    try:
        response = requests.get("https://www.wgsn.com/en", headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        news = []
        sections = soup.find_all(['section', 'div', 'article'], class_=re.compile('trend|news|insight|article'), limit=5)
        
        for section in sections[:3]:
            try:
                title_tag = section.find('h2') or section.find('h3') or section.find('a')
                if not title_tag:
                    continue
                    
                title = _clean_html(title_tag.get_text())
                link_tag = section.find('a', href=True)
                link = link_tag['href'] if link_tag else ''
                if link and not link.startswith('http'):
                    link = 'https://www.wgsn.com' + link
                
                news.append({
                    'title': title,
                    'link': link,
                    'source': 'WGSN'
                })
            except Exception as e:
                continue
                
        return news[:3]
    except Exception as e:
        logger.error(f"Ошибка парсинга WGSN: {e}")
        return []

# ==================== ОСНОВНЫЕ ФУНКЦИИ ====================

def get_fashion_news(force_refresh: bool = False) -> List[Dict]:
    """
    Получение новостей моды
    
    Args:
        force_refresh: Если True, игнорирует кэш и парсит заново
    
    Returns:
        Список новостей
    """
    # Проверяем кэш
    if not force_refresh:
        cached = _get_cached_news()
        if cached:
            return cached
    
    # Парсим заново
    logger.info("Запуск парсинга новостей...")
    all_news = []
    
    for site in FASHION_SITES:
        try:
            parser_func = globals()[site['parser']]
            logger.info(f"Парсинг {site['name']}...")
            
            news = parser_func()
            all_news.extend(news)
            logger.info(f"Получено {len(news)} новостей с {site['name']}")
            
        except Exception as e:
            logger.error(f"Ошибка парсинга {site['name']}: {e}")
            continue
    
    # Сохраняем в кэш
    _save_cache(all_news)
    
    return all_news[:15]  # Ограничиваем до 15 новостей

def format_news_message(news_list: List[Dict]) -> str:
    """
    Форматирование новостей в красивое сообщение
    
    Args:
        news_list: Список новостей
    
    Returns:
        Отформатированная строка
    """
    if not news_list:
        return "📰 *Новости моды*\n\nК сожалению, не удалось загрузить свежие новости. Попробуйте позже."
    
    today = datetime.now().strftime("%d.%m.%Y")
    message = f"📰 *Новости моды — {today}*\n\n"
    
    # Группируем по источникам
    sources = {}
    for news in news_list:
        source = news.get('source', 'Источник')
        if source not in sources:
            sources[source] = []
        sources[source].append(news)
    
    for source, items in sources.items():
        message += f"━━━━━━━━━━━━━━━━━━\n"
        message += f"🔸 *{source}*\n\n"
        
        for i, item in enumerate(items[:3], 1):
            title = item.get('title', 'Без заголовка')
            link = item.get('link', '#')
            
            # Обрезаем длинные заголовки
            if len(title) > 70:
                title = title[:67] + "..."
            
            message += f"{i}. {title}\n"
            if link != '#':
                message += f"   🔗 {link}\n"
            message += "\n"
    
    message += f"━━━━━━━━━━━━━━━━━━\n"
    message += f"\n_Данные собраны с 8 мировых источников моды_"
    message += f"\n_Автообновление каждые {CACHE_TTL_HOURS} час(а)_"
    
    return message

def get_cache_info() -> Dict:
    """Получение информации о кэше"""
    cache = _load_cache()
    if not cache:
        return {"exists": False, "count": 0, "age": "N/A"}
    
    cache_time = datetime.fromisoformat(cache.get("timestamp", ""))
    age = datetime.now() - cache_time
    age_minutes = int(age.total_seconds() / 60)
    
    return {
        "exists": True,
        "count": len(cache.get("news", [])),
        "age": f"{age_minutes} мин" if age_minutes < 60 else f"{age_minutes // 60} ч {age_minutes % 60} мин",
        "timestamp": cache.get("timestamp")
    }
