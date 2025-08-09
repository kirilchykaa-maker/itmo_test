# Сбор и парсинг учебного плана ИТМО (AI)

## Структура

- `app/` — FastAPI-приложение (`uvicorn`)
- `src/` — модули:
  - `src/downloader.py` — загрузка PDF через Playwright → `data/downloads`
  - `src/converter.py` — конвертация PDF → TXT/XML/structured XML → `data/processed`
- `data/` — артефакты:
  - `data/downloads` — загруженные PDF
  - `data/processed` — результаты конвертации

## Установка и запуск (Windows / PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m playwright install chromium
.\.venv\Scripts\uvicorn app.main:app --reload
```

После старта сервер сходит на страницу, скачает PDF и подготовит файлы в `data/processed`.

Эндпоинты:
- `GET /` — информация о сервисе
- `GET /status` — статус и пути файлов
- `GET /files/{pdf|txt|xml|structured}` — скачать соответствующий файл 