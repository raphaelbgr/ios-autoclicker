"""
Logging module for the iOS Auto-Clicker.
Provides timestamped, categorized log entries for GUI display and file output.
"""

import logging
import os
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Callable


class LogCategory(Enum):
    SCREEN_MATCH = "MATCH"
    SCREEN_MISMATCH = "MISMATCH"
    CLICK_EXECUTED = "CLICK"
    TIMELINE_START = "TIMELINE_START"
    TIMELINE_STOP = "TIMELINE_STOP"
    STATE_CHANGE = "STATE"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class LogEntry:
    timestamp: datetime
    category: LogCategory
    message: str
    details: Optional[str] = None

    def format(self) -> str:
        ts = self.timestamp.strftime("%H:%M:%S.%f")[:-3]
        cat = self.category.value.ljust(14)
        line = f"[{ts}] [{cat}] {self.message}"
        if self.details:
            line += f" | {self.details}"
        return line


class AppLogger:
    """Central logger that stores entries in memory and optionally writes to file."""

    def __init__(self, log_dir: Optional[str] = None, max_entries: int = 5000):
        self._entries: List[LogEntry] = []
        self._max_entries = max_entries
        self._listeners: List[Callable[[LogEntry], None]] = []
        self._file_handler: Optional[logging.FileHandler] = None

        # Set up file logging if requested
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(
                log_dir,
                f"autoclicker_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
            )
            self._file_logger = logging.getLogger("autoclicker_file")
            self._file_logger.setLevel(logging.DEBUG)
            handler = logging.FileHandler(log_file, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._file_logger.addHandler(handler)
            self._file_handler = handler
        else:
            self._file_logger = None

    def add_listener(self, callback: Callable[[LogEntry], None]):
        """Register a callback that fires on every new log entry."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[LogEntry], None]):
        if callback in self._listeners:
            self._listeners.remove(callback)

    def log(self, category: LogCategory, message: str, details: Optional[str] = None):
        entry = LogEntry(
            timestamp=datetime.now(),
            category=category,
            message=message,
            details=details,
        )
        self._entries.append(entry)

        # Trim if over limit
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

        # Write to file
        if self._file_logger:
            self._file_logger.info(entry.format())

        # Notify listeners
        for listener in self._listeners:
            try:
                listener(entry)
            except Exception:
                pass  # Don't let listener errors break logging

    def get_entries(self, count: Optional[int] = None) -> List[LogEntry]:
        if count is None:
            return list(self._entries)
        return list(self._entries[-count:])

    def clear(self):
        self._entries.clear()

    def export(self, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(entry.format() + "\n")

    # Convenience methods
    def info(self, message: str, details: Optional[str] = None):
        self.log(LogCategory.INFO, message, details)

    def warning(self, message: str, details: Optional[str] = None):
        self.log(LogCategory.WARNING, message, details)

    def error(self, message: str, details: Optional[str] = None):
        self.log(LogCategory.ERROR, message, details)

    def match(self, message: str, details: Optional[str] = None):
        self.log(LogCategory.SCREEN_MATCH, message, details)

    def mismatch(self, message: str, details: Optional[str] = None):
        self.log(LogCategory.SCREEN_MISMATCH, message, details)

    def click(self, message: str, details: Optional[str] = None):
        self.log(LogCategory.CLICK_EXECUTED, message, details)
