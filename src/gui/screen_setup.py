"""
Screen setup panel.
Allows capturing/uploading reference screenshots and configuring similarity threshold.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QFileDialog, QGroupBox, QProgressBar, QSizePolicy,
    QScrollArea, QCheckBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

import cv2
import numpy as np

from src.screen_capture import ScreenCapture
from src.screen_recognizer import ScreenRecognizer
from src.gui.click_position_picker import ClickPositionPicker
from src.gui.styles import COLORS


class ScreenSetup(QWidget):
    """Panel for setting up screen recognition."""

    reference_updated = pyqtSignal()  # Emitted when reference image changes
    threshold_changed = pyqtSignal(float)

    def __init__(self, screen_capture: ScreenCapture,
                 recognizer: ScreenRecognizer, parent=None):
        super().__init__(parent)
        self._capture = screen_capture
        self._recognizer = recognizer

        self._setup_ui()

    def _setup_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(12)

        # ── Window Detection ──
        window_group = QGroupBox("Window Detection")
        window_layout = QVBoxLayout(window_group)

        self._window_status = QLabel("No window detected")
        self._window_status.setObjectName("statusLabel")
        window_layout.addWidget(self._window_status)

        detect_btn = QPushButton("🔍 Detect iPhone Mirroring Window")
        detect_btn.clicked.connect(self._detect_window)
        window_layout.addWidget(detect_btn)

        layout.addWidget(window_group)

        # ── Reference Screenshot ──
        ref_group = QGroupBox("Reference Screenshot")
        ref_layout = QVBoxLayout(ref_group)

        btn_layout = QHBoxLayout()

        self._capture_btn = QPushButton("📸 Capture Current Screen")
        self._capture_btn.clicked.connect(self._capture_screen)
        btn_layout.addWidget(self._capture_btn)

        self._upload_btn = QPushButton("📁 Upload from File")
        self._upload_btn.clicked.connect(self._upload_screenshot)
        btn_layout.addWidget(self._upload_btn)

        self._save_btn = QPushButton("💾 Save Reference")
        self._save_btn.clicked.connect(self._save_reference)
        self._save_btn.setEnabled(False)
        btn_layout.addWidget(self._save_btn)

        ref_layout.addLayout(btn_layout)

        # Image preview — give it a strong minimum and expanding policy
        self._preview = ClickPositionPicker()
        self._preview.setMinimumHeight(350)
        self._preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        ref_layout.addWidget(self._preview, 1)  # stretch factor 1

        layout.addWidget(ref_group, 1)  # stretch factor so it gets most space

        # ── Similarity Threshold ──
        threshold_group = QGroupBox("Similarity Threshold")
        threshold_layout = QVBoxLayout(threshold_group)

        slider_layout = QHBoxLayout()
        self._threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self._threshold_slider.setRange(0, 100)
        self._threshold_slider.setValue(85)
        self._threshold_slider.setTickInterval(5)
        self._threshold_slider.valueChanged.connect(self._on_threshold_changed)
        slider_layout.addWidget(self._threshold_slider)

        self._threshold_label = QLabel("85%")
        self._threshold_label.setFixedWidth(50)
        self._threshold_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        slider_layout.addWidget(self._threshold_label)

        threshold_layout.addLayout(slider_layout)

        desc = QLabel(
            "How closely the screen must match the reference. "
            "Higher = stricter matching. Recommended: 75-90%"
        )
        desc.setObjectName("subheader")
        desc.setWordWrap(True)
        threshold_layout.addWidget(desc)

        # Live match indicator
        match_layout = QHBoxLayout()
        match_layout.addWidget(QLabel("Current Match:"))
        self._match_bar = QProgressBar()
        self._match_bar.setRange(0, 100)
        self._match_bar.setValue(0)
        self._match_bar.setFormat("%v%")
        match_layout.addWidget(self._match_bar)

        self._match_status = QLabel("—")
        self._match_status.setFixedWidth(100)
        match_layout.addWidget(self._match_status)

        threshold_layout.addLayout(match_layout)

        # Test / Live preview buttons
        test_layout = QHBoxLayout()

        self._test_btn = QPushButton("🔄 Test Match Now")
        self._test_btn.clicked.connect(self._test_match)
        test_layout.addWidget(self._test_btn)

        self._live_check = QCheckBox("Live preview")
        self._live_check.setToolTip("Continuously compare screen against reference")
        self._live_check.toggled.connect(self._toggle_live_preview)
        test_layout.addWidget(self._live_check)

        test_layout.addStretch()
        threshold_layout.addLayout(test_layout)

        layout.addWidget(threshold_group)

        # Timer for live preview
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._test_match)

        scroll.setWidget(container)
        outer_layout.addWidget(scroll)

    def _detect_window(self):
        window = self._capture.find_iphone_mirroring_window()
        if window:
            self._window_status.setText(
                f"✅ Found: {window.owner_name} — "
                f"{window.width}×{window.height} at ({window.x}, {window.y})"
            )
            self._window_status.setStyleSheet(
                f"color: {COLORS['success']}; "
                f"background-color: {COLORS['bg_card']}; "
                f"border: 1px solid {COLORS['success']};"
            )
        else:
            self._window_status.setText(
                "❌ iPhone Mirroring window not found. "
                "Make sure it's open and visible."
            )
            self._window_status.setStyleSheet(
                f"color: {COLORS['error']}; "
                f"background-color: {COLORS['bg_card']}; "
                f"border: 1px solid {COLORS['error']};"
            )

    def _capture_screen(self):
        image = self._capture.capture_iphone_mirroring()
        if image is not None:
            self._recognizer.set_reference(image)
            self._preview.set_image(image)
            self._save_btn.setEnabled(True)
            self.reference_updated.emit()
        else:
            self._window_status.setText(
                "❌ Could not capture screen. Detect the window first."
            )

    def _upload_screenshot(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Upload Reference Screenshot", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if filepath:
            if self._recognizer.load_reference(filepath):
                self._preview.set_image(self._recognizer.reference_image)
                self._save_btn.setEnabled(True)
                self.reference_updated.emit()

    def _save_reference(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Save Reference Screenshot", "reference.png",
            "PNG Images (*.png);;All Files (*)"
        )
        if filepath:
            self._recognizer.save_reference(filepath)

    def _on_threshold_changed(self, value: int):
        self._threshold_label.setText(f"{value}%")
        self._recognizer.threshold = value / 100.0
        self.threshold_changed.emit(value / 100.0)

    def _test_match(self):
        """Do a one-shot screen capture and compare against reference."""
        if not self._recognizer.has_reference:
            self._match_status.setText("No ref")
            self._match_status.setStyleSheet(f"color: {COLORS['warning']};")
            return

        image = self._capture.capture_iphone_mirroring()
        if image is None:
            self._match_status.setText("No window")
            self._match_status.setStyleSheet(f"color: {COLORS['warning']};")
            return

        result = self._recognizer.compare(image)
        self.update_match_display(result.similarity, result.is_match)

    def _toggle_live_preview(self, enabled: bool):
        """Start/stop the live preview timer."""
        if enabled:
            self._live_timer.start(1000)  # Check every 1 second
        else:
            self._live_timer.stop()

    def update_match_display(self, similarity: float, is_match: bool):
        """Update the live match indicator."""
        percent = int(similarity * 100)
        self._match_bar.setValue(percent)

        if is_match:
            self._match_status.setText("✅ MATCH")
            self._match_status.setStyleSheet(f"color: {COLORS['success']};")
            self._match_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {COLORS['success']}; border-radius: 5px; }}"
            )
        else:
            self._match_status.setText("❌ NO MATCH")
            self._match_status.setStyleSheet(f"color: {COLORS['error']};")
            self._match_bar.setStyleSheet(
                f"QProgressBar::chunk {{ background-color: {COLORS['error']}; border-radius: 5px; }}"
            )

    def get_picker(self) -> ClickPositionPicker:
        """Return the click position picker for external use."""
        return self._preview
