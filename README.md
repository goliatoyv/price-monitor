# Price Monitor — Joe's New Balance Outlet

Агент мониторит цены и шлёт письмо на Gmail когда цена упала или достигла нужного значения.
Работает в облаке GitHub — Mac держать включённым не нужно.

---

## Быстрый старт (для себя или друга)

### Шаг 1 — Форкнуть репозиторий
Нажать **Fork** в правом верхнем углу страницы на GitHub.

### Шаг 2 — Добавить Gmail App Password как секрет

1. В своём аккаунте Google включи 2FA:
   **myaccount.google.com → Безопасность → Двухэтапная аутентификация**

2. Создай App Password:
   **myaccount.google.com → Безопасность → Пароли приложений**
   Выбери "Другое" → назови "Price Monitor" → скопируй пароль вида `xxxx xxxx xxxx xxxx`

3. В форкнутом репо на GitHub:
   **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `EMAIL_PASSWORD`
   - Value: вставить App Password

### Шаг 3 — Настроить товары в config.json

Отредактировать файл `config.json` прямо на GitHub (карандаш справа):

```json
{
  "products": [
    {
      "name": "Название товара",
      "url": "https://www.joesnewbalanceoutlet.com/pd/...",
      "target_price": 90.00,
      "size": "M8"
    }
  ],
  "check_interval_hours": 4,
  "notifications": {
    "email": {
      "enabled": true,
      "smtp_host": "smtp.gmail.com",
      "smtp_port": 587,
      "sender": "твой@gmail.com",
      "password": "",
      "recipients": ["твой@gmail.com"]
    }
  }
}
```

> `password` оставь пустым — пароль берётся из GitHub Secret.

### Шаг 4 — Включить Actions

В форкнутом репо: **Actions → "I understand my workflows, enable them"**

Готово. Агент будет проверять цены каждые 4 часа автоматически.

---

## Ручной запуск

**Actions → Price Monitor → Run workflow** — проверит прямо сейчас.

## Посмотреть историю цен

**Actions → последний запуск → Artifacts → price-history** — скачать `price_history.json` и `monitor.log`.

## Добавить ещё товар

Добавить объект в массив `products` в `config.json`. Один запуск проверяет все товары.

---

## Файлы

| Файл | Описание |
|---|---|
| `config.json` | Товары, email, интервал |
| `price_monitor.py` | Скрипт мониторинга |
| `.github/workflows/price_monitor.yml` | Расписание запуска |
| `price_history.json` | История цен (создаётся автоматически) |
