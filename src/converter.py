from pathlib import Path
from typing import Optional, Iterable, List, Dict, Any
import re
import argparse

PROCESSED_DIR = Path("data/processed")
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    from pdfminer.high_level import extract_text as pdfminer_extract_text
    from pdfminer.layout import LAParams
    from pdfminer.pdfparser import PDFSyntaxError
except Exception:
    pdfminer_extract_text = None
    LAParams = None
    PDFSyntaxError = Exception  # type: ignore

try:
    import pdfplumber  # type: ignore
except Exception:
    pdfplumber = None  # type: ignore


def _clean_lines(lines: Iterable[str]) -> str:
    cleaned: list[str] = []
    for line in lines:
        s = line.replace("\xa0", " ").strip()
        if not s:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        cleaned.append(s)

    def is_noise_token(token: str) -> bool:
        if len(token) == 1 and token.isalpha():
            return True
        return False

    result_lines: list[str] = []
    for s in cleaned:
        if s == "":
            result_lines.append(s)
            continue
        tokens = s.split()
        if tokens and all(is_noise_token(t) for t in tokens):
            continue
        result_lines.append(s)
    return "\n".join(result_lines).strip() + "\n"


def extract_text_pymupdf(pdf_path: Path) -> str:
    assert fitz is not None
    doc = fitz.open(pdf_path)
    lines: list[str] = []
    for page in doc:
        text = page.get_text("text")
        if not text:
            text = page.get_text("blocks")
            if isinstance(text, list):
                text = "\n".join(block[4] for block in text if len(block) > 4 and isinstance(block[4], str))
        lines.extend(text.splitlines())
    doc.close()
    return _clean_lines(lines)


def extract_text_pdfminer(pdf_path: Path) -> str:
    assert pdfminer_extract_text is not None and LAParams is not None
    laparams = LAParams(line_overlap=0.5, char_margin=2.0, line_margin=0.5, word_margin=0.1, boxes_flow=0.5)
    text = pdfminer_extract_text(str(pdf_path), laparams=laparams)
    return _clean_lines(text.splitlines())


def pdf_to_txt(pdf_path: Path, txt_path: Optional[Path] = None) -> Path:
    if txt_path is None:
        txt_path = PROCESSED_DIR / f"{pdf_path.stem}.txt"
    text: Optional[str] = None
    if fitz is not None:
        try:
            text = extract_text_pymupdf(pdf_path)
        except Exception:
            text = None
    if text is None and pdfminer_extract_text is not None:
        try:
            text = extract_text_pdfminer(pdf_path)
        except Exception:
            text = None
    if text is None:
        raise RuntimeError("Не удалось извлечь текст: нет доступного backend или произошла ошибка.")
    txt_path.write_text(text, encoding="utf-8")
    return txt_path


def xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def pdf_to_xml(pdf_path: Path, xml_path: Optional[Path] = None) -> Path:
    if xml_path is None:
        xml_path = PROCESSED_DIR / f"{pdf_path.stem}.xml"
    txt_path = PROCESSED_DIR / f"{pdf_path.stem}.txt"
    if not txt_path.exists():
        pdf_to_txt(pdf_path, txt_path)
    content = txt_path.read_text(encoding="utf-8")
    xml = f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<document>\n{xml_escape(content)}\n</document>\n"
    xml_path.write_text(xml, encoding="utf-8")
    return xml_path


_num_re = re.compile(r"^\d{1,4}$")
_block_re = re.compile(r"^Блок\s+(\d+)\.(.*)$", re.IGNORECASE)
_sem_re = re.compile(r"(\d)\s*семест", re.IGNORECASE)
_total_keywords = ["итог", "итоги", "всего", "сумма"]


def _is_int_line(line: str) -> bool:
    return bool(_num_re.match(line.strip()))


def _is_total_line(line: str) -> bool:
    s = line.lower()
    return any(k in s for k in _total_keywords)


def _try_parse_three_numbers(lines: List[str], idx: int) -> Optional[Dict[str, int]]:
    if idx + 2 < len(lines):
        a, b, c = lines[idx], lines[idx + 1], lines[idx + 2]
        if _is_int_line(a) and _is_int_line(b) and _is_int_line(c):
            return {"credits": int(a), "hours": int(b), "semester": int(c)}
    return None


def _looks_like_section_title(line: str) -> bool:
    if not line:
        return False
    if _sem_re.search(line):
        return True
    keywords = [
        "Обязательные дисциплины",
        "Пул выборных дисциплин",
        "Практика по выбору",
        "Универсальная (надпрофессиональная) подготовка",
        "Государственная итоговая аттестация",
        "Факультативные модули",
        "Практика",
        "ГИА",
    ]
    return any(k.lower() in line.lower() for k in keywords)


def parse_study_plan_lines(lines: List[str]) -> Dict[str, Any]:
    data: Dict[str, Any] = {"blocks": []}
    current_block: Optional[Dict[str, Any]] = None
    current_section: Optional[Dict[str, Any]] = None

    buffer_name: List[str] = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        m_block = _block_re.match(line)
        if m_block:
            current_block = {"title": line.strip(), "sections": []}
            data["blocks"].append(current_block)
            current_section = None
            buffer_name.clear()
            i += 1
            consumed = 0
            while i < n and _is_int_line(lines[i].strip()):
                consumed += 1
                i += 1
                if consumed >= 4:
                    break
            continue

        if _looks_like_section_title(line):
            sem = None
            m_sem = _sem_re.search(line)
            if m_sem:
                try:
                    sem = int(m_sem.group(1))
                except Exception:
                    sem = None
            current_section = {"title": line.strip(), "semester": sem, "disciplines": []}
            if current_block is None:
                current_block = {"title": "Блок", "sections": []}
                data["blocks"].append(current_block)
            current_block["sections"].append(current_section)
            buffer_name.clear()
            i += 1
            skip = 0
            while i < n and _is_int_line(lines[i].strip()) and skip < 3:
                skip += 1
                i += 1
            continue

        if _is_total_line(line):
            i += 1
            continue

        if not _is_int_line(line):
            buffer_name.append(line)
            triple = _try_parse_three_numbers(lines, i + 1)
            if triple:
                name = " ".join(buffer_name).strip()
                disc = {
                    "title": name,
                    "credits": triple["credits"],
                    "hours": triple["hours"],
                    "semester": triple["semester"],
                }
                if current_section is None:
                    current_section = {"title": "Разное", "semester": None, "disciplines": []}
                    if current_block is None:
                        current_block = {"title": "Блок", "sections": []}
                        data["blocks"].append(current_block)
                    current_block["sections"].append(current_section)
                current_section["disciplines"].append(disc)
                buffer_name.clear()
                i += 4
                continue
            else:
                i += 1
                continue

        i += 1

    return data


def dict_to_structured_xml(data: Dict[str, Any]) -> str:
    lines: List[str] = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<study_plan>"]
    for block in data.get("blocks", []):
        title = xml_escape(str(block.get("title", "")))
        lines.append(f"  <block title=\"{title}\">")
        for section in block.get("sections", []):
            stitle = xml_escape(str(section.get("title", "")))
            sem = section.get("semester")
            sem_attr = f" semester=\"{sem}\"" if sem is not None else ""
            lines.append(f"    <section title=\"{stitle}\"{sem_attr}>")
            for disc in section.get("disciplines", []):
                dtitle = xml_escape(str(disc.get("title", "")))
                credits = disc.get("credits")
                hours = disc.get("hours")
                dsem = disc.get("semester")
                attrs = [f"title=\"{dtitle}\""]
                if credits is not None:
                    attrs.append(f"credits=\"{credits}\"")
                if hours is not None:
                    attrs.append(f"hours=\"{hours}\"")
                if dsem is not None:
                    attrs.append(f"semester=\"{dsem}\"")
                lines.append("      <discipline " + " ".join(attrs) + "/>")
            lines.append("    </section>")
        lines.append("  </block>")
    lines.append("</study_plan>\n")
    return "\n".join(lines)


def pdf_to_structured_xml(pdf_path: Path, out_path: Optional[Path] = None) -> Path:
    txt_path = PROCESSED_DIR / f"{pdf_path.stem}.txt"
    if not txt_path.exists():
        pdf_to_txt(pdf_path, txt_path)
    raw = txt_path.read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines()]
    data = parse_study_plan_lines(lines)
    xml = dict_to_structured_xml(data)
    if out_path is None:
        out_path = PROCESSED_DIR / f"{pdf_path.stem}.structured.xml"
    out_path.write_text(xml, encoding="utf-8")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert PDF to TXT/XML/structured XML")
    parser.add_argument("pdf", help="Путь к PDF")
    parser.add_argument("--structured", action="store_true", help="Генерировать только structured XML")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(f"Файл не найден: {pdf_path}")

    if args.structured:
        out = pdf_to_structured_xml(pdf_path)
        print(str(out))
    else:
        txt = pdf_to_txt(pdf_path)
        xml = pdf_to_xml(pdf_path)
        st = pdf_to_structured_xml(pdf_path)
        print(str(txt))
        print(str(xml))
        print(str(st))


if __name__ == "__main__":
    main() 