import re
import unicodedata

from src.core.errors import ValidationError


def _slugify_identifier(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    without_accents = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", without_accents).strip("-").lower()
    return slug or "livro"


def resolve_book_key(raw: str | None, filename: str | None = None) -> str:
    """ISBN opcional: usa campo, nome do arquivo (se for ISBN) ou slug do arquivo."""
    if raw and raw.strip():
        cleaned = re.sub(r"[^0-9Xx]", "", raw.strip())
        if cleaned:
            return normalize_isbn(raw)

    if filename:
        stem = (filename or "").rsplit(".", 1)[0].strip()
        if stem:
            try:
                return normalize_isbn(stem)
            except ValidationError:
                return _slugify_identifier(stem)

    raise ValidationError("Informe um ISBN ou use um arquivo PDF com nome identificável.")


_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def validate_book_key(raw: str) -> str:
    """Aceita ISBN (10/13) ou slug gerado a partir do nome do arquivo."""
    cleaned = (raw or "").strip()
    if not cleaned:
        raise ValidationError("Identificador do livro obrigatorio.")
    if len(cleaned) > 128:
        raise ValidationError("Identificador do livro muito longo (max. 128 caracteres).")

    digits = re.sub(r"[^0-9Xx]", "", cleaned)
    if len(digits) in (10, 13):
        try:
            return normalize_isbn(cleaned)
        except ValidationError:
            pass

    if _SLUG_PATTERN.fullmatch(cleaned):
        return cleaned

    raise ValidationError("Identificador do livro invalido.")


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
