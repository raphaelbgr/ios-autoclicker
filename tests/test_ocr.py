"""Tests for src/ocr.py — real macOS Vision framework OCR on rendered text."""

import numpy as np
import cv2
import pytest

from src.ocr import recognize_text, text_matches_any


def render_text_image(text: str, size=(140, 640)) -> np.ndarray:
    """White canvas with large black text — trivially OCR-able."""
    img = np.full((size[0], size[1], 3), 255, dtype=np.uint8)
    cv2.putText(img, text, (20, size[0] - 45),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 5, cv2.LINE_AA)
    return img


@pytest.fixture(scope="module")
def hello_image():
    return render_text_image("HELLO WORLD")


class TestRecognizeText:
    def test_reads_rendered_text(self, hello_image):
        texts = recognize_text(hello_image)
        if not texts:
            pytest.skip("Vision returned nothing — OCR unavailable in this env")
        joined = " ".join(texts).upper()
        assert "HELLO" in joined
        assert "WORLD" in joined

    def test_blank_image_returns_empty_or_no_crash(self):
        blank = np.full((100, 200, 3), 255, dtype=np.uint8)
        texts = recognize_text(blank)
        assert isinstance(texts, list)


class TestTextMatchesAny:
    def test_matches_case_insensitive(self, hello_image):
        matched, pattern, all_texts = text_matches_any(
            hello_image, ["nope", "hello"])
        if not all_texts:
            pytest.skip("Vision returned nothing — OCR unavailable in this env")
        assert matched is True
        assert pattern == "hello"

    def test_or_logic_first_hit_wins(self, hello_image):
        matched, pattern, _ = text_matches_any(
            hello_image, ["world", "hello"])
        assert matched is True
        assert pattern == "world"  # first pattern in list that is present

    def test_no_match(self, hello_image):
        matched, pattern, all_texts = text_matches_any(
            hello_image, ["xyzzy-not-there"])
        assert matched is False
        assert pattern is None

    def test_empty_patterns(self, hello_image):
        assert text_matches_any(hello_image, []) == (False, None, [])

    def test_whitespace_patterns_ignored(self, hello_image):
        matched, pattern, all_texts = text_matches_any(hello_image, ["   "])
        assert matched is False
