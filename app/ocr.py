from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from io import BytesIO
from itertools import combinations
from pathlib import Path

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
)
NUM_RE = re.compile(r"\d{2,3}")
PAIR_RE = re.compile(r"(\d{2,3})\s*/\s*(\d{2,3})")

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
    bgr = _fit_cv(bgr, 2000)

    found: list[int] = []
    candidates: list[tuple[int, int, int]] = []

    for crop in (bgr, _center_crop(bgr, 0.82), _center_crop(bgr, 0.64)):
        for binary in _digit_masks(crop):
            numbers = _read_by_projection(binary)
            found.extend(numbers)
            parsed = _from_number_list(numbers)
            if parsed:
                candidates.append(parsed)
            parsed = _seven_seg_boxes(binary)
            if parsed:
                candidates.append(parsed)

    ssocr_text = _ssocr_text(bgr)
    if ssocr_text:
        log.info("ssocr: %s", ssocr_text)
        found.extend(int(part) for part in NUM_RE.findall(ssocr_text))
        parsed = _from_text(ssocr_text)
        if parsed:
            candidates.append(parsed)

    texts = _tesseract_texts(bgr)
    log.info("OCR samples: %s", texts[:4])
    for text in texts:
        found.extend(int(part) for part in NUM_RE.findall(text))
        parsed = _from_text(text)
        if parsed:
            candidates.append(parsed)

    if candidates:
        return max(candidates, key=_score_reading)
    return _best_triple(found)


def _score_reading(reading: tuple[int, int, int]) -> int:
    systolic, diastolic, pulse = reading
    score = 0
    if 90 <= systolic <= 180:
        score += 3
    if 55 <= diastolic <= 105:
        score += 3
    if 45 <= pulse <= 110:
        score += 2
    gap = systolic - diastolic
    if 15 <= gap <= 80:
        score += 3
    else:
        score -= 2
    return score


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


def _center_crop(image: np.ndarray, fraction: float) -> np.ndarray:
    height, width = image.shape[:2]
    keep_w = int(width * fraction)
    keep_h = int(height * fraction)
    x0 = (width - keep_w) // 2
    y0 = (height - keep_h) // 2
    return image[y0 : y0 + keep_h, x0 : x0 + keep_w]


def _digit_masks(bgr: np.ndarray) -> list[np.ndarray]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8)).apply(gray)
    wide = cv2.getStructuringElement(cv2.MORPH_RECT, (21, 5))
    blackhat = cv2.morphologyEx(clahe, cv2.MORPH_BLACKHAT, wide)
    boosted = cv2.normalize(blackhat, None, 0, 255, cv2.NORM_MINMAX)
    boosted = boosted.astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    masks: list[np.ndarray] = []
    for source in (boosted, clahe, gray):
        adaptive = cv2.adaptiveThreshold(
            source, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 5
        )
        _, otsu = cv2.threshold(source, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        for raw in (adaptive, 255 - adaptive, otsu, 255 - otsu):
            if np.mean(raw) > 127:
                raw = 255 - raw
            closed = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, kernel, iterations=1)
            masks.append(closed)
    return masks


def _runs(flags: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start = None
    for index, flag in enumerate(flags.tolist()):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def _read_by_projection(binary: np.ndarray) -> list[int]:
    height, width = binary.shape[:2]
    row_proj = (binary > 0).sum(axis=1).astype(np.float64)
    if row_proj.max() < width * 0.03:
        return []
    kernel = np.ones(max(3, height // 80), dtype=np.float64)
    kernel /= len(kernel)
    smooth = np.convolve(row_proj, kernel, mode="same")
    bands = _runs(smooth > max(smooth.max() * 0.18, width * 0.025))
    bands = [(a, b) for a, b in bands if b - a >= height * 0.05]
    bands.sort(key=lambda item: -(item[1] - item[0]))
    bands = sorted(bands[:3], key=lambda item: item[0])
    numbers: list[int] = []
    for y0, y1 in bands:
        band = binary[y0:y1, :]
        number = _read_band(band)
        if number is not None:
            numbers.append(number)
    return numbers


def _read_band(band: np.ndarray) -> int | None:
    height, width = band.shape[:2]
    col_proj = (band > 0).sum(axis=0).astype(np.float64)
    if col_proj.max() < height * 0.12:
        return None
    digits: list[str] = []
    for x0, x1 in _runs(col_proj > max(col_proj.max() * 0.18, height * 0.08)):
        if x1 - x0 < 3:
            continue
        pad = max(1, (x1 - x0) // 8)
        roi = band[:, max(0, x0 - pad) : min(width, x1 + pad)]
        if roi.shape[1] < 3:
            continue
        digit = _classify_digit(roi)
        if digit:
            digits.append(digit)
    if len(digits) < 2:
        return None
    value = int("".join(digits[:3]))
    if 30 <= value <= 250:
        return value
    return None


def _seven_seg_boxes(binary: np.ndarray) -> tuple[int, int, int] | None:
    height, width = binary.shape[:2]
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if h < height * 0.045 or h > height * 0.75:
            continue
        if w < 3 or h < 10:
            continue
        aspect = w / h
        if aspect < 0.08 or aspect > 1.05:
            continue
        boxes.append((x, y, w, h))
    if len(boxes) < 5:
        return None

    rows: list[dict] = []
    for box in sorted(boxes, key=lambda item: item[1] + item[3] / 2):
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
    numbers: list[int] = []
    for row in main_rows:
        digits: list[str] = []
        for box in sorted(row["boxes"], key=lambda item: item[0]):
            x, y, w, h = box
            pad_y = max(1, h // 12)
            pad_x = max(1, w // 8)
            roi = binary[
                max(0, y - pad_y) : min(height, y + h + pad_y),
                max(0, x - pad_x) : min(width, x + w + pad_x),
            ]
            digit = _classify_digit(roi)
            if digit:
                digits.append(digit)
        if len(digits) >= 2:
            numbers.append(int("".join(digits[:3])))
    return _from_number_list(numbers)


def _classify_digit(roi: np.ndarray) -> str | None:
    if roi.size == 0:
        return None
    roi = cv2.resize(roi, (40, 72), interpolation=cv2.INTER_CUBIC)
    _, bw = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(bw) > 127:
        bw = 255 - bw
    h, w = bw.shape
    if np.mean(bw) / 255 < 0.03:
        return None

    def on(y0: float, y1: float, x0: float, x1: float, thresh: float = 0.32) -> int:
        patch = bw[
            int(h * y0) : max(int(h * y1), int(h * y0) + 1),
            int(w * x0) : max(int(w * x1), int(w * x0) + 1),
        ]
        if patch.size == 0:
            return 0
        return int(np.mean(patch) / 255 > thresh)

    if w / h < 0.42 and on(0.12, 0.48, 0.40, 0.98, 0.22) and on(0.52, 0.88, 0.40, 0.98, 0.22):
        return "1"

    pattern = (
        on(0.03, 0.18, 0.20, 0.80),
        on(0.12, 0.48, 0.68, 0.98),
        on(0.52, 0.88, 0.68, 0.98),
        on(0.82, 0.97, 0.20, 0.80),
        on(0.52, 0.88, 0.02, 0.32),
        on(0.12, 0.48, 0.02, 0.32),
        on(0.42, 0.58, 0.20, 0.80),
    )
    return _match_segments(pattern)


def _match_segments(pattern: tuple[int, ...]) -> str | None:
    exact = SEGMENTS.get(pattern)
    if exact:
        return exact
    best: str | None = None
    best_dist = 3
    for key, value in SEGMENTS.items():
        dist = sum(int(a != b) for a, b in zip(pattern, key))
        if dist < best_dist:
            best_dist = dist
            best = value
    return best if best_dist <= 2 else None


def _ssocr_text(bgr: np.ndarray) -> str:
    if not shutil.which("ssocr"):
        return ""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "lcd.png"
        cv2.imwrite(str(path), gray)
        try:
            result = subprocess.run(
                [
                    "ssocr",
                    "-d",
                    "-1",
                    "-t",
                    "20",
                    "make_mono",
                    "invert",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
    return (result.stdout or "").strip()


def _tesseract_texts(bgr: np.ndarray) -> list[str]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    variants = _cv_variants(gray) + _pil_variants(bgr)
    texts: list[str] = []
    for variant in variants:
        for cfg in TESS_CFGS:
            try:
                text = pytesseract.image_to_string(variant, config=cfg)
            except pytesseract.TesseractError:
                continue
            except pytesseract.TesseractNotFoundError:
                return texts
            if text and text.strip():
                texts.append(text)
    return texts


def _cv_variants(gray: np.ndarray) -> list[np.ndarray]:
    scaled = cv2.resize(gray, None, fx=2.4, fy=2.4, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8)).apply(scaled)
    blur = cv2.GaussianBlur(clahe, (3, 3), 0)
    _, otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 5
    )
    return [clahe, otsu, 255 - otsu, adaptive, 255 - adaptive]


def _pil_variants(bgr: np.ndarray) -> list[Image.Image]:
    image = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    gray = ImageOps.autocontrast(ImageOps.grayscale(image))
    sharp = ImageEnhance.Contrast(gray.filter(ImageFilter.SHARPEN)).enhance(2.8)
    inverted = ImageOps.invert(sharp)
    binary = sharp.point(lambda px: 255 if px > 120 else 0)
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
    useful = [n for n in numbers if 30 <= n <= 250]
    for index in range(len(useful) - 2):
        parsed = parse_bp(f"{useful[index]}/{useful[index + 1]} {useful[index + 2]}")
        if parsed:
            return parsed
    return _best_triple(useful)


def _best_triple(numbers: list[int]) -> tuple[int, int, int] | None:
    useful = [n for n in numbers if 30 <= n <= 250]
    seen: set[tuple[int, int, int]] = set()
    for trio in combinations(useful, 3):
        for sys, dia, pulse in (
            trio,
            (trio[0], trio[2], trio[1]),
            (trio[1], trio[0], trio[2]),
        ):
            parsed = parse_bp(f"{sys}/{dia} {pulse}")
            if parsed and parsed not in seen:
                seen.add(parsed)
                return parsed
    return None
