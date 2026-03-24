#!/usr/bin/env python3
"""
Скрипт автообновления цен на жильё и авиабилеты.
Запускается по cron каждые 30 минут.
Парсит цены с площадок, обновляет HTML, пушит на GitHub Pages.
"""

import re
import json
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('/root/личное/поездка в Самару/update.log'),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

HTML_PATH = Path('/root/личное/поездка в Самару/index.html')
REPO_DIR = Path('/root/личное/поездка в Самару')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5',
}


def fetch_url(url, timeout=15):
    """Загрузка URL с обработкой ошибок."""
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        log.warning(f'Ошибка загрузки {url}: {e}')
        return None


def parse_ostrovok_price(hotel_id):
    """Парсинг цены с Островка через их API-подобные эндпоинты."""
    url = f'https://ostrovok.ru/hotel/russia/samara/{hotel_id}/?dates=09.04.2026-12.04.2026&guests=2'
    html = fetch_url(url)
    if not html:
        return None
    # Ищем цену в JSON-данных или HTML
    patterns = [
        r'"price":\s*(\d+)',
        r'"min_price":\s*(\d+)',
        r'от\s*([\d\s]+)\s*₽',
        r'(\d[\d\s]*)\s*₽\s*/\s*ночь',
    ]
    for pat in patterns:
        match = re.search(pat, html)
        if match:
            price_str = match.group(1).replace(' ', '').replace('\xa0', '')
            try:
                price = int(price_str)
                if 500 < price < 100000:
                    return price
            except ValueError:
                continue
    return None


def parse_sutochno_price(listing_id):
    """Парсинг цены с Суточно.ру."""
    url = f'https://samara.sutochno.ru/{listing_id}'
    html = fetch_url(url)
    if not html:
        return None
    patterns = [
        r'"price":\s*(\d+)',
        r'(\d[\d\s]*)\s*₽\s*/\s*сут',
        r'"costPerNight":\s*(\d+)',
        r'price_per_night["\s:]+(\d+)',
    ]
    for pat in patterns:
        match = re.search(pat, html)
        if match:
            price_str = match.group(1).replace(' ', '').replace('\xa0', '')
            try:
                price = int(price_str)
                if 500 < price < 50000:
                    return price * 3  # 3 ночи
            except ValueError:
                continue
    return None


def parse_tutu_flights(date_str):
    """Парсинг цен на рейсы с Туту."""
    url = f'https://avia.tutu.ru/f/Moskva/Samara/?date={date_str}'
    html = fetch_url(url)
    if not html:
        return {}
    flights = {}
    # Ищем блоки рейсов с ценами
    price_patterns = [
        r'(SU\s*\d+|DP\s*\d+|S7\s*\d+|Y7\s*\d+).*?(\d[\d\s]*)\s*₽',
        r'"flightNumber":\s*"([^"]+)".*?"price":\s*(\d+)',
    ]
    for pat in price_patterns:
        for match in re.finditer(pat, html, re.DOTALL):
            flight_num = match.group(1).replace(' ', '')
            price_str = match.group(2).replace(' ', '').replace('\xa0', '')
            try:
                price = int(price_str)
                if 1000 < price < 50000:
                    flights[flight_num] = price
            except ValueError:
                continue
    return flights


def update_price_in_html(html, old_price_pattern, new_price):
    """Обновить цену в HTML."""
    if new_price is None:
        return html
    formatted = f'{new_price:,}'.replace(',', ' ')
    return re.sub(old_price_pattern, f'~{formatted} ₽', html, count=1)


def update_timestamp(html):
    """Обновить временную метку."""
    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    # Обновляем мета-информацию в комментарии
    if '<!-- last-update:' in html:
        html = re.sub(
            r'<!-- last-update:.*?-->',
            f'<!-- last-update: {now} -->',
            html
        )
    else:
        html = html.replace('</head>', f'<!-- last-update: {now} -->\n</head>')
    return html


def git_push():
    """Коммит и пуш на GitHub."""
    try:
        subprocess.run(
            ['git', 'add', 'index.html'],
            cwd=REPO_DIR, check=True, capture_output=True
        )
        # Проверяем есть ли изменения
        result = subprocess.run(
            ['git', 'diff', '--cached', '--quiet'],
            cwd=REPO_DIR, capture_output=True
        )
        if result.returncode == 0:
            log.info('Нет изменений для коммита')
            return
        now = datetime.now().strftime('%d.%m %H:%M')
        subprocess.run(
            ['git', 'commit', '-m', f'Автообновление цен {now}'],
            cwd=REPO_DIR, check=True, capture_output=True
        )
        subprocess.run(
            ['git', 'push', 'origin', 'master'],
            cwd=REPO_DIR, check=True, capture_output=True
        )
        log.info('Изменения запушены на GitHub')
    except subprocess.CalledProcessError as e:
        log.error(f'Git ошибка: {e.stderr.decode() if e.stderr else e}')


def main():
    log.info('=== Начало обновления цен ===')

    html = HTML_PATH.read_text(encoding='utf-8')
    updated = False

    # --- Обновление цен на жильё ---
    hotels = {
        'ЛетягинЪ': ('mid11234047/letyaginy_butikhotel', r'~[\d\s]+₽\s*<small>/ 3 ночи</small>', 18000),
        'HolidayHall': ('mid7467350/holiday_hall', None, 12750),
        'В Теме': ('mid10460865/v_teme', None, 13500),
        'Hampton': ('mid8141919/hampton_by_hilton_samara', None, 20400),
        'Times': ('mid7467350/hotel_times', None, 7560),
    }

    for name, (hotel_id, _, fallback) in hotels.items():
        price = parse_ostrovok_price(hotel_id)
        if price:
            log.info(f'{name}: найдена цена {price} ₽/ночь (за 3 ночи: {price * 3})')
            # Обновляем цену в HTML (за 3 ночи)
            total = price * 3
            old_pattern = re.escape(f'~{fallback:,}'.replace(',', ' '))
            if old_pattern:
                new_formatted = f'~{total:,}'.replace(',', ' ')
                html_new = html.replace(
                    f'~{fallback:,}'.replace(',', ' '),
                    new_formatted,
                    1
                )
                if html_new != html:
                    html = html_new
                    updated = True
        else:
            log.info(f'{name}: цена не найдена, оставляем текущую')

    # --- Обновление цен на апартаменты ---
    apartments = {
        'Grand London': ('sutochno_search', 10470),
        'Некрасовская': ('1272577', 11400),
    }

    for name, (listing_id, fallback) in apartments.items():
        if listing_id == 'sutochno_search':
            continue  # Нельзя получить точную цену без ID
        price = parse_sutochno_price(listing_id)
        if price:
            log.info(f'{name}: найдена цена {price} ₽ за 3 ночи')
            old_str = f'~{fallback:,}'.replace(',', ' ')
            new_str = f'~{price:,}'.replace(',', ' ')
            html_new = html.replace(old_str, new_str, 1)
            if html_new != html:
                html = html_new
                updated = True
        else:
            log.info(f'{name}: цена не найдена, оставляем текущую')

    # --- Обновление цен на авиабилеты ---
    flight_map = {
        'SU1602': '4 265',
        'SU1604': '4 265',
        'SU1606': '4 265',
        'DP421': '2 830',
        'DP6581': '2 830',
        'S71073': '3 829',
        'Y74211': '3 434',
    }
    flights = parse_tutu_flights('09.04.2026')
    if flights:
        log.info(f'Найдены цены на рейсы: {flights}')
        for flight_num, price in flights.items():
            old_price = flight_map.get(flight_num)
            if old_price:
                new_formatted = f'{price:,}'.replace(',', ' ')
                old_str = f'~{old_price} ₽'
                new_str = f'~{new_formatted} ₽'
                if old_str in html and old_str != new_str:
                    html = html.replace(old_str, new_str, 1)
                    updated = True
                    log.info(f'Рейс {flight_num}: {old_str} → {new_str}')
    else:
        log.info('Цены на рейсы не найдены')

    # --- Обновить timestamp ---
    html = update_timestamp(html)

    # --- Записать и запушить ---
    if updated:
        HTML_PATH.write_text(html, encoding='utf-8')
        log.info('HTML обновлён')
        git_push()
    else:
        # Всё равно обновим timestamp
        HTML_PATH.write_text(html, encoding='utf-8')
        log.info('Цены не изменились, timestamp обновлён')

    log.info('=== Обновление завершено ===\n')


if __name__ == '__main__':
    main()
