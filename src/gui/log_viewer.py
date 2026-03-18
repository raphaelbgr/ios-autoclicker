"""
Log viewer widget for real-time display of application logs.
Color-coded entries with auto-scroll and export functionality.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit,
    QPushButton, QFileDialog, QLabel
)
from PyQt6.QtCore import Qt, pyqtSlot, pyqtSignal, QObject
from PyQt6.QtGui import QTextCharFormat, QColor, QFont

from src.logger import AppLogger, LogEntry, LogCategory
from src.gui.styles import COLORS


# Color map for log categories
CATEGORY_COLORS = {
    LogCategory.SCREEN_MATCH: COLORS["success"],
    LogCategory.SCREEN_MISMATCH: COLORS["error"],
    LogCategory.CLICK_EXECUTED: "#6c9eff",
    LogCategory.TIMELINE_START: COLORS["success"],
    LogCategory.TIMELINE_STOP: COLORS["warning"],
    LogCategory.STATE_CHANGE: "#c084fc",
    LogCategory.ERROR: COLORS["error"],
    LogCategory.WARNING: COLORS["warning"],
    LogCategory.INFO: COLORS["text_secondary"],
}


class LogSignalBridge(QObject):
    """Bridge to safely emit log entries from non-GUI threads."""
    new_entry = pyqtSignal(object)


class LogViewer(QWidget):
    """Real-time log viewer with color-coded entries."""

    def __init__(self, logger: AppLogger, parent=None):
        super().__init__(parent)
        self._logger = logger
        self._auto_scroll = True
        self._signal_bridge = LogSignalBridge()
        self._signal_bridge.new_entry.connect(self._on_new_entry)

        self._setup_ui()

        # Register listener
        self._logger.add_listener(self._on_log_entry)

        # Load existing entries
        for entry in self._logger.get_entries():
            self._append_entry(entry)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("📋 Activity Log")
        title.setObjectName("header")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Buttons
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedWidth(70)
        self._clear_btn.clicked.connect(self._clear_log)
        header_layout.addWidget(self._clear_btn)

        self._export_btn = QPushButton("Export")
        self._export_btn.setFixedWidth(70)
        self._export_btn.clicked.connect(self._export_log)
        header_layout.addWidget(self._export_btn)

        layout.addLayout(header_layout)

        # Log text area
        self._text_edit = QTextEdit()
        self._text_edit.setReadOnly(True)
        self._text_edit.setFont(QFont("Menlo", 11))
        layout.addWidget(self._text_edit)

        # Entry count
        self._count_label = QLabel("0 entries")
        self._count_label.setObjectName("subheader")
        layout.addWidget(self._count_label)

    def _on_log_entry(self, entry: LogEntry):
        """Called from any thread — bridges to GUI thread."""
        self._signal_bridge.new_entry.emit(entry)

    @pyqtSlot(object)
    def _on_new_entry(self, entry: LogEntry):
        """Handle new log entry in the GUI thread."""
        self._append_entry(entry)

    def _append_entry(self, entry: LogEntry):
        """Append a formatted log entry to the text area."""
        color = CATEGORY_COLORS.get(entry.category, COLORS["text_primary"])

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))

        cursor = self._text_edit.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(entry.format() + "\n", fmt)

        count = len(self._logger.get_entries())
        self._count_label.setText(f"{count} entries")

        if self._auto_scroll:
            scrollbar = self._text_edit.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _clear_log(self):
        self._text_edit.clear()
        self._logger.clear()
        self._count_label.setText("0 entries")

    def _export_log(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Log", "autoclicker_log.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        if filepath:
            self._logger.export(filepath)
