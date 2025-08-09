# Сбор и парсинг учебного плана ИТМО (AI)

## Структура

- `app/` — FastAPI-приложение (`uvicorn`)
- `src/` — модули:
  - `src/downloader.py` — загрузка PDF через Playwright → `data/downloads`
  - `src/converter.py` — конвертация PDF → TXT/XML/structured XML → `data/processed`
- `services/` — фоновые сервисы
  - `services/telegram_bot.py` — Telegram echo-бот (polling)
- `data/` — артефакты:
  - `data/downloads` — загруженные PDF
  - `data/processed` — результаты конвертации
  - `data/latest.txt` — путь к последнему PDF

## Переменные окружения

- `TELEGRAM_BOT_TOKEN` — токен вашего Telegram-бота

Создайте файл `.env` в корне (см. `ENV_EXAMPLE.txt`).

## Установка и запуск (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\uvicorn app.main:app --reload
```

После старта сервис сходит на страницу, скачает PDF и подготовит файлы в `data/processed`.

Эндпоинты:
- `GET /` — информация о сервисе
- `GET /status` — статус и пути файлов
- `GET /files/{pdf|txt|xml|structured}` — скачать соответствующий файл

## Запуск Telegram-бота (echo)

```powershell
$env:TELEGRAM_BOT_TOKEN = "<ваш_токен>"
.\.venv\Scripts\python -m services.telegram_bot
```

Бот отвечает тем же текстом, что получает. Для постоянного запуска используйте системный планировщик/сервис. 