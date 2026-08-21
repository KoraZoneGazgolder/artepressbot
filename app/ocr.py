from __future__ import annotations

import re
from io import BytesIO

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract

from app.db import parse_bp

TESS_CFG = "--psm 6 -c tessedit_char_whitelist=0123456789/"
NUM_RE = re.compile(r"\d{2,3}")
PAIR_RE = re.compile(r"(\d{2,3})\s*/\s*(\d{2,3})")


def extract_bp_from_image(data: bytes) -> tuple[int, int, int] | None:
    image = Image.open(BytesIO(data))
    if image.mode not in {"RGB", "L"}:
        image = image.convert("RGB")
    image = _fit(image, 1600)

    texts: list[str] = []
    for variant in _variants(image):
        try:
            texts.append(pytesseract.image_to_string(variant, config=TESS_CFG))
        except pytesseract.TesseractError:
            continue
    return _pick_from_texts(texts)


def _fit(image: Image.Image, max_side: int) -> Image.Image:
    width, height = image.size
    longest = max(width, height)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return image.resize((int(width * scale), int(height * scale)), Image.Resampling.LANCZOS)


def _variants(image: Image.Image) -> list[Image.Image]:
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    sharp = gray.filter(ImageFilter.SHARPEN)
    contrast = ImageEnhance.Contrast(sharp).enhance(2.0)
    inverted = ImageOps.invert(contrast)
    binary = contrast.point(lambda px: 255 if px > 140 else 0)
    binary_inv = ImageOps.invert(binary)
    return [contrast, inverted, binary, binary_inv]


def _pick_from_texts(texts: list[str]) -> tuple[int, int, int] | None:
    for text in texts:
        parsed = _from_text(text)
        if parsed:
            return parsed
    return None


def _from_text(text: str) -> tuple[int, int, int] | None:
    compact = re.sub(r"[^\d/\s]", " ", text)
    direct = parse_bp(compact)
    if direct:
        return direct

    for line in text.splitlines():
        cleaned = re.sub(r"[^\d/\s]", " ", line)
        parsed = parse_bp(cleaned)
        if parsed:
            return parsed

    for match in PAIR_RE.finditer(text):
        start = match.end()
        rest = NUM_RE.findall(text[start : start + 40])
        pulse = int(rest[0]) if rest else None
        if pulse is None:
            continue
        parsed = parse_bp(f"{match.group(1)}/{match.group(2)} {pulse}")
        if parsed:
            return parsed

    numbers = [int(part) for part in NUM_RE.findall(text)]
    for index in range(len(numbers) - 2):
        parsed = parse_bp(
            f"{numbers[index]}/{numbers[index + 1]} {numbers[index + 2]}"
        )
        if parsed:
            return parsed
    return None
