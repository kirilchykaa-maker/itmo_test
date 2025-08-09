from pathlib import Path
import subprocess
import argparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

DEFAULT_URL = "https://abit.itmo.ru/program/master/ai"
DATA_DIR = Path("data")
DOWNLOADS_DIR = DATA_DIR / "downloads"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
LATEST_FILE = DATA_DIR / "latest.txt"


def ensure_playwright_browser() -> None:
    try:
        result = subprocess.run(
            ["python", "-m", "playwright", "install", "chromium"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            subprocess.run(["python", "-m", "playwright", "install", "chromium"], check=False)
    except Exception:
        pass


def download_pdf(url: str = DEFAULT_URL, save_as: Path | None = None) -> Path:
    ensure_playwright_browser()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, locale="ru-RU")
        page = context.new_page()

        page.goto(url, wait_until="networkidle", timeout=60_000)

        try:
            button = page.get_by_role("button", name="Скачать учебный план")
            button.scroll_into_view_if_needed()
            with page.expect_download(timeout=30_000) as dl_info:
                button.click()
            download = dl_info.value

            target = save_as if save_as is not None else DOWNLOADS_DIR / "study_plan_itmo_ai.pdf"
            try:
                suggested = download.suggested_filename
                if suggested and save_as is None:
                    target = DOWNLOADS_DIR / suggested
            except Exception:
                pass

            download.save_as(str(target))
            return target.resolve()
        except PlaywrightTimeoutError:
            raise SystemExit("Не удалось найти кнопку или получить загрузку (таймаут).")
        finally:
            context.close()
            browser.close()


async def download_pdf_async(url: str = DEFAULT_URL, save_as: Path | None = None) -> Path:
    ensure_playwright_browser()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=True, locale="ru-RU")
        page = await context.new_page()

        await page.goto(url, wait_until="networkidle", timeout=60_000)

        try:
            button = page.get_by_role("button", name="Скачать учебный план")
            await button.scroll_into_view_if_needed()
            async with page.expect_download(timeout=30_000) as dl_info:
                await button.click()
            download = await dl_info.value

            target = save_as if save_as is not None else DOWNLOADS_DIR / "study_plan_itmo_ai.pdf"
            try:
                suggested = download.suggested_filename
                if suggested and save_as is None:
                    target = DOWNLOADS_DIR / suggested
            except Exception:
                pass

            await download.save_as(str(target))
            await context.close()
            await browser.close()
            return target.resolve()
        except Exception:
            await context.close()
            await browser.close()
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Download ITMO study plan PDF")
    parser.add_argument("--url", default=DEFAULT_URL, help="Источник URL")
    parser.add_argument("--out", default=None, help="Путь для сохранения PDF")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else None
    pdf = download_pdf(args.url, out_path)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        LATEST_FILE.write_text(str(pdf), encoding="utf-8")
    except Exception:
        pass
    print(str(pdf))


if __name__ == "__main__":
    main() 