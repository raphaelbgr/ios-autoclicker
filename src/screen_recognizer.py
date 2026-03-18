"""
Screen recognition module.
Compares current window captures against reference screenshots using SSIM and template matching.
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Optional, Tuple
from skimage.metrics import structural_similarity as ssim


@dataclass
class MatchResult:
    """Result of a screen comparison."""
    is_match: bool
    similarity: float  # 0.0 to 1.0
    method: str  # "ssim" or "template"
    threshold: float

    @property
    def similarity_percent(self) -> float:
        return self.similarity * 100.0


class ScreenRecognizer:
    """Compares screen captures against reference images."""

    def __init__(self, threshold: float = 0.85):
        """
        Args:
            threshold: Similarity threshold (0.0-1.0). Default 0.85 (85%).
        """
        self._threshold = threshold
        self._reference_image: Optional[np.ndarray] = None
        self._reference_gray: Optional[np.ndarray] = None

    @property
    def threshold(self) -> float:
        return self._threshold

    @threshold.setter
    def threshold(self, value: float):
        self._threshold = max(0.0, min(1.0, value))

    @property
    def has_reference(self) -> bool:
        return self._reference_image is not None

    @property
    def reference_image(self) -> Optional[np.ndarray]:
        return self._reference_image

    def set_reference(self, image: np.ndarray):
        """Set the reference image to compare against."""
        self._reference_image = image.copy()
        self._reference_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def load_reference(self, filepath: str) -> bool:
        """Load a reference image from file."""
        try:
            img = cv2.imread(filepath)
            if img is None:
                return False
            self.set_reference(img)
            return True
        except Exception:
            return False

    def save_reference(self, filepath: str) -> bool:
        """Save the current reference image to file."""
        if self._reference_image is None:
            return False
        try:
            cv2.imwrite(filepath, self._reference_image)
            return True
        except Exception:
            return False

    def compare(self, current_image: np.ndarray) -> MatchResult:
        """
        Compare current screen capture against the reference image.
        Uses SSIM (Structural Similarity Index) as the primary method.
        """
        if self._reference_image is None or self._reference_gray is None:
            return MatchResult(
                is_match=False,
                similarity=0.0,
                method="none",
                threshold=self._threshold,
            )

        try:
            # Resize current image to match reference if sizes differ
            current_resized = self._resize_to_match(current_image, self._reference_image)
            current_gray = cv2.cvtColor(current_resized, cv2.COLOR_BGR2GRAY)

            # Compute SSIM
            similarity_score, _ = ssim(
                self._reference_gray,
                current_gray,
                full=True,
            )

            return MatchResult(
                is_match=bool(similarity_score >= self._threshold),
                similarity=float(similarity_score),
                method="ssim",
                threshold=float(self._threshold),
            )
        except Exception as e:
            return MatchResult(
                is_match=False,
                similarity=0.0,
                method=f"error: {e}",
                threshold=self._threshold,
            )

    def compare_template(self, current_image: np.ndarray,
                         template: Optional[np.ndarray] = None) -> MatchResult:
        """
        Alternative comparison using OpenCV template matching.
        Useful for detecting a specific sub-region of the screen.
        """
        if template is None:
            template = self._reference_image
        if template is None:
            return MatchResult(
                is_match=False, similarity=0.0,
                method="template", threshold=self._threshold,
            )

        try:
            current_gray = cv2.cvtColor(current_image, cv2.COLOR_BGR2GRAY)
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

            # Ensure template is not larger than the image
            if (template_gray.shape[0] > current_gray.shape[0] or
                    template_gray.shape[1] > current_gray.shape[1]):
                # Resize template to fit
                template_gray = cv2.resize(
                    template_gray,
                    (current_gray.shape[1], current_gray.shape[0])
                )

            result = cv2.matchTemplate(
                current_gray, template_gray, cv2.TM_CCOEFF_NORMED
            )
            _, max_val, _, _ = cv2.minMaxLoc(result)

            return MatchResult(
                is_match=bool(max_val >= self._threshold),
                similarity=float(max_val),
                method="template",
                threshold=float(self._threshold),
            )
        except Exception as e:
            return MatchResult(
                is_match=False, similarity=0.0,
                method=f"template_error: {e}", threshold=self._threshold,
            )

    @staticmethod
    def _resize_to_match(image: np.ndarray, target: np.ndarray) -> np.ndarray:
        """Resize image to match target dimensions."""
        if image.shape[:2] == target.shape[:2]:
            return image
        return cv2.resize(image, (target.shape[1], target.shape[0]),
                          interpolation=cv2.INTER_AREA)
