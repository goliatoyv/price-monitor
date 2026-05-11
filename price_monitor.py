#!/usr/bin/env python3
"""
Price Monitor — Joe's New Balance Outlet
Отслеживает цены и отправляет email-уведомление при снижении.

Запуск: python3 price_monitor.py
Планировщик (macOS): crontab -e → добавить строку из README
"""

import os
from curl_cffi import requests
from bs4 import BeautifulSoup
import json
import re
import smtplib
import time
import logging
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ─── Логирование ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
HISTORY_FILE = BASE_DIR / "price_history.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
}


# ─── Конфиг ────────────────────────────────────────────────────────────────
def load_config() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


# ─── История цен ───────────────────────────────────────────────────────────
def load_history() -> dict:
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(history: dict):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ─── Парсер цены ───────────────────────────────────────────────────────────
def fetch_price(url: str) -> dict | None:
    """
    Возвращает словарь:
        {"sale_price": 109.99, "original_price": 179.99, "currency": "USD"}
    или None, если не удалось распарсить.

    Стратегии (от надёжной к запасной):
      1. JSON-LD structured data (<script type="application/ld+json">)
      2. CSS-селекторы Salesforce Commerce Cloud
      3. Regex по тексту страницы
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30, impersonate="chrome124")
        resp.raise_for_status()
    except Exception as e:
        log.error("Не удалось загрузить страницу %s: %s", url, e)
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    html_text = resp.text

    # ── Стратегия 1: JSON-LD ──────────────────────────────────────────────
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            # Может быть списком
            items = data if isinstance(data, list) else [data]
            for item in items:
                if item.get("@type") == "Product":
                    offers = item.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0]
                    price = offers.get("price") or offers.get("lowPrice")
                    if price:
                        return {
                            "sale_price": float(price),
                            "original_price": None,
                            "currency": offers.get("priceCurrency", "USD"),
                        }
        except Exception:
            pass

    # ── Стратегия 2: CSS-селекторы SFCC / NB Outlet ───────────────────────
    selectors_sale = [
        ".sales .value",
        "[data-price-type='finalPrice']",
        ".price__sales .value",
        ".product-price .sales",
        "span.value[content]",   # <span class="value" content="109.99">
    ]
    selectors_original = [
        ".strike-through .value",
        ".price__old .value",
        "del .value",
    ]

    sale_price = None
    original_price = None

    for sel in selectors_sale:
        el = soup.select_one(sel)
        if el:
            raw = el.get("content") or el.get_text(strip=True)
            match = re.search(r"[\d,]+\.?\d*", raw.replace(",", ""))
            if match:
                sale_price = float(match.group().replace(",", ""))
                break

    for sel in selectors_original:
        el = soup.select_one(sel)
        if el:
            raw = el.get("content") or el.get_text(strip=True)
            match = re.search(r"[\d,]+\.?\d*", raw.replace(",", ""))
            if match:
                original_price = float(match.group().replace(",", ""))
                break

    if sale_price:
        return {"sale_price": sale_price, "original_price": original_price, "currency": "USD"}

    # ── Стратегия 3: Regex по тексту страницы ─────────────────────────────
    # Паттерны: "reduced to $109.99", "salesPrice":"109.99", "\"price\":109.99"
    patterns = [
        r'[Rr]educed\s+to\s+\$?([\d]+\.[\d]{2})',
        r'"salesPrice"\s*:\s*"?\$?([\d]+\.[\d]{2})',
        r'"price"\s*:\s*"([\d]+\.[\d]{2})"',
        r'class="sales[^"]*"[^>]*>\s*\$?([\d]+\.[\d]{2})',
    ]
    for pat in patterns:
        m = re.search(pat, html_text)
        if m:
            return {
                "sale_price": float(m.group(1)),
                "original_price": original_price,
                "currency": "USD",
            }

    log.warning("Не удалось распарсить цену для %s", url)
    return None


# ─── Email-уведомление ─────────────────────────────────────────────────────
def send_email(config: dict, product: dict, old_price: float, new_price: float):
    cfg = config["notifications"]["email"]
    if not cfg.get("enabled"):
        return

    subject = f"🔔 Цена упала: {product['name']} — ${new_price:.2f}"
    pct = ((old_price - new_price) / old_price * 100) if old_price else 0

    body = f"""
<html><body style="font-family:sans-serif;max-width:600px">
<h2 style="color:#d35400">🏷 Снижение цены!</h2>
<table style="border-collapse:collapse;width:100%">
  <tr><td style="padding:8px;color:#666">Товар</td>
      <td style="padding:8px"><b>{product['name']}</b></td></tr>
  <tr style="background:#f9f9f9">
      <td style="padding:8px;color:#666">Размер</td>
      <td style="padding:8px">{product.get('size','—')}</td></tr>
  <tr><td style="padding:8px;color:#666">Была</td>
      <td style="padding:8px;text-decoration:line-through;color:#999">${old_price:.2f}</td></tr>
  <tr style="background:#f9f9f9">
      <td style="padding:8px;color:#666">Стала</td>
      <td style="padding:8px;font-size:1.4em;color:#27ae60"><b>${new_price:.2f}</b></td></tr>
  <tr><td style="padding:8px;color:#666">Скидка</td>
      <td style="padding:8px;color:#e74c3c">−{pct:.0f}% (−${old_price - new_price:.2f})</td></tr>
</table>
<br>
<a href="{product['url']}" style="background:#27ae60;color:white;padding:12px 24px;
   text-decoration:none;border-radius:4px;display:inline-block">
   Купить сейчас →</a>
<br><br><small style="color:#aaa">Price Monitor · {datetime.now().strftime('%d.%m.%Y %H:%M')}</small>
</body></html>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(cfg["recipients"])
    msg.attach(MIMEText(body, "html", "utf-8"))

    try:
        password = os.environ.get("EMAIL_PASSWORD") or cfg["password"]
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["sender"], password)
            server.sendmail(cfg["sender"], cfg["recipients"], msg.as_bytes())
        log.info("✉️  Email отправлен на %s", cfg["recipients"])
    except Exception as e:
        log.error("Ошибка отправки email: %s", e)


# ─── Telegram-уведомление ──────────────────────────────────────────────────
def send_telegram(config: dict, product: dict, old_price: float, new_price: float):
    cfg = config["notifications"].get("telegram", {})
    if not cfg.get("enabled"):
        return

    token   = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("bot_token", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")   or cfg.get("chat_id", "")

    if not token or not chat_id:
        log.warning("Telegram не настроен: нет токена или chat_id")
        return

    pct  = ((old_price - new_price) / old_price * 100) if old_price else 0
    size = product.get("size", "")
    text = (
        f"🏷 *Цена упала!*\n\n"
        f"*{product['name']}*"
        + (f" `{size}`" if size else "") + "\n\n"
        f"~~${old_price:.2f}~~ → *${new_price:.2f}*\n"
        f"Скидка: −{pct:.0f}% (−${old_price - new_price:.2f})\n\n"
        f"[Купить →]({product['url']})"
    )

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "MarkdownV2",
                  "disable_web_page_preview": False},
            timeout=10,
            impersonate="chrome124",
        )
        resp.raise_for_status()
        log.info("📨 Telegram отправлен в chat %s", chat_id)
    except Exception as e:
        log.error("Ошибка отправки Telegram: %s", e)


# ─── Основная проверка ─────────────────────────────────────────────────────
def check_product(product: dict, config: dict, history: dict) -> None:
    url = product["url"]
    name = product["name"]
    target = product.get("target_price")

    log.info("Проверяю: %s", name)
    result = fetch_price(url)

    if result is None:
        log.warning("Не удалось получить цену для %s", name)
        return

    current_price = result["sale_price"]
    now_str = datetime.now().isoformat(timespec="seconds")

    # Запись в историю
    if url not in history:
        history[url] = []

    last_entry = history[url][-1] if history[url] else None
    last_price = last_entry["price"] if last_entry else None

    history[url].append({
        "price": current_price,
        "original": result.get("original_price"),
        "timestamp": now_str,
    })

    # Логика уведомления
    reasons = []

    if last_price is not None and current_price < last_price:
        reasons.append(f"цена упала с ${last_price:.2f} → ${current_price:.2f}")

    if target is not None and current_price <= target:
        reasons.append(f"достигнута целевая цена ${target:.2f}")

    if reasons:
        log.info("🎉 %s (%s)", name, ", ".join(reasons))
        old = last_price or (result.get("original_price") or current_price * 1.1)
        send_email(config, product, old, current_price)
        send_telegram(config, product, old, current_price)
    else:
        log.info("Цена не изменилась: $%.2f", current_price)


# ─── Главный цикл ──────────────────────────────────────────────────────────
def run_once():
    """Одна итерация проверки всех товаров."""
    config = load_config()
    history = load_history()

    for product in config["products"]:
        try:
            check_product(product, config, history)
        except Exception as e:
            log.error("Ошибка при проверке %s: %s", product.get("name"), e)

    save_history(history)
    log.info("История сохранена в %s", HISTORY_FILE)


def run_loop():
    """Непрерывный цикл с паузами (альтернатива cron)."""
    config = load_config()
    interval = config.get("check_interval_hours", 4) * 3600

    log.info("🚀 Price Monitor запущен. Интервал: %d ч.", interval // 3600)
    while True:
        run_once()
        log.info("Следующая проверка через %d ч.", interval // 3600)
        time.sleep(interval)


if __name__ == "__main__":
    import sys
    if "--loop" in sys.argv:
        run_loop()
    else:
        run_once()
