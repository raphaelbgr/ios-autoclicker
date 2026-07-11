"""Tests for src/screen_recognizer.py — SSIM + template matching on synthetic images."""

import numpy as np
import cv2
import pytest

from src.screen_recognizer import ScreenRecognizer, MatchResult


def make_screen(seed: int = 0, size: int = 96) -> np.ndarray:
    """Deterministic structured BGR test image (gradient + rectangles)."""
    rng = np.random.default_rng(seed)
    img = np.zeros((size, size, 3), dtype=np.uint8)
    # gradient background
    for i in range(size):
        img[i, :, :] = (i * 255 // size, 128, 255 - i * 255 // size)
    # random rectangles = "UI elements"
    for _ in range(6):
        x, y = rng.integers(0, size - 20, 2)
        w, h = rng.integers(8, 20, 2)
        color = tuple(int(c) for c in rng.integers(0, 255, 3))
        cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), color, -1)
    return img


class TestCompare:
    def test_identical_images_match(self):
        r = ScreenRecognizer(threshold=0.85)
        img = make_screen(1)
        r.set_reference(img)
        res = r.compare(img)
        assert res.method == "ssim"
        assert res.similarity > 0.99
        assert res.is_match is True
        assert res.similarity_percent == pytest.approx(res.similarity * 100)

    def test_different_images_no_match(self):
        r = ScreenRecognizer(threshold=0.85)
        r.set_reference(make_screen(1))
        noise = np.random.default_rng(9).integers(
            0, 255, make_screen(1).shape, dtype=np.uint8)
        res = r.compare(noise.astype(np.uint8))
        assert res.similarity < 0.5
        assert res.is_match is False

    def test_slightly_modified_image_scores_between(self):
        r = ScreenRecognizer(threshold=0.99)
        img = make_screen(2)
        r.set_reference(img)
        mod = img.copy()
        cv2.rectangle(mod, (10, 10), (40, 40), (0, 0, 0), -1)  # small change
        res = r.compare(mod)
        assert 0.5 < res.similarity < 0.999
        assert res.is_match is False  # 99% threshold

    def test_mismatched_sizes_are_resized(self):
        r = ScreenRecognizer(threshold=0.5)
        img = make_screen(3, size=96)
        r.set_reference(img)
        bigger = cv2.resize(img, (192, 192))
        res = r.compare(bigger)
        assert res.similarity > 0.7  # content identical modulo resample loss
        assert res.is_match is True

    def test_no_reference_returns_no_match(self):
        r = ScreenRecognizer()
        res = r.compare(make_screen(4))
        assert res.is_match is False
        assert res.similarity == 0.0
        assert res.method == "none"
        assert r.has_reference is False

    def test_threshold_clamped(self):
        r = ScreenRecognizer()
        r.threshold = 5.0
        assert r.threshold == 1.0
        r.threshold = -1.0
        assert r.threshold == 0.0

    def test_threshold_boundary_is_inclusive(self):
        r = ScreenRecognizer(threshold=1.0)
        img = make_screen(5)
        r.set_reference(img)
        res = r.compare(img)
        assert res.similarity == pytest.approx(1.0)
        assert res.is_match is True  # sim >= threshold


class TestReferenceIO:
    def test_save_and_load_reference(self, tmp_path):
        r = ScreenRecognizer()
        img = make_screen(6)
        r.set_reference(img)
        p = str(tmp_path / "ref.png")
        assert r.save_reference(p) is True

        r2 = ScreenRecognizer()
        assert r2.load_reference(p) is True
        assert r2.has_reference
        assert np.array_equal(r2.reference_image, img)

    def test_load_missing_file(self):
        r = ScreenRecognizer()
        assert r.load_reference("/nonexistent/nope.png") is False

    def test_save_without_reference(self, tmp_path):
        r = ScreenRecognizer()
        assert r.save_reference(str(tmp_path / "x.png")) is False

    def test_set_reference_copies(self):
        r = ScreenRecognizer()
        img = make_screen(7)
        r.set_reference(img)
        img[:] = 0  # mutate original
        assert r.reference_image.any()  # internal copy untouched


class TestTemplate:
    def test_template_identical(self):
        r = ScreenRecognizer(threshold=0.8)
        img = make_screen(8)
        r.set_reference(img)
        res = r.compare_template(img)
        assert res.method == "template"
        assert res.similarity > 0.99
        assert res.is_match

    def test_template_subregion_found(self):
        r = ScreenRecognizer(threshold=0.8)
        img = make_screen(9, size=128)
        sub = img[20:60, 30:90].copy()
        res = r.compare_template(img, template=sub)
        assert res.similarity > 0.95
        assert res.is_match

    def test_template_none(self):
        r = ScreenRecognizer()
        res = r.compare_template(make_screen(10))
        assert res.is_match is False
        assert res.method == "template"

    def test_template_larger_than_image_is_resized(self):
        r = ScreenRecognizer(threshold=0.5)
        img = make_screen(11, size=64)
        big = cv2.resize(img, (256, 256))
        res = r.compare_template(img, template=big)
        assert res.similarity > 0.5  # resized down and still similar
