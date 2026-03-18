"""
OCR module using macOS Vision framework.
Recognizes text from images without any external dependencies.
"""

import numpy as np
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def recognize_text(image: np.ndarray) -> List[str]:
    """
    Run OCR on a numpy image (BGR from OpenCV) using macOS Vision framework.

    Returns a list of recognized text strings (one per detected text block).
    """
    try:
        import cv2
        import objc
        from Foundation import NSData
        import Vision
    except Exception as e:
        logger.error(f"OCR import error: {e}")
        return []

    try:
        # Encode image as JPEG bytes
        _, jpeg_bytes = cv2.imencode('.jpg', image)
        ns_data = NSData.dataWithBytes_length_(
            jpeg_bytes.tobytes(), len(jpeg_bytes)
        )

        # Create image request handler from data
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(
            ns_data, None
        )

        # Create text recognition request
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(
            Vision.VNRequestTextRecognitionLevelAccurate
        )
        request.setUsesLanguageCorrection_(True)

        # Perform the request — PyObjC returns (success, error) tuple
        result = handler.performRequests_error_([request], None)

        # Handle different PyObjC return formats
        if isinstance(result, tuple):
            success = result[0]
            error = result[1] if len(result) > 1 else None
        else:
            success = bool(result)
            error = None

        if not success:
            logger.error(f"Vision OCR failed: {error}")
            return []

        # Extract recognized text from results
        observations = request.results()
        if not observations:
            return []

        texts = []
        for observation in observations:
            candidates = observation.topCandidates_(1)
            if candidates and len(candidates) > 0:
                text = str(candidates[0].string())
                if text.strip():
                    texts.append(text.strip())

        return texts

    except Exception as e:
        logger.error(f"OCR error: {e}")
        return []


def text_matches_any(
    image: np.ndarray, patterns: List[str]
) -> Tuple[bool, Optional[str], List[str]]:
    """
    Check if any of the given text patterns appear on screen.

    Args:
        image: BGR numpy array (from OpenCV)
        patterns: list of text strings to look for (case-insensitive, OR logic)

    Returns:
        (matched: bool, matched_pattern: str or None, all_recognized_texts: list)
    """
    if not patterns:
        return False, None, []

    recognized = recognize_text(image)
    if not recognized:
        return False, None, []

    # Join all recognized text into one string for substring matching
    all_text_lower = " ".join(recognized).lower()

    for pattern in patterns:
        pattern_clean = pattern.strip().lower()
        if pattern_clean and pattern_clean in all_text_lower:
            return True, pattern.strip(), recognized

    return False, None, recognized
