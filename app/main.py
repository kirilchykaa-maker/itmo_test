from pathlib import Path
from contextlib import asynccontextmanager
import platform
import asyncio
import subprocess
import sys
import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from dotenv import load_dotenv

# Загрузка переменных окружения из .env (если есть)
load_dotenv()

# Установка совместимой политики цикла событий для Windows
if platform.system() == "Windows":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

DATA_DIR = Path("data")
LATEST_FILE = DATA_DIR / "latest.txt"
PROCESSED_DIR = Path("data/processed")

LATEST_PDF: Path | None = None
BOT_PROC: subprocess.Popen | None = None

# Флаг запуска первичных задач (скачивание/конвертация) при старте
STARTUP_RUN_JOBS = os.getenv("STARTUP_RUN_JOBS", "1").lower() in ("1", "true", "yes", "on")


def run_cmd(args: list[str]) -> None:
    subprocess.run(args, check=True)


def start_bot_subprocess() -> subprocess.Popen | None:
    # Бот сам подхватит TELEGRAM_BOT_TOKEN из .env через python-dotenv
    token_present = os.getenv("TELEGRAM_BOT_TOKEN") is not None
    if not token_present:
        # Не блокируем запуск сервера, просто предупреждаем
        logging.warning("TELEGRAM_BOT_TOKEN не задан — Telegram-бот не будет запущен")
        return None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "services.telegram_bot"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            cwd=str(Path.cwd()),
            env=os.environ.copy(),
            creationflags=(subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0),
        )
        logging.info("Telegram-бот запущен как подпроцесс (polling)")
        return proc
    except Exception as e:
        logging.exception("Не удалось запустить Telegram-бот: %s", e)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global LATEST_PDF, BOT_PROC

    j = False
    if j:
        # Выполняем downloader и converter как отдельные скрипты ДО запуска сервера
        run_cmd([sys.executable, "-m", "src.downloader"])
        if not LATEST_FILE.exists():
            raise RuntimeError("Не удалось определить путь к последнему PDF")
        pdf_path = Path(LATEST_FILE.read_text(encoding="utf-8").strip())
        run_cmd([sys.executable, "-m", "src.converter", str(pdf_path)])
        LATEST_PDF = pdf_path
    else:
        # Режим без первичных задач: пробуем использовать уже имеющийся latest.txt
        if LATEST_FILE.exists():
            pdf_path = Path(LATEST_FILE.read_text(encoding="utf-8").strip())
            LATEST_PDF = pdf_path if pdf_path.exists() else None
        else:
            LATEST_PDF = None

    # Запускаем Telegram-бота (если задан токен)
    BOT_PROC = start_bot_subprocess()

    yield
    # Завершение: останавливаем бота, если он запущен
    if BOT_PROC is not None:
        try:
            BOT_PROC.terminate()
            try:
                BOT_PROC.wait(timeout=5)
            except Exception:
                BOT_PROC.kill()
        except Exception:
            pass


app = FastAPI(title="Study Plan Parser", lifespan=lifespan)


@app.get("/")
def root():
    return {"service": "study-plan-parser", "endpoints": ["/status", "/files/{pdf|txt|xml|structured}"]}


@app.get("/status")
def status():
    if LATEST_PDF is None:
        return {"ready": False, "startup_run_jobs": STARTUP_RUN_JOBS}
    stem = LATEST_PDF.stem
    return {
        "ready": True,
        "startup_run_jobs": STARTUP_RUN_JOBS,
        "pdf": str(LATEST_PDF),
        "txt": str(PROCESSED_DIR / f"{stem}.txt"),
        "xml": str(PROCESSED_DIR / f"{stem}.xml"),
        "structured": str(PROCESSED_DIR / f"{stem}.structured.xml"),
        "bot_running": BOT_PROC is not None and (BOT_PROC.poll() is None),
    }


@app.get("/files/{kind}")
def get_file(kind: str):
    if LATEST_PDF is None:
        raise HTTPException(503, "Ещё не готово")
    stem = LATEST_PDF.stem
    mapping = {
        "pdf": LATEST_PDF,
        "txt": PROCESSED_DIR / f"{stem}.txt",
        "xml": PROCESSED_DIR / f"{stem}.xml",
        "structured": PROCESSED_DIR / f"{stem}.structured.xml",
    }
    path = mapping.get(kind)
    if path is None or not Path(path).exists():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True) 