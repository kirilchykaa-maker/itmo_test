from pathlib import Path
from contextlib import asynccontextmanager
import platform
import asyncio
import subprocess
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

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


def run_cmd(args: list[str]) -> None:
    subprocess.run(args, check=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global LATEST_PDF
    # Выполняем downloader и converter как отдельные скрипты ДО запуска сервера
    # 1) Скачать PDF и записать путь в data/latest.txt
    run_cmd(["python", "-m", "src.downloader"])
    if not LATEST_FILE.exists():
        raise RuntimeError("Не удалось определить путь к последнему PDF")
    pdf_path = Path(LATEST_FILE.read_text(encoding="utf-8").strip())
    # 2) Конвертация PDF → TXT/XML/structured
    run_cmd(["python", "-m", "src.converter", str(pdf_path)])
    LATEST_PDF = pdf_path

    yield
    # Завершение: ничего не требуется


app = FastAPI(title="Study Plan Parser", lifespan=lifespan)


@app.get("/")
def root():
    return {"service": "study-plan-parser", "endpoints": ["/status", "/files/{pdf|txt|xml|structured}"]}


@app.get("/status")
def status():
    if LATEST_PDF is None:
        return {"ready": False}
    stem = LATEST_PDF.stem
    return {
        "ready": True,
        "pdf": str(LATEST_PDF),
        "txt": str(PROCESSED_DIR / f"{stem}.txt"),
        "xml": str(PROCESSED_DIR / f"{stem}.xml"),
        "structured": str(PROCESSED_DIR / f"{stem}.structured.xml"),
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