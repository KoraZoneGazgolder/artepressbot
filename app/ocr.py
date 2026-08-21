from __future__ import annotations

import logging
import re
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract

from app.db import parse_bp

log = logging.getLogger(__name__)

TESS_CFGS = (
    "--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789",
    "--oem 3 --psm 11 -c tessedit_char_whitelist=0123456789",
    "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789",
    "--oem 3 --psm 13 -c tessedit_char_whitelist=0123456789",
)
NUM_RE = re.compile(r"\d{2,3}")
PAIR_RE = re.compile(r"(\d{2,3})\s*/\s*(\d{2,3})")

# A, B, C, D, E, F, G
SEGMENTS = {
    (1, 1, 1, 1, 1, 1, 0): "0",
    (0, 1, 1, 0, 0, 0, 0): "1",
    (1, 1, 0, 1, 1, 0, 1): "2",
    (1, 1, 1, 1, 0, 0, 1): "3",
    (0, 1, 1, 0, 0, 1, 1): "4",
    (1, 0, 1, 1, 0, 1, 1): "5",
    (1, 0, 1, 1, 1, 1, 1): "6",
    (1, 1, 1, 0, 0, 0, 0): "7",
    (1, 1, 1, 1, 1, 1, 1): "8",
    (1, 1, 1, 1, 0, 1, 1): "9",
}


def extract_bp_from_image(data: bytes) -> tuple[int, int, int] | None:
    bgr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        image = Image.open(BytesIO(data)).convert("RGB")
        bgr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    bgr = _fit_cv(bgr, 1800)

    candidates: list[tuple[int, int, int]] = []

    lcd = _seven_seg_reading(bgr)
    if lcd:
        candidates.append(lcd)

    texts = _tesseract_texts(bgr)
    log.info("OCR text samples: %s", texts[:6])
    for text in texts:
        parsed = _from_text(text)
        if parsed:
            candidates.append(parsed)

    merged_nums = []
    for text in texts:
        merged_nums.extend(int(part) for part in NUM_RE.findall(text))
    from_nums = _from_number_list(merged_nums)
    if from_nums:
        candidates.append(from_nums)

    return candidates[0] if candidates else None


def _fit_cv(image: np.ndarray, max_side: int) -> np.ndarray:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image
    scale = max_side / longest
    return cv2.resize(
        image,
        (int(width * scale), int(height * scale)),
        interpolation=cv2.INTER_CUBIC,
    )


def _seven_seg_reading(bgr: np.ndarray) -> tuple[int, int, int] | None:
    crops = [bgr, _center_crop(bgr, 0.78), _center_crop(bgr, 0.6)]
    for crop in crops:
        for binary in _lcd_binaries(crop):
            parsed = _read_rows(binary)
            if parsed:
                return parsed
    return None


def _center_crop(image: np.ndarray, fraction: float) -> np.ndarray:
    height, width = image.shape[:2]
    keep_w = int(width * fraction)
    keep_h = int(height * fraction)
    x0 = (width - keep_w) // 2
    y0 = (height - keep_h) // 2
    return image[y0 : y0 + keep_h, x0 : x0 + keep_w]


def _lcd_binaries(bgr: np.ndarray) -> list[np.ndarray]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    results: list[np.ndarray] = []
    for source in (clahe, gray):
        adaptive = cv2.adaptiveThreshold(
            source, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 8
        )
        _, otsu = cv2.threshold(source, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        for raw in (adaptive, otsu, 255 - adaptive, 255 - otsu):
            closed = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, kernel, iterations=1)
            results.append(closed)
    return results


def _read_rows(binary: np.ndarray) -> tuple[int, int, int] | None:
    height, width = binary.shape[:2]
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h < height * 0.06 or h > height * 0.7:
            continue
        if w < 4 or h < 12:
            continue
        aspect = w / h
        if aspect < 0.12 or aspect > 0.95:
            continue
        if cv2.contourArea(contour) < 20:
            continue
        boxes.append((x, y, w, h))
    if len(boxes) < 6:
        return None

    boxes.sort(key=lambda item: (item[1] + item[3] / 2, item[0]))
    rows: list[dict] = []
    for box in boxes:
        x, y, w, h = box
        cy = y + h / 2
        if not rows or abs(cy - rows[-1]["cy"]) > max(h, rows[-1]["h"]) * 0.55:
            rows.append({"cy": cy, "h": h, "boxes": [box]})
        else:
            rows[-1]["boxes"].append(box)
            n = len(rows[-1]["boxes"])
            rows[-1]["cy"] = (rows[-1]["cy"] * (n - 1) + cy) / n
            rows[-1]["h"] = max(rows[-1]["h"], h)

    ranked = sorted(rows, key=lambda row: -max(b[3] for b in row["boxes"]))
    main_rows = sorted(ranked[:3], key=lambda row: row["cy"])
    if len(main_rows) < 3:
        return None

    numbers: list[int] = []
    for row in main_rows:
        digits = []
        for box in sorted(row["boxes"], key=lambda item: item[0]):
            x, y, w, h = box
            pad_y = max(1, h // 12)
            pad_x = max(1, w // 10)
            roi = binary[
                max(0, y - pad_y) : min(height, y + h + pad_y),
                max(0, x - pad_x) : min(width, x + w + pad_x),
            ]
            digit = _classify_digit(roi)
            if digit is None:
                digits = []
                break
            digits.append(digit)
        if len(digits) < 2:
            return None
        numbers.append(int("".join(digits)))
    return _from_number_list(numbers)


def _classify_digit(roi: np.ndarray) -> str | None:
    if roi.size == 0:
        return None
    roi = cv2.resize(roi, (36, 64), interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(bw) > 127:
        bw = 255 - bw
    h, w = bw.shape
    fill = np.mean(bw) / 255
    if fill < 0.04:
        return None

    def on(y0: float, y1: float, x0: float, x1: float, thresh: float = 0.38) -> int:
        patch = bw[int(h * y0) : max(int(h * y1), int(h * y0) + 1), int(w * x0) : max(int(w * x1), int(w * x0) + 1)]
        if patch.size == 0:
            return 0
        return int(np.mean(patch) / 255 > thresh)

    # Thin digit "1": mostly the right verticals
    if w / h < 0.38 and on(0.12, 0.48, 0.45, 0.95) and on(0.52, 0.88, 0.45, 0.95):
        return "1"

    pattern = (
        on(0.04, 0.16, 0.22, 0.78),  # A
        on(0.14, 0.46, 0.72, 0.98),  # B
        on(0.54, 0.86, 0.72, 0.98),  # C
        on(0.84, 0.96, 0.22, 0.78),  # D
        on(0.54, 0.86, 0.02, 0.28),  # E
        on(0.14, 0.46, 0.02, 0.28),  # F
        on(0.44, 0.56, 0.22, 0.78),  # G
    )
    return _match_segments(pattern)


def _match_segments(pattern: tuple[int, ...]) -> str | None:
    exact = SEGMENTS.get(pattern)
    if exact:
        return exact
    best: str | None = None
    best_dist = 2
    for key, value in SEGMENTS.items():
        dist = sum(int(a != b) for a, b in zip(pattern, key))
        if dist < best_dist:
            best_dist = dist
            best = value
    return best if best_dist <= 1 else None


def _tesseract_texts(bgr: np.ndarray) -> list[str]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    variants = _cv_variants(gray) + _pil_variants(bgr)
    texts: list[str] = []
    for variant in variants:
        if isinstance(variant, np.ndarray):
            source = variant
        else:
            source = variant
        for cfg in TESS_CFGS:
            try:
                text = pytesseract.image_to_string(source, config=cfg)
            except pytesseract.TesseractError:
                continue
            except pytesseract.TesseractNotFoundError:
                return texts
            if text and text.strip():
                texts.append(text)
    return texts


def _cv_variants(gray: np.ndarray) -> list[np.ndarray]:
    scaled = cv2.resize(gray, None, fx=2.2, fy=2.2, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(scaled)
    blur = cv2.GaussianBlur(clahe, (3, 3), 0)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 5
    )
    return [clahe, otsu, 255 - otsu, adaptive, 255 - adaptive]


def _pil_variants(bgr: np.ndarray) -> list[Image.Image]:
    image = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    sharp = ImageEnhance.Contrast(gray.filter(ImageFilter.SHARPEN)).enhance(2.4)
    inverted = ImageOps.invert(sharp)
    binary = sharp.point(lambda px: 255 if px > 130 else 0)
    return [sharp, inverted, binary, ImageOps.invert(binary)]


def _from_text(text: str) -> tuple[int, int, int] | None:
    compact = re.sub(r"[^\d/\s]", " ", text)
    direct = parse_bp(compact)
    if direct:
        return direct
    for line in text.splitlines():
        parsed = parse_bp(re.sub(r"[^\d/\s]", " ", line))
        if parsed:
            return parsed
    for match in PAIR_RE.finditer(text):
        rest = NUM_RE.findall(text[match.end() : match.end() + 50])
        if not rest:
            continue
        parsed = parse_bp(f"{match.group(1)}/{match.group(2)} {rest[0]}")
        if parsed:
            return parsed
    numbers = [int(part) for part in NUM_RE.findall(text)]
    return _from_number_list(numbers)


def _from_number_list(numbers: list[int]) -> tuple[int, int, int] | None:
    for index in range(len(numbers) - 2):
        parsed = parse_bp(
            f"{numbers[index]}/{numbers[index + 1]} {numbers[index + 2]}"
        )
        if parsed:
            return parsed
    return None
