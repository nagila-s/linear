import re

from src.core.errors import ValidationError


def normalize_isbn(raw: str) -> str:
    cleaned = re.sub(r"[^0-9Xx]", "", (raw or "").strip())
    if len(cleaned) == 10:
        if not _is_valid_isbn10(cleaned):
            raise ValidationError("ISBN-10 invalido.")
        return cleaned.upper()
    if len(cleaned) == 13:
        if not _is_valid_isbn13(cleaned):
            raise ValidationError("ISBN-13 invalido.")
        return cleaned
    raise ValidationError("ISBN deve ter 10 ou 13 caracteres validos.")


def _is_valid_isbn10(isbn: str) -> bool:
    if not re.match(r"^\d{9}[\dXx]$", isbn):
        return False
    total = 0
    for idx, ch in enumerate(isbn[:9], start=1):
        total += idx * int(ch)
    check = isbn[9].upper()
    total += 10 * (10 if check == "X" else int(check))
    return total % 11 == 0


def _is_valid_isbn13(isbn: str) -> bool:
    if not re.match(r"^\d{13}$", isbn):
        return False
    total = 0
    for idx, ch in enumerate(isbn[:12]):
        weight = 1 if idx % 2 == 0 else 3
        total += int(ch) * weight
    check_digit = (10 - (total % 10)) % 10
    return check_digit == int(isbn[-1])
