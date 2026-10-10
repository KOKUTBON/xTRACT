"""Text, date, and decimal normalization helpers for metadata extraction."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

MONTHS: dict[str, int] = {
    # 1
    "january": 1, "jan": 1, "gennaio": 1, "gen": 1, "janvier": 1, "janv": 1, "enero": 1, "ene": 1, "januar": 1, "jänner": 1, "jaenner": 1, "janner": 1,
    # 2
    "february": 2, "feb": 2, "febbraio": 2, "février": 2, "fevrier": 2, "févr": 2, "fevr": 2, "febrero": 2, "februar": 2,
    # 3
    "march": 3, "mar": 3, "marzo": 3, "mars": 3, "märz": 3, "maerz": 3, "mrz": 3,
    # 4
    "april": 4, "apr": 4, "aprile": 4, "avril": 4, "avr": 4, "abril": 4, "abr": 4,
    # 5
    "may": 5, "maggio": 5, "mag": 5, "mai": 5, "mayo": 5,
    # 6
    "june": 6, "jun": 6, "giugno": 6, "giu": 6, "juin": 6, "junio": 6, "juni": 6,
    # 7
    "july": 7, "jul": 7, "luglio": 7, "lug": 7, "juillet": 7, "juil": 7, "julio": 7, "juli": 7,
    # 8
    "august": 8, "aug": 8, "agosto": 8, "ago": 8, "août": 8, "aout": 8,
    # 9
    "september": 9, "sep": 9, "sept": 9, "settembre": 9, "set": 9, "sett": 9, "septembre": 9, "septiembre": 9, "setiembre": 9,
    # 10
    "october": 10, "oct": 10, "ottobre": 10, "ott": 10, "octobre": 10, "octubre": 10, "oktober": 10, "okt": 10,
    # 11
    "november": 11, "nov": 11, "novembre": 11, "noviembre": 11,
    # 12
    "december": 12, "dec": 12, "dicembre": 12, "dic": 12, "décembre": 12, "decembre": 12, "déc": 12, "diciembre": 12, "dezember": 12, "dez": 12,
}  # fmt: skip


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.split()).strip().lower()


def title_case(value: str) -> str:
    return " ".join(part.capitalize() for part in value.strip().split())


def digits_only(value: str) -> str:
    return "".join(char for char in value if char.isdigit())


def normalize_fiscal_code(value: str | None) -> str | None:
    """Normalize national tax identifiers, specifically Italian Codice Fiscale (16 chars) or Partita IVA (11 digits)."""
    if value is None:
        return None
    cleaned = re.sub(r"[\s.\-_/]", "", value).upper()
    if not cleaned:
        return None
    if re.fullmatch(r"[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]", cleaned):
        return cleaned
    if re.fullmatch(r"\d{11}", cleaned):
        return cleaned
    return cleaned if len(cleaned) >= 5 else None


def normalize_iban(value: str | None) -> str | None:
    """Normalize international bank account numbers (IBAN) by stripping formatting."""
    if value is None:
        return None
    cleaned = re.sub(r"[\s.\-_]", "", value).upper()
    if not cleaned:
        return None
    if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", cleaned):
        return cleaned
    return cleaned if len(cleaned) >= 15 else None


def normalize_vat_number(value: str | None) -> str | None:
    """Normalize VAT / tax registration numbers (e.g. IT00000000000, 12345678901)."""
    if value is None:
        return None
    cleaned = re.sub(r"[\s.\-_/]", "", value).upper()
    return cleaned if cleaned else None


def normalize_alphanumeric(value: str | None) -> str | None:
    """Keep only alphanumeric characters, slashes, and hyphens."""
    if value is None:
        return None
    cleaned = re.sub(r"[^\w/\-]", "", value).strip().upper()
    return cleaned if cleaned else None


def _year(value: str) -> int:
    year = int(value)
    return year + 2000 if year < 100 else year


def parse_date(value: str, date_order: str = "DMY") -> str | None:
    """Parse common numeric and written date formats into ISO 8601 (YYYY-MM-DD)."""
    text = value.strip().lower().rstrip(".,;")
    text = re.sub(r"^(?:in data|data|le|il|den|del|on)\s+", "", text).strip()
    try:
        # Match ISO or dot/slash/dash YMD (e.g. 2026-03-12, 2026/03/12, 2026.03.12)
        match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
        if match:
            y, m, d = (int(g) for g in match.groups())
            return date(y, m, d).isoformat()

        # Match 3-part numeric dates
        match = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", text)
        if match:
            first, second, y = match.groups()
            if date_order == "MDY":
                m, d = int(first), int(second)
                if m > 12 and d <= 12:
                    d, m = m, d
            else:  # DMY default
                d, m = int(first), int(second)
                if m > 12 and d <= 12:
                    d, m = m, d
            return date(_year(y), m, d).isoformat()

        # Match YMD with 2-digit year (e.g. 26/03/12 when date_order == "YMD")
        if date_order == "YMD":
            match = re.fullmatch(r"(\d{2,4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
            if match:
                y, m, d = (int(g) for g in match.groups())
                return date(_year(y), m, d).isoformat()

        # Match written: Day Month Year (e.g. "12 marzo 2026", "12 de marzo de 2026", "12. März 2026", "3rd March 2026", "1er mars 2026")
        match = re.fullmatch(
            r"(\d{1,2})(?:st|nd|rd|th|°|er|\.)?\s+(?:de\s+|d['’]\s*)?([^\W\d_]+)\.?,?\s+(?:de\s+)?(\d{2,4})",
            text,
        )
        if match:
            d, month, y = match.groups()
            if month in MONTHS:
                return date(_year(y), MONTHS[month], int(d)).isoformat()

        # Match written: Month Day Year (e.g. "March 3, 2026", "Mar 3, 2026")
        match = re.fullmatch(r"([^\W\d_]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{2,4})", text)
        if match:
            month, d, y = match.groups()
            if month in MONTHS:
                return date(_year(y), MONTHS[month], int(d)).isoformat()
    except ValueError:
        return None
    return None


def parse_decimal(value: str) -> str | None:
    """Normalize amounts such as '1.234,56 €', '$1,234.56', 'CHF 1'234.56', or '(12.30)' into '1234.56'."""
    raw = value.strip()
    if not raw:
        return None
    negative = (
        raw.startswith("-") or (raw.startswith("(") and raw.endswith(")")) or raw.endswith("-")
    )
    cleaned = raw.replace("'", "")
    text = re.sub(r"[^\d,.]", "", cleaned)
    if not text:
        return None
    if "," in text and "." in text:
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
    elif "," in text:
        decimal_sep = "," if re.search(r",\d{1,2}$", text) else None
    elif "." in text:
        decimal_sep = "." if re.search(r"\.\d{1,2}$", text) or text.count(".") == 1 else None
    else:
        decimal_sep = None
    if decimal_sep:
        integer, _, fraction = text.rpartition(decimal_sep)
        integer = re.sub(r"[,.]", "", integer)
        normalized = f"{integer or '0'}.{fraction}"
    else:
        normalized = re.sub(r"[,.]", "", text)
    return f"-{normalized}" if negative else normalized


def apply_normalization(value: str | None, rules: list[str], date_order: str = "DMY") -> str | None:
    if value is None:
        return None
    current = value
    for rule in rules:
        if rule == "strip":
            current = current.strip().strip(":;,").strip()
        elif rule == "collapse_whitespace":
            current = " ".join(current.split())
        elif rule == "title_case":
            current = title_case(current)
        elif rule == "uppercase":
            current = current.upper()
        elif rule == "digits_only":
            current = digits_only(current)
        elif rule == "fiscal_code":
            current = normalize_fiscal_code(current) or current.strip()
        elif rule == "iban":
            current = normalize_iban(current) or current.strip()
        elif rule == "vat_number":
            current = normalize_vat_number(current) or current.strip()
        elif rule == "alphanumeric":
            current = normalize_alphanumeric(current) or current.strip()
        elif rule == "date_iso":
            current = parse_date(current, date_order) or current.strip()
        elif rule == "decimal":
            current = parse_decimal(current) or current.strip()
    return current


def text_lines(pages: list[dict]) -> list[dict]:
    """Merge OCR blocks that share a baseline into reading-order lines."""
    lines: list[dict] = []
    for page in pages:
        blocks = sorted(
            page.get("text_blocks", []),
            key=lambda b: (b["bounding_box"]["top"], b["bounding_box"]["left"]),
        )
        page_lines: list[dict] = []
        for block in blocks:
            box = block["bounding_box"]
            middle = box["top"] + box["height"] / 2
            target = None
            for line in page_lines:
                lbox = line["bounding_box"]
                if lbox["top"] <= middle <= lbox["top"] + lbox["height"]:
                    target = line
                    break
            if target is None:
                page_lines.append(
                    {
                        "page_number": page.get("page_number", 1),
                        "blocks": [block],
                        "bounding_box": dict(box),
                    }
                )
                continue
            target["blocks"].append(block)
            lbox = target["bounding_box"]
            right = max(lbox["left"] + lbox["width"], box["left"] + box["width"])
            bottom = max(lbox["top"] + lbox["height"], box["top"] + box["height"])
            lbox["left"] = min(lbox["left"], box["left"])
            lbox["top"] = min(lbox["top"], box["top"])
            lbox["width"] = right - lbox["left"]
            lbox["height"] = bottom - lbox["top"]
        for line in page_lines:
            line["blocks"].sort(key=lambda b: b["bounding_box"]["left"])
            line["text"] = " ".join(b["text"] for b in line["blocks"]).strip()
            confidences = [b.get("confidence", 0.0) for b in line["blocks"]]
            line["confidence"] = sum(confidences) / len(confidences) if confidences else 0.0
            lines.append(line)
    return [line for line in lines if line["text"]]
