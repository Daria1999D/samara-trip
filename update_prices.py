#!/usr/bin/env python3
"""
Скрипт автообновления цен на жильё и авиабилеты.
Запускается по cron каждые 30 минут.
Парсит Яндекс.Расписания и Туту, обновляет HTML, пушит на GitHub Pages.
"""

import re
import json
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

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


def fetch_url(url, timeout=20):
    try:
        req = Request(url, headers=HEADERS)
        with urlopen(req, timeout=timeout) as resp:
            return resp.read().decode('utf-8', errors='replace')
    except Exception as e:
        log.warning(f'Ошибка загрузки {url}: {e}')
        return None


def parse_yandex_flights(from_id, to_id, date):
    """Парсинг рейсов с Яндекс.Расписания."""
    url = f'https://rasp.yandex.ru/search/plane/?fromId={from_id}&toId={to_id}&when={date}'
    html = fetch_url(url)
    if not html:
        return {}

    flights = {}
    # Ищем данные рейсов в JSON
    # Паттерн: номер рейса и цена
    price_patterns = [
        r'"number":\s*"([^"]+)".*?"value":\s*(\d+)',
        r'"thread".*?"number":\s*"([^"]+)".*?"price".*?"value":\s*(\d+)',
    ]
    for pat in price_patterns:
        for match in re.finditer(pat, html, re.DOTALL):
            flight_num = match.group(1).replace(' ', '')
            try:
                price = int(match.group(2))
                if 1000 < price < 50000:
                    flights[flight_num] = price
            except ValueError:
                continue
    return flights


def parse_tutu_prices(from_city, to_city, date):
    """Парсинг цен с Туту."""
    url = f'https://avia.tutu.ru/f/{from_city}/{to_city}/?date={date}'
    html = fetch_url(url)
    if not html:
        return {}

    flights = {}
    patterns = [
        r'(SU\s*\d+|DP\s*\d+|S7\s*\d+|Y7\s*\d+|FV\s*\d+|UT\s*\d+|U6\s*\d+|6R\s*\d+).*?(\d[\d\s]*)\s*₽',
    ]
    for pat in patterns:
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


def update_flight_prices(html, flights_data):
    """Обновить цены рейсов в HTML."""
    updated = False

    for flight_num, price in flights_data.items():
        # Ищем рейс в HTML и обновляем цену
        # Формат в HTML: badge>Airline</span> FV 6061</span>
        # Ищем по номеру рейса и обновляем ближайший flight-price-tag
        escaped = re.escape(flight_num)
        # Добавим пробел между буквами и цифрами для поиска
        spaced = re.sub(r'([A-Z]+)(\d+)', r'\1 \2', flight_num)

        pattern = re.escape(spaced) + r'.*?~[\d\s]+\s*₽'
        match = re.search(pattern, html, re.DOTALL)
        if match and len(match.group()) < 500:  # Защита от слишком жадного поиска
            old_text = match.group()
            # Извлечь старую цену
            old_price_match = re.search(r'~([\d\s]+)\s*₽', old_text)
            if old_price_match:
                old_price_str = old_price_match.group(1).replace(' ', '')
                new_price_str = f'{price:,}'.replace(',', ' ')
                if old_price_str != str(price):
                    new_text = old_text.replace(f'~{old_price_match.group(1)} ₽', f'~{new_price_str} ₽')
                    html = html.replace(old_text, new_text, 1)
                    log.info(f'Рейс {flight_num}: {old_price_str} → {price} ₽')
                    updated = True

    return html, updated


def update_timestamp(html):
    now = datetime.now().strftime('%d.%m.%Y %H:%M')
    if '<!-- last-update:' in html:
        html = re.sub(r'<!-- last-update:.*?-->', f'<!-- last-update: {now} -->', html)
    else:
        html = html.replace('</head>', f'<!-- last-update: {now} -->\n</head>')
    return html


def git_push():
    try:
        subprocess.run(['git', 'add', 'index.html'], cwd=REPO_DIR, check=True, capture_output=True)
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=REPO_DIR, capture_output=True)
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
    log.info('=== Начало обновления ===')

    html = HTML_PATH.read_text(encoding='utf-8')
    updated = False

    # --- Рейсы туда: Москва → Самара, 9 апреля ---
    log.info('Ищу цены Москва → Самара 09.04...')
    prices_out = {}

    # Яндекс.Расписания
    yandex_out = parse_yandex_flights('c213', 'c51', '2026-04-09')
    if yandex_out:
        log.info(f'Яндекс туда: {yandex_out}')
        prices_out.update(yandex_out)

    # Туту
    tutu_out = parse_tutu_prices('Moskva', 'Samara', '09.04.2026')
    if tutu_out:
        log.info(f'Туту туда: {tutu_out}')
        # Обновляем только если нет данных из Яндекса
        for k, v in tutu_out.items():
            if k not in prices_out:
                prices_out[k] = v

    if prices_out:
        html, upd = update_flight_prices(html, prices_out)
        updated = updated or upd

    # --- Рейсы обратно: Самара → Москва, 12 апреля ---
    log.info('Ищу цены Самара → Москва 12.04...')
    prices_ret = {}

    yandex_ret = parse_yandex_flights('c51', 'c213', '2026-04-12')
    if yandex_ret:
        log.info(f'Яндекс обратно: {yandex_ret}')
        prices_ret.update(yandex_ret)

    tutu_ret = parse_tutu_prices('Samara', 'Moskva', '12.04.2026')
    if tutu_ret:
        log.info(f'Туту обратно: {tutu_ret}')
        for k, v in tutu_ret.items():
            if k not in prices_ret:
                prices_ret[k] = v

    if prices_ret:
        html, upd = update_flight_prices(html, prices_ret)
        updated = updated or upd

    # --- Обновить timestamp ---
    html = update_timestamp(html)
    HTML_PATH.write_text(html, encoding='utf-8')

    if updated:
        log.info('HTML обновлён с новыми ценами')
        git_push()
    else:
        log.info('Цены не изменились')

    log.info('=== Обновление завершено ===\n')


if __name__ == '__main__':
    main()
