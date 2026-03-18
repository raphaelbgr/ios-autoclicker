"""
Click position picker widget.
Shows a screenshot where the user can click to select target coordinates.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QSize
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QImage, QMouseEvent

import numpy as np
import cv2


class ClickPositionPicker(QWidget):
    """
    Displays an image and lets the user click to pick coordinates.
    Emits position_selected(x, y) with coordinates relative to the original image.
    """

    position_selected = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._original_image: QPixmap | None = None
        self._display_pixmap: QPixmap | None = None
        self._markers: list[tuple[int, int, str]] = []  # (x, y, label)
        self._selected_point: QPoint | None = None
        self._scale_x = 1.0
        self._scale_y = 1.0

        self.setMinimumSize(200, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_image(self, image: np.ndarray):
        """Set the image from a numpy array (BGR format from OpenCV)."""
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        self._original_image = QPixmap.fromImage(qimg.copy())
        self._update_display()

    def set_pixmap(self, pixmap: QPixmap):
        """Set the image directly from a QPixmap."""
        self._original_image = pixmap
        self._update_display()

    def clear_image(self):
        self._original_image = None
        self._display_pixmap = None
        self._markers.clear()
        self._selected_point = None
        self.update()

    def add_marker(self, x: int, y: int, label: str = ""):
        """Add a persistent marker at the given image coordinates."""
        self._markers.append((x, y, label))
        self.update()

    def clear_markers(self):
        self._markers.clear()
        self.update()

    def _update_display(self):
        if self._original_image is None or self._original_image.isNull():
            self._display_pixmap = None
            return
        # Scale to fit widget while maintaining aspect ratio
        widget_size = self.size()
        if widget_size.width() < 1 or widget_size.height() < 1:
            return
        self._display_pixmap = self._original_image.scaled(
            widget_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        if (self._display_pixmap and
                self._display_pixmap.width() > 0 and
                self._display_pixmap.height() > 0):
            self._scale_x = self._original_image.width() / self._display_pixmap.width()
            self._scale_y = self._original_image.height() / self._display_pixmap.height()
        else:
            self._scale_x = 1.0
            self._scale_y = 1.0
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()

    def mousePressEvent(self, event: QMouseEvent):
        if self._display_pixmap is None:
            return

        pos = event.position()
        # Calculate offset (image is centered)
        offset_x = (self.width() - self._display_pixmap.width()) / 2
        offset_y = (self.height() - self._display_pixmap.height()) / 2

        # Check if click is within the image
        local_x = pos.x() - offset_x
        local_y = pos.y() - offset_y

        if (0 <= local_x <= self._display_pixmap.width() and
                0 <= local_y <= self._display_pixmap.height()):
            # Convert to original image coordinates
            img_x = int(local_x * self._scale_x)
            img_y = int(local_y * self._scale_y)

            self._selected_point = QPoint(int(local_x), int(local_y))
            self.update()
            self.position_selected.emit(img_x, img_y)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            if self._display_pixmap is None or self._display_pixmap.isNull():
                # Draw placeholder
                painter.setPen(QPen(QColor("#636e7f"), 2, Qt.PenStyle.DashLine))
                painter.drawRect(10, 10, self.width() - 20, self.height() - 20)
                painter.setPen(QColor("#636e7f"))
                painter.drawText(
                    self.rect(), Qt.AlignmentFlag.AlignCenter,
                    "No screenshot loaded\nCapture or upload a reference image"
                )
                return

            # Draw the image centered
            offset_x = (self.width() - self._display_pixmap.width()) // 2
            offset_y = (self.height() - self._display_pixmap.height()) // 2
            painter.drawPixmap(offset_x, offset_y, self._display_pixmap)

            # Guard: skip markers/points if scale is zero
            if self._scale_x <= 0 or self._scale_y <= 0:
                return

            # Draw markers
            for mx, my, label in self._markers:
                # Convert image coords to display coords
                dx = int(mx / self._scale_x) + offset_x
                dy = int(my / self._scale_y) + offset_y

                # Crosshair
                pen = QPen(QColor("#e94560"), 2)
                painter.setPen(pen)
                size = 10
                painter.drawLine(dx - size, dy, dx + size, dy)
                painter.drawLine(dx, dy - size, dx, dy + size)

                # Circle
                painter.drawEllipse(QPoint(dx, dy), 6, 6)

                # Label
                if label:
                    painter.setPen(QColor("#eaf0fb"))
                    painter.drawText(dx + 10, dy - 5, label)

            # Draw selected point
            if self._selected_point:
                dx = self._selected_point.x() + offset_x
                dy = self._selected_point.y() + offset_y
                pen = QPen(QColor("#00d2d3"), 2)
                painter.setPen(pen)
                size = 14
                painter.drawLine(dx - size, dy, dx + size, dy)
                painter.drawLine(dx, dy - size, dx, dy + size)
                painter.drawEllipse(QPoint(dx, dy), 8, 8)

        except Exception:
            pass  # Never let a paint exception crash the app
        finally:
            painter.end()
