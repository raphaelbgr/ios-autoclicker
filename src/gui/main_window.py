"""
Main application window — single unified view.
No tabs: screenshot preview, timeline, threshold, and logs are all visible at once.
Everything auto-saves to the project folder so no data is ever lost.
"""

import time
import threading
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSplitter, QFrame,
    QMessageBox, QSpinBox, QSlider, QFileDialog,
    QGroupBox, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QCheckBox, QLineEdit, QTextEdit, QComboBox,
    QSizePolicy, QScrollArea
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QFont, QTextCharFormat, QColor

from src.screen_capture import ScreenCapture
from src.screen_recognizer import ScreenRecognizer
from src.click_engine import ClickEngine
from src.timeline import Timeline, TimelineExecutor, ClickAction
from src.click_engine import ClickType
from src.logger import AppLogger, LogCategory
from src.project import Project, ProjectSettings
from src.gui.click_position_picker import ClickPositionPicker
from src.gui.styles import STYLESHEET, COLORS


# ── Color map for log categories ──
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


class SignalBridge(QObject):
    """Thread-safe signal bridge for updating GUI from automation thread."""
    match_update = pyqtSignal(list, int)
    status_update = pyqtSignal(str)
    automation_stopped = pyqtSignal()
    new_log = pyqtSignal(object)
    highlight_action = pyqtSignal(int)    # index of currently watching action
    action_triggered = pyqtSignal(int, str)  # index, match_reason — after click executed
    bring_to_front = pyqtSignal()  # must be on main thread (AppKit requirement)


class MainWindow(QMainWindow):
    """Main application window — single unified view, auto-persistence."""

    def __init__(self):
        super().__init__()

        # ── Project & persistence ──
        self._project = Project("default")
        self._settings = self._project.load_settings()

        # ── Core components ──
        self._logger = AppLogger(log_dir="logs")
        self._screen_capture = ScreenCapture()
        self._recognizer = ScreenRecognizer(threshold=self._settings.threshold)
        self._click_engine = ClickEngine(self._screen_capture)

        # Load or create timeline
        saved_timeline = self._project.load_timeline()
        self._timeline = saved_timeline if saved_timeline else Timeline("My Timeline")

        self._timeline_executor = TimelineExecutor()

        # ── Automation state ──
        self._is_running = False
        self._automation_thread = None
        self._stop_event = threading.Event()
        self._window_lock = threading.Lock()   # guards _cached_window hot-swap
        self._signal_bridge = SignalBridge()
        self._signal_bridge.match_update.connect(self._on_match_update)
        self._signal_bridge.status_update.connect(self._on_status_update)
        self._signal_bridge.automation_stopped.connect(self._on_automation_stopped)
        self._signal_bridge.new_log.connect(self._on_new_log)
        self._signal_bridge.highlight_action.connect(self._on_highlight_action)
        self._signal_bridge.action_triggered.connect(self._on_action_triggered)
        self._signal_bridge.bring_to_front.connect(self._on_bring_to_front)
        self._bring_to_front_done = threading.Event()

        # ── Buttons to lock/unlock during automation ──
        self._edit_buttons = []

        # ── Button pulse animation state ──
        self._btn_pulse_timer = QTimer(self)
        self._btn_pulse_timer.setInterval(600)
        self._btn_pulse_timer.timeout.connect(self._pulse_buttons)
        self._btn_pulse_state = False

        # ── Last-triggered tracking ──
        self._last_triggered_index = -1
        self._last_triggered_time = 0.0  # time.time()
        self._last_triggered_reason = ""

        # ── Monitoring interval ──
        self._monitor_interval_ms = self._settings.monitor_interval_ms

        # ── Live preview timer ──
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._test_match)

        # ── Elapsed time update timer ──
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed_display)
        self._elapsed_timer.setInterval(1000)

        self._setup_window()
        self._setup_ui()
        self._refresh_project_combo()
        self._load_saved_data()
        self._check_permissions()

        self._logger.info("Application started", "iOS Auto-Clicker ready")
        
        # Populate window picker after data is loaded
        self._detect_window()

    def _setup_window(self):
        self.setWindowTitle("iOS Auto-Clicker")
        self.setMinimumSize(1000, 750)
        self.resize(1200, 900)
        self.setStyleSheet(STYLESHEET)

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(6)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ── Title Bar ──
        title_frame = QFrame()
        title_frame.setObjectName("card")
        title_layout = QHBoxLayout(title_frame)
        title_layout.setContentsMargins(12, 6, 12, 6)

        app_title = QLabel("🎯 iOS Auto-Clicker")
        app_title.setFont(QFont("Helvetica Neue", 18, QFont.Weight.Bold))
        app_title.setStyleSheet(f"color: {COLORS['accent']};")
        title_layout.addWidget(app_title)

        title_layout.addStretch()

        self._status_label = QLabel("⏸ Idle")
        self._status_label.setObjectName("statusLabel")
        title_layout.addWidget(self._status_label)

        main_layout.addWidget(title_frame)

        # ── Main Content: Left (screenshot) | Right (timeline + controls) ──
        content_splitter = QSplitter(Qt.Orientation.Horizontal)

        # ━━━ LEFT PANEL: Screenshot + Threshold ━━━
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(8)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Window detection wrapper
        detect_layout = QHBoxLayout()
        self._window_picker = QComboBox()
        self._window_picker.setObjectName("windowPicker")
        self._window_picker.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._window_picker.currentIndexChanged.connect(self._on_window_selected)
        detect_layout.addWidget(self._window_picker, 1)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setFixedWidth(80)
        refresh_btn.clicked.connect(self._detect_window)
        detect_layout.addWidget(refresh_btn)
        left_layout.addLayout(detect_layout)

        # Screenshot buttons
        shot_layout = QHBoxLayout()
        capture_btn = QPushButton("📸 Capture Screen")
        capture_btn.clicked.connect(self._capture_screen)
        shot_layout.addWidget(capture_btn)

        upload_btn = QPushButton("📁 Upload")
        upload_btn.clicked.connect(self._upload_screenshot)
        shot_layout.addWidget(upload_btn)
        left_layout.addLayout(shot_layout)

        # Selected action info label
        self._action_info_label = QLabel("📸 Reference Screenshot")
        self._action_info_label.setStyleSheet(
            f"color: {COLORS['accent']}; font-weight: 600; font-size: 13px; padding: 2px 4px;"
        )
        left_layout.addWidget(self._action_info_label)

        # Last triggered indicator
        self._last_triggered_label = QLabel("")
        self._last_triggered_label.setStyleSheet(
            f"color: {COLORS['success']}; font-size: 12px; padding: 2px 4px;"
        )
        self._last_triggered_label.setVisible(False)
        left_layout.addWidget(self._last_triggered_label)

        # Screenshot preview (main area)
        self._preview = ClickPositionPicker()
        self._preview.setMinimumHeight(300)
        self._preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._preview.position_selected.connect(self._on_preview_position_picked)
        left_layout.addWidget(self._preview, 1)

        # Threshold controls
        thresh_layout = QHBoxLayout()
        thresh_layout.addWidget(QLabel("Threshold:"))
        self._threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self._threshold_slider.setRange(0, 100)
        self._threshold_slider.setValue(int(self._settings.threshold * 100))
        self._threshold_slider.valueChanged.connect(self._on_threshold_changed)
        thresh_layout.addWidget(self._threshold_slider)

        self._threshold_label = QLabel(f"{int(self._settings.threshold * 100)}%")
        self._threshold_label.setFixedWidth(40)
        thresh_layout.addWidget(self._threshold_label)
        left_layout.addLayout(thresh_layout)

        # Match indicator
        match_layout = QHBoxLayout()
        match_layout.addWidget(QLabel("Match:"))
        self._match_bar = QProgressBar()
        self._match_bar.setRange(0, 100)
        self._match_bar.setValue(0)
        self._match_bar.setFormat("%v%")
        self._match_bar.setFixedHeight(20)
        match_layout.addWidget(self._match_bar)

        self._match_status = QLabel("—")
        self._match_status.setFixedWidth(90)
        match_layout.addWidget(self._match_status)

        test_btn = QPushButton("🔄 Test")
        test_btn.setFixedWidth(60)
        test_btn.clicked.connect(self._test_match)
        match_layout.addWidget(test_btn)

        self._live_check = QCheckBox("Live")
        self._live_check.toggled.connect(self._toggle_live)
        match_layout.addWidget(self._live_check)

        left_layout.addLayout(match_layout)

        content_splitter.addWidget(left_panel)

        # ━━━ RIGHT PANEL: Timeline table + controls ━━━
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(6)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # Timeline header
        tl_header = QHBoxLayout()
        tl_title = QLabel("⏱ Click Timeline")
        tl_title.setObjectName("header")
        tl_header.addWidget(tl_title)
        tl_header.addStretch()

        # Project selector + New (each project is its own clicks/triggers config)
        tl_header.addWidget(QLabel("Project:"))
        self._project_combo = QComboBox()
        self._project_combo.setFixedWidth(130)
        self._project_combo.currentTextChanged.connect(self._on_project_selected)
        tl_header.addWidget(self._project_combo)

        new_proj_btn = QPushButton("➕ New")
        new_proj_btn.setMinimumWidth(90)
        new_proj_btn.setToolTip("Create a new project (its own clicks, triggers, screenshots and settings)")
        new_proj_btn.clicked.connect(self._new_project)
        tl_header.addWidget(new_proj_btn)
        self._edit_buttons.append(new_proj_btn)

        tl_header.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit(self._timeline.name)
        self._name_edit.setFixedWidth(150)
        self._name_edit.textChanged.connect(self._on_name_changed)
        tl_header.addWidget(self._name_edit)
        right_layout.addLayout(tl_header)

        # Action buttons (tracked for lock/unlock during automation)
        btn_layout = QHBoxLayout()

        add_btn = QPushButton("➕ Add")
        add_btn.clicked.connect(self._add_action)
        btn_layout.addWidget(add_btn)
        self._edit_buttons.append(add_btn)

        edit_btn = QPushButton("✏️ Edit")
        edit_btn.clicked.connect(self._edit_action)
        btn_layout.addWidget(edit_btn)
        self._edit_buttons.append(edit_btn)

        remove_btn = QPushButton("🗑 Remove")
        remove_btn.clicked.connect(self._remove_action)
        btn_layout.addWidget(remove_btn)
        self._edit_buttons.append(remove_btn)

        up_btn = QPushButton("⬆ Up")
        up_btn.clicked.connect(self._move_up)
        up_btn.setFixedWidth(55)
        btn_layout.addWidget(up_btn)
        self._edit_buttons.append(up_btn)

        down_btn = QPushButton("⬇ Down")
        down_btn.clicked.connect(self._move_down)
        down_btn.setFixedWidth(65)
        btn_layout.addWidget(down_btn)
        self._edit_buttons.append(down_btn)

        clear_btn = QPushButton("🧹 Clear")
        clear_btn.clicked.connect(self._clear_actions)
        btn_layout.addWidget(clear_btn)
        self._edit_buttons.append(clear_btn)

        btn_layout.addStretch()

        import_btn = QPushButton("📥 Import")
        import_btn.clicked.connect(self._import_timeline)
        btn_layout.addWidget(import_btn)
        self._edit_buttons.append(import_btn)

        export_btn = QPushButton("📤 Export")
        export_btn.clicked.connect(self._export_timeline)
        btn_layout.addWidget(export_btn)

        right_layout.addLayout(btn_layout)

        # ── Click actions table (takes most space) ──
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels(
            ["On", "#", "Match%", "Current", "Delay", "X", "Y", "Type", "Label"]
        )

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(0, 32)
        self._table.setColumnWidth(1, 30)
        self._table.setColumnWidth(2, 55)
        self._table.setColumnWidth(3, 70)
        self._table.setColumnWidth(4, 65)
        self._table.setColumnWidth(5, 55)
        self._table.setColumnWidth(6, 55)
        self._table.setColumnWidth(7, 90)

        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._table.doubleClicked.connect(self._edit_action)
        self._table.itemSelectionChanged.connect(self._on_row_selected)
        self._table.itemChanged.connect(self._on_table_item_changed)
        right_layout.addWidget(self._table, 1)  # stretch factor = 1

        # Loop settings
        loop_layout = QHBoxLayout()
        self._loop_check = QCheckBox("Loop")
        self._loop_check.setChecked(self._timeline.loop)
        self._loop_check.toggled.connect(self._on_loop_changed)
        loop_layout.addWidget(self._loop_check)

        loop_layout.addWidget(QLabel("×"))
        self._loop_count_spin = QSpinBox()
        self._loop_count_spin.setRange(0, 99999)
        self._loop_count_spin.setValue(self._timeline.loop_count)
        self._loop_count_spin.setSpecialValueText("∞")
        self._loop_count_spin.setFixedWidth(80)
        self._loop_count_spin.valueChanged.connect(self._on_loop_count_changed)
        loop_layout.addWidget(self._loop_count_spin)

        loop_layout.addStretch()

        self._duration_label = QLabel("Duration: 0 ms")
        self._duration_label.setObjectName("subheader")
        loop_layout.addWidget(self._duration_label)

        right_layout.addLayout(loop_layout)

        content_splitter.addWidget(right_panel)
        content_splitter.setSizes([400, 550])

        # ── Bottom: Log + Controls ──
        bottom_splitter = QSplitter(Qt.Orientation.Vertical)
        bottom_splitter.addWidget(content_splitter)

        # Log viewer
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(4)

        log_header = QHBoxLayout()
        log_header.addWidget(QLabel("📋 Activity Log"))
        log_header.addStretch()

        clear_log_btn = QPushButton("Clear")
        clear_log_btn.setFixedWidth(75)
        clear_log_btn.clicked.connect(self._clear_log)
        log_header.addWidget(clear_log_btn)

        export_log_btn = QPushButton("Export")
        export_log_btn.setFixedWidth(75)
        export_log_btn.clicked.connect(self._export_log)
        log_header.addWidget(export_log_btn)

        log_layout.addLayout(log_header)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(150)
        self._log_text.setFont(QFont("Menlo", 11))
        log_layout.addWidget(self._log_text)

        bottom_splitter.addWidget(log_widget)
        bottom_splitter.setSizes([650, 150])

        main_layout.addWidget(bottom_splitter, 1)

        # ── Control Bar ──
        control_frame = QFrame()
        control_frame.setObjectName("card")
        control_layout = QHBoxLayout(control_frame)
        control_layout.setContentsMargins(12, 6, 12, 6)

        control_layout.addWidget(QLabel("Interval:"))
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(100, 5000)
        self._interval_spin.setSuffix(" ms")
        self._interval_spin.setValue(self._monitor_interval_ms)
        self._interval_spin.setFixedWidth(100)
        self._interval_spin.valueChanged.connect(self._on_interval_changed)
        control_layout.addWidget(self._interval_spin)

        self._bg_click_check = QCheckBox("Background Click")
        self._bg_click_check.setToolTip("Click without moving the mouse or focusing window")
        self._bg_click_check.setChecked(self._settings.background_click)
        self._bg_click_check.toggled.connect(self._on_bg_click_changed)
        control_layout.addWidget(self._bg_click_check)

        control_layout.addStretch()

        self._start_btn = QPushButton("▶  Start Automation")
        self._start_btn.setObjectName("startButton")
        self._start_btn.clicked.connect(self._start_automation)
        control_layout.addWidget(self._start_btn)

        self._stop_btn = QPushButton("⏹  Stop")
        self._stop_btn.setObjectName("stopButton")
        self._stop_btn.clicked.connect(self._stop_automation)
        self._stop_btn.setEnabled(False)
        control_layout.addWidget(self._stop_btn)

        main_layout.addWidget(control_frame)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Data Persistence
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _load_saved_data(self):
        """Load all saved project data on startup."""
        loaded_anything = False

        # Load reference screenshot
        ref = self._project.load_reference()
        if ref is not None:
            self._recognizer.set_reference(ref)
            self._preview.set_image(ref)
            self._logger.info("Loaded saved reference screenshot")
            loaded_anything = True

        # Timeline was already loaded in __init__
        if self._project.has_timeline():
            self._refresh_table()
            self._logger.info(
                f"Loaded saved timeline: {self._timeline.name}",
                f"{len(self._timeline.actions)} actions"
            )
            loaded_anything = True

        if loaded_anything:
            self._logger.info("Project data restored from disk")

    def _auto_save(self):
        """Save all current state to the project folder."""
        # Save timeline
        self._project.save_timeline(self._timeline)

        # Save reference if we have one
        if self._recognizer.has_reference and self._recognizer.reference_image is not None:
            self._project.save_reference(self._recognizer.reference_image)

        # Save settings
        self._settings.threshold = self._recognizer.threshold
        self._settings.monitor_interval_ms = self._monitor_interval_ms
        self._settings.background_click = self._bg_click_check.isChecked()
        self._project.save_settings(self._settings)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Window Detection & Screen Capture
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _detect_window(self):
        """Populates the combo box with available windows + Entire Screen."""
        import os
        own_pid = os.getpid()
        self._window_picker.blockSignals(True)
        self._window_picker.clear()
        self._window_picker.addItem("[Entire Screen]", "[Entire Screen]")

        windows = self._screen_capture.list_windows()
        windows.sort(key=lambda w: w.owner_name.lower())

        iphone_idx = -1
        for w in windows:
            if not w.owner_name:
                continue
            # Never offer the auto-clicker's own window as a target (avoids self-targeting)
            if w.owner_pid == own_pid:
                continue
            display_name = f"{w.owner_name} - {w.window_name}" if w.window_name else w.owner_name
            composite_key = f"{w.window_id}::{w.owner_name}::{w.window_name}"
            self._window_picker.addItem(display_name, composite_key)
            if iphone_idx < 0 and "iphone mirroring" in w.owner_name.lower():
                iphone_idx = self._window_picker.count() - 1

        # Restore previous selection — match by owner name part (IDs change across reboots)
        target = self._settings.target_app
        target_owner = target.split("::")[1] if "::" in target else target
        # Treat stale self-targets / no-target as invalid so we can auto-prefer iPhone Mirroring
        bogus = target_owner in ("Python", "iOS Auto-Clicker", "[Entire Screen]", "")
        selected_idx = 0  # default to Entire Screen

        if not bogus:
            for i in range(self._window_picker.count()):
                userData = self._window_picker.itemData(i)
                userOwner = userData.split("::")[1] if "::" in userData else userData
                if userOwner == target_owner:
                    selected_idx = i
                    break

        # Nothing valid restored → auto-select iPhone Mirroring if present, and persist it
        if selected_idx == 0 and iphone_idx >= 0:
            selected_idx = iphone_idx
            self._settings.target_app = self._window_picker.itemData(iphone_idx)
            self._project.save_settings(self._settings)

        self._window_picker.setCurrentIndex(selected_idx)
        self._window_picker.blockSignals(False)
        self._refresh_cached_window(selected_idx)

    def _refresh_cached_window(self, index):
        """Update the internal cached window from picker index WITHOUT saving settings."""
        if index < 0:
            return
        target = self._window_picker.itemData(index)
        if target:
            window = self._screen_capture.find_target_window(target)
            # Thread-safe update
            with self._window_lock:
                self._screen_capture._cached_window = window

    def _on_window_selected(self, index):
        if index < 0:
            return
        target = self._window_picker.itemData(index)
        if not target:
            return

        friendly_name = target.split("::")[1] if "::" in target else target

        # Immediately resolve + cache the window (thread-safe for hot-swap during automation)
        window = self._screen_capture.find_target_window(target)
        with self._window_lock:
            self._screen_capture._cached_window = window

        # Save selection to settings
        self._settings.target_app = target
        self._project.save_settings(self._settings)

        if window:
            width = window.width if not window.is_entire_screen else "[Full]"
            height = window.height if not window.is_entire_screen else "[Full]"
            self._logger.log(LogCategory.INFO, f"🎯 Target locked: {friendly_name} ({width}×{height})")
        else:
            self._logger.log(LogCategory.WARNING, f"⚠️ Target not visible: {friendly_name} (will retry on capture)")

    def _capture_screen(self):
        self._logger.log(LogCategory.STATE_CHANGE, f"Capturing {self._settings.target_app} screen...")
        image = self._screen_capture.capture_target(self._settings.target_app)
        if image is not None:
            self._recognizer.set_reference(image)
            self._preview.set_image(image)
            self._auto_save()
            self._logger.info("Reference screenshot captured and saved")
        else:
            self._window_status.setText("❌ Capture failed — detect window first")

    def _upload_screenshot(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Upload Reference Screenshot", "",
            "Images (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if filepath and self._recognizer.load_reference(filepath):
            self._preview.set_image(self._recognizer.reference_image)
            self._auto_save()
            self._logger.info("Reference screenshot uploaded and saved")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Threshold & Match
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_threshold_changed(self, value: int):
        self._threshold_label.setText(f"{value}%")
        self._recognizer.threshold = value / 100.0
        self._auto_save()

    def _test_match(self):
        if not self._recognizer.has_reference:
            self._match_status.setText("No ref")
            return
        image = self._screen_capture.capture_target(self._settings.target_app)
        if image is None:
            self._match_status.setText("No window")
            return
        result = self._recognizer.compare(image)
        self._update_match_display(result.similarity, result.is_match)

    def _toggle_live(self, enabled: bool):
        if enabled:
            self._live_timer.start(1000)
        else:
            self._live_timer.stop()

    def _update_match_display(self, similarity: float, is_match: bool):
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

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Timeline Management
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _refresh_table(self):
        self._table.blockSignals(True)  # Prevent itemChanged during rebuild
        actions = self._timeline.actions
        self._table.setRowCount(len(actions))

        type_names = {
            ClickType.SINGLE: "Single",
            ClickType.DOUBLE: "Double",
            ClickType.LONG_PRESS: "Long Press",
        }

        for i, action in enumerate(actions):
            # Checkbox column ("On")
            chk_item = QTableWidgetItem()
            chk_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            chk_item.setCheckState(
                Qt.CheckState.Checked if action.enabled else Qt.CheckState.Unchecked
            )
            self._table.setItem(i, 0, chk_item)

            has_screenshot = "📸" if action.screenshot_path else "—"
            if action.trigger_type == "after_trigger":
                match_cell = f"after #{action.after_index}"
            else:
                match_cell = f"{int(action.threshold * 100)}%{has_screenshot}"
            if action.action_type == "close_app":
                type_label = "Close App" + (" (home)" if action.close_method == "home" else " (quit)")
            elif action.action_type == "open_app":
                type_label = "Open App" + (" (tap)" if action.open_method == "tap_icon" else " (spotlight)")
            else:
                type_label = type_names.get(action.click_type, action.click_type)
            items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(match_cell),
                None,  # Placeholder for the Current% Progress Bar
                QTableWidgetItem(f"{action.delay_ms}"),
                QTableWidgetItem(str(action.x)),
                QTableWidgetItem(str(action.y)),
                QTableWidgetItem(type_label),
                QTableWidgetItem(action.label),
            ]
            for j, item in enumerate(items):
                if item is None:
                    # Create the Progress Bar for the "Current" column
                    bar = QProgressBar()
                    bar.setRange(0, 100)
                    bar.setValue(0)
                    bar.setFormat("%v%")
                    bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLORS['accent']}; border-radius: 2px; }}")
                    self._table.setCellWidget(i, j + 1, bar)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self._table.setItem(i, j + 1, item)

            # Dim disabled rows
            if not action.enabled:
                dim_color = QColor(COLORS["text_muted"])
                for col in range(self._table.columnCount()):
                    it = self._table.item(i, col)
                    if it:
                        it.setForeground(dim_color)

        self._table.blockSignals(False)

        self._duration_label.setText(f"Duration: {self._timeline.total_duration_ms} ms")

        # Update markers on preview
        self._preview.clear_markers()
        for i, action in enumerate(actions):
            if action.enabled:
                self._preview.add_marker(action.x, action.y, f"#{i+1}")

    def _on_table_item_changed(self, item):
        """Handle checkbox toggle in the 'On' column."""
        if item.column() != 0:
            return
        row = item.row()
        actions = self._timeline.actions
        if row >= len(actions):
            return
        is_checked = item.checkState() == Qt.CheckState.Checked
        if actions[row].enabled != is_checked:
            actions[row].enabled = is_checked
            self._timeline.update_action(row, actions[row])
            # Update row dimming
            for col in range(self._table.columnCount()):
                it = self._table.item(row, col)
                if it and col > 0:  # Skip checkbox itself
                    if is_checked:
                        it.setForeground(QColor(COLORS["text_primary"]))
                    else:
                        it.setForeground(QColor(COLORS["text_muted"]))
            self._auto_save()

    def _on_row_selected(self):
        """When a table row is clicked, show that action's screenshot on the left."""
        row = self._table.currentRow()
        if row < 0:
            return
        actions = self._timeline.actions
        if row >= len(actions):
            return
        action = actions[row]

        # Show action info
        action_label = action.label or f"Action #{row + 1}"
        self._action_info_label.setText(f"🎯 {action_label}  —  ({action.x}, {action.y})")

        # Load and display per-action screenshot
        if action.screenshot_path:
            img = self._project.load_action_screenshot(action.screenshot_path)
            if img is not None:
                self._preview.set_image(img)
                # Show just this action's marker
                self._preview.clear_markers()
                self._preview.add_marker(action.x, action.y, f"#{row + 1}")
                return

        # Fallback: show reference with this action highlighted
        if self._recognizer.has_reference and self._recognizer.reference_image is not None:
            self._preview.set_image(self._recognizer.reference_image)
            self._preview.clear_markers()
            self._preview.add_marker(action.x, action.y, f"#{row + 1}")

    def _on_preview_position_picked(self, x: int, y: int):
        """Click on the left preview to set the selected action's X/Y coordinate."""
        if self._is_running:
            return
        row = self._table.currentRow()
        actions = self._timeline.actions
        if row < 0 or row >= len(actions):
            self._status_label.setText("👆 Select an action row first, then click to set its X/Y")
            self._logger.info("Position pick ignored — select an action row first")
            return
        action = actions[row]
        action.x = x
        action.y = y
        self._timeline.update_action(row, action)
        self._refresh_table()
        self._table.selectRow(row)
        self._preview.clear_markers()
        self._preview.add_marker(x, y, f"#{row + 1}")
        self._auto_save()
        self._logger.info(
            f"Set #{row + 1} '{action.label}' position",
            f"({x}, {y})"
        )

    def _add_action(self):
        from src.gui.timeline_editor import AddClickDialog
        dialog = AddClickDialog(
            picker=self._preview,
            screen_capture=self._screen_capture,
            actions=self._timeline.actions,
            current_index=None,
            parent=self,
        )
        if dialog.exec():
            action = dialog.get_action()

            # Save per-action screenshot if one was captured
            screenshot = dialog.get_screenshot()
            if screenshot is not None:
                idx = len(self._timeline.actions)
                path = self._project.save_action_screenshot(idx, screenshot)
                action.screenshot_path = path

            self._timeline.add_action(action)
            self._refresh_table()
            self._auto_save()

    def _edit_action(self):
        row = self._table.currentRow()
        if row < 0:
            return
        actions = self._timeline.actions
        if row >= len(actions):
            return
        from src.gui.timeline_editor import AddClickDialog
        dialog = AddClickDialog(
            picker=self._preview,
            action=actions[row],
            screen_capture=self._screen_capture,
            actions=self._timeline.actions,
            current_index=row,
            parent=self,
        )
        if dialog.exec():
            action = dialog.get_action()

            # Save per-action screenshot if one was captured
            screenshot = dialog.get_screenshot()
            if screenshot is not None:
                path = self._project.save_action_screenshot(row, screenshot)
                action.screenshot_path = path

            self._timeline.update_action(row, action)
            self._refresh_table()
            self._auto_save()

    def _remove_action(self):
        row = self._table.currentRow()
        if row >= 0:
            self._timeline.remove_action(row)
            self._refresh_table()
            self._auto_save()

    def _move_up(self):
        row = self._table.currentRow()
        if row > 0:
            self._timeline.swap_actions(row, row - 1)
            self._refresh_table()
            self._table.selectRow(row - 1)
            self._auto_save()

    def _move_down(self):
        row = self._table.currentRow()
        if 0 <= row < len(self._timeline.actions) - 1:
            self._timeline.swap_actions(row, row + 1)
            self._refresh_table()
            self._table.selectRow(row + 1)
            self._auto_save()

    def _clear_actions(self):
        reply = QMessageBox.question(
            self, "Clear Timeline", "Remove all click actions?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._timeline.clear()
            self._refresh_table()
            self._auto_save()

    def _on_name_changed(self, text: str):
        self._timeline.name = text
        self._auto_save()

    def _on_loop_changed(self, checked: bool):
        self._timeline.loop = checked
        self._auto_save()

    def _on_loop_count_changed(self, value: int):
        self._timeline.loop_count = value
        self._auto_save()

    def _on_interval_changed(self, value: int):
        self._monitor_interval_ms = value
        self._auto_save()

    def _on_bg_click_changed(self, checked: bool):
        self._settings.background_click = checked
        self._auto_save()

    def _import_timeline(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Import Timeline", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if not filepath:
            return
        try:
            loaded = Timeline.load(filepath)
            self._timeline.clear()
            self._timeline.name = loaded.name
            self._timeline.loop = loaded.loop
            self._timeline.loop_count = loaded.loop_count
            for action in loaded.actions:
                self._timeline.add_action(action)
            self._name_edit.setText(loaded.name)
            self._loop_check.setChecked(loaded.loop)
            self._loop_count_spin.setValue(loaded.loop_count)
            self._refresh_table()
            self._auto_save()
            self._logger.info(f"Imported timeline: {loaded.name}")
        except Exception as e:
            QMessageBox.warning(self, "Import Error", str(e))

    def _export_timeline(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Timeline", f"{self._timeline.name}.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if filepath:
            self._timeline.save(filepath)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Log Viewer (inline)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _on_log_entry_from_thread(self, entry):
        """Called from any thread — bridge to GUI."""
        self._signal_bridge.new_log.emit(entry)

    def _on_new_log(self, entry):
        """Append log entry in the GUI thread."""
        from src.logger import LogEntry
        color = CATEGORY_COLORS.get(entry.category, COLORS["text_primary"])
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self._log_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(entry.format() + "\n", fmt)
        self._log_text.verticalScrollBar().setValue(
            self._log_text.verticalScrollBar().maximum()
        )

    def _clear_log(self):
        self._log_text.clear()
        self._logger.clear()

    def _export_log(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Log", "autoclicker_log.txt",
            "Text Files (*.txt);;All Files (*)"
        )
        if filepath:
            self._logger.export(filepath)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Automation
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _check_permissions(self):
        has_screen = self._screen_capture.check_screen_recording_permission()
        if not has_screen:
            self._logger.warning(
                "Screen Recording permission may not be granted",
                "System Settings → Privacy & Security → Screen Recording"
            )
        if not ClickEngine.has_post_event_permission():
            self._logger.warning(
                "⚠️ Accessibility NOT granted — clicks will be silently ignored by macOS",
                "System Settings → Privacy & Security → Accessibility → enable Python / this app"
            )
        else:
            self._logger.info("Accessibility permission OK — clicks enabled")

    ACCESSIBILITY_HELP = (
        "macOS is silently ignoring the clicks: the app matches the screen but "
        "the taps never reach the iPhone.\n\n"
        "To fix:\n"
        "1.  Open  System Settings → Privacy & Security → Accessibility\n"
        "2.  Enable the entry for this app. Because it runs via Python, it is usually "
        "listed as “Python” — enable EVERY Python entry shown (e.g. python3.11, python3.14).\n"
        "      • If nothing relevant is listed, click ➕ and add the app / Python.\n"
        "3.  If an entry is already ON, toggle it OFF then ON to refresh it.\n"
        "4.  Quit and relaunch this app, then press Start again.\n\n"
        "(A system permission prompt may have just appeared — its “Open System Settings” "
        "button takes you straight there.)"
    )

    def _warn_accessibility(self):
        """Show clear instructions for granting Accessibility (event-posting) permission."""
        # Also fire the native prompt — this adds Python/the app to the Accessibility list
        ClickEngine.request_post_event_permission()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Accessibility permission required")
        box.setText("This app can't send clicks until you grant Accessibility permission.")
        box.setInformativeText(self.ACCESSIBILITY_HELP)
        open_btn = box.addButton("Open Accessibility Settings", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            import subprocess
            subprocess.run(
                ["open", "x-apple.systempreferences:com.apple.preference.security"
                 "?Privacy_Accessibility"],
                capture_output=True,
            )
        self._logger.warning(
            "Accessibility permission missing — clicks are being dropped by macOS",
            "System Settings → Privacy & Security → Accessibility → enable Python / this app"
        )

    def _set_editing_locked(self, locked: bool):
        """Lock or unlock all editing controls during automation."""
        for btn in self._edit_buttons:
            btn.setEnabled(not locked)
        self._name_edit.setEnabled(not locked)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

    def _on_highlight_action(self, index: int):
        """Highlight the currently watching action row (amber).
        Also keeps the last-triggered row highlighted (green)."""
        actions = self._timeline.actions
        for row in range(self._table.rowCount()):
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                if item:
                    if row == index:
                        # Currently watching — amber
                        item.setBackground(QColor("#4a3800"))
                        item.setForeground(QColor("#fbbf24"))
                    elif row == self._last_triggered_index:
                        # Last triggered — green
                        item.setBackground(QColor("#1a5c2e"))
                        item.setForeground(QColor("#4ade80"))
                    else:
                        item.setBackground(QColor("transparent"))
                        # Respect enabled/disabled dim
                        if row < len(actions) and not actions[row].enabled:
                            item.setForeground(QColor(COLORS["text_muted"]))
                        else:
                            item.setForeground(QColor(COLORS["text_primary"]))

        # Scroll to watching row
        if 0 <= index < self._table.rowCount():
            self._table.scrollToItem(
                self._table.item(index, 0),
                QTableWidget.ScrollHint.EnsureVisible
            )

    def _on_action_triggered(self, index: int, reason: str):
        """Called after an action is matched and clicked."""
        import time as _time
        self._last_triggered_index = index
        self._last_triggered_time = _time.time()
        self._last_triggered_reason = reason

        actions = self._timeline.actions
        label = actions[index].label if index < len(actions) else f"#{index+1}"
        self._last_triggered_label.setText(
            f"✅ Last: #{index+1} {label} — via {reason} — just now"
        )
        self._last_triggered_label.setVisible(True)

        # Also show the triggered action's screenshot on the left
        if index < len(actions):
            action = actions[index]
            if action.screenshot_path:
                img = self._project.load_action_screenshot(action.screenshot_path)
                if img is not None:
                    self._preview.set_image(img)
                    self._preview.clear_markers()
                    self._preview.add_marker(action.x, action.y, f"#{index+1} ✅")

        # Highlight the triggered row green
        for col in range(self._table.columnCount()):
            item = self._table.item(index, col)
            if item:
                item.setBackground(QColor("#1a5c2e"))
                item.setForeground(QColor("#4ade80"))

    def _update_elapsed_display(self):
        """Update the 'X seconds ago' label every second."""
        import time as _time
        if self._last_triggered_index < 0:
            return
        elapsed = _time.time() - self._last_triggered_time
        actions = self._timeline.actions
        idx = self._last_triggered_index
        label = actions[idx].label if idx < len(actions) else f"#{idx+1}"

        if elapsed < 60:
            time_str = f"{int(elapsed)}s ago"
        elif elapsed < 3600:
            time_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s ago"
        else:
            time_str = f"{int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m ago"

        self._last_triggered_label.setText(
            f"✅ Last: #{idx+1} {label} — via {self._last_triggered_reason} — {time_str}"
        )

    def _clear_row_highlights(self):
        """Remove all row highlights."""
        actions = self._timeline.actions
        for row in range(self._table.rowCount()):
            for col in range(self._table.columnCount()):
                item = self._table.item(row, col)
                if item:
                    item.setBackground(QColor("transparent"))
                    if row < len(actions) and not actions[row].enabled:
                        item.setForeground(QColor(COLORS["text_muted"]))
                    else:
                        item.setForeground(QColor(COLORS["text_primary"]))

    def _start_automation(self):
        if self._is_running:
            return

        # Accessibility / event-posting permission — without it clicks silently no-op
        if not ClickEngine.has_post_event_permission():
            self._warn_accessibility()
            return

        # Check that actions have screenshots or text patterns
        has_any_ref = self._recognizer.has_reference
        actions = self._timeline.actions
        for a in actions:
            if a.screenshot_path or (a.match_texts and a.match_texts.strip()):
                has_any_ref = True
                break
        if not has_any_ref:
            QMessageBox.warning(
                self, "No Screenshots",
                "Actions need reference screenshots.\n"
                "Edit each action and capture a screenshot of the screen state\n"
                "that should trigger it."
            )
            return

        if not self._timeline.actions:
            QMessageBox.warning(
                self, "No Actions",
                "Please add at least one click action to the timeline."
            )
            return

        window = self._screen_capture.find_target_window(self._settings.target_app)
        friendly_name = self._settings.target_app.split("::")[1] if "::" in self._settings.target_app else self._settings.target_app
        if window is None:
            QMessageBox.warning(
                self, "Window Not Found",
                f"Could not find window matching '{friendly_name}'.\n"
                "Make sure it's open and visible."
            )
            return

        self._is_running = True
        self._stop_event.clear()
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._set_editing_locked(True)
        self._status_label.setText("🟢 Running")
        self._status_label.setStyleSheet(
            f"color: {COLORS['success']}; "
            f"background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['success']};"
        )

        self._logger.log(
            LogCategory.STATE_CHANGE, "Automation started",
            f"Monitoring every {self._monitor_interval_ms}ms, "
            f"threshold: {self._recognizer.threshold * 100:.0f}%"
        )

        self._automation_thread = threading.Thread(
            target=self._automation_loop, daemon=True,
        )
        self._automation_thread.start()
        self._elapsed_timer.start()
        self._btn_pulse_state = False
        self._btn_pulse_timer.start()

    def _stop_automation(self):
        self._stop_event.set()
        self._timeline_executor.stop()
        # Animate stop button as "stopping..."
        self._stop_btn.setText("⏳  Stopping...")
        self._logger.log(LogCategory.STATE_CHANGE, "Automation stop requested")

    def _pulse_buttons(self):
        """Toggle a pulsing glow on the Stop button while automation is running."""
        self._btn_pulse_state = not self._btn_pulse_state
        if self._btn_pulse_state:
            self._stop_btn.setStyleSheet(
                f"background-color: #ff4757; color: white; font-weight: 700; font-size: 14px;"
                f"padding: 12px 32px; border: none; border-radius: 8px;"
                f"box-shadow: 0 0 12px #ff4757;"
            )
        else:
            self._stop_btn.setStyleSheet(
                f"background-color: {COLORS['accent']}; color: white; font-weight: 700; font-size: 14px;"
                f"padding: 12px 32px; border: 2px solid #ff8a95; border-radius: 8px;"
            )

    def _on_automation_stopped(self):
        self._is_running = False
        self._btn_pulse_timer.stop()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._stop_btn.setText("⏹  Stop")
        self._stop_btn.setStyleSheet("")  # reset to stylesheet default
        self._start_btn.setStyleSheet("")  # reset
        self._set_editing_locked(False)
        self._elapsed_timer.stop()
        self._clear_row_highlights()
        self._status_label.setText("⏸ Idle")
        self._status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; "
            f"background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']};"
        )
        self._logger.log(LogCategory.STATE_CHANGE, "Automation stopped")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  Projects (multiple clicks/triggers configurations)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _refresh_project_combo(self):
        """Populate the project selector and select the current project."""
        self._project_combo.blockSignals(True)
        self._project_combo.clear()
        names = set(Project.list_projects())
        names.add("default")
        names.add(self._project.name)
        for n in sorted(names):
            self._project_combo.addItem(n)
        idx = self._project_combo.findText(self._project.name)
        if idx >= 0:
            self._project_combo.setCurrentIndex(idx)
        self._project_combo.blockSignals(False)

    def _new_project(self):
        if self._is_running:
            QMessageBox.information(self, "Busy", "Stop automation before creating a project.")
            return
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        name = (name or "").strip().replace("/", "_").replace("\\", "_")
        if not ok or not name:
            return
        if name in Project.list_projects():
            QMessageBox.information(self, "Project Exists",
                                    f"'{name}' already exists — switching to it.")
            self._auto_save()
            self._load_project(name)
            return
        self._auto_save()  # persist current project before switching
        self._load_project(name, fresh=True)
        self._logger.info(f"Created project: {name}")

    def _on_project_selected(self, name: str):
        name = (name or "").strip()
        if not name or name == self._project.name:
            return
        if self._is_running:
            QMessageBox.information(self, "Busy", "Stop automation before switching projects.")
            self._refresh_project_combo()  # revert selection
            return
        self._auto_save()
        self._load_project(name)

    def _load_project(self, name: str, fresh: bool = False):
        """Switch to a different project and reload all project-bound state."""
        self._project = Project(name)
        self._settings = self._project.load_settings()

        if fresh:
            self._timeline = Timeline(name)
        else:
            loaded = self._project.load_timeline()
            self._timeline = loaded if loaded else Timeline(name)

        # Recognizer + reference screenshot
        self._recognizer = ScreenRecognizer(threshold=self._settings.threshold)
        ref = self._project.load_reference()
        if ref is not None:
            self._recognizer.set_reference(ref)
            self._preview.set_image(ref)
        self._monitor_interval_ms = self._settings.monitor_interval_ms

        # Sync UI controls (block signals to avoid re-saving during refresh)
        for widget, setter in (
            (self._name_edit, lambda: self._name_edit.setText(self._timeline.name)),
            (self._threshold_slider, lambda: self._threshold_slider.setValue(int(self._settings.threshold * 100))),
            (self._interval_spin, lambda: self._interval_spin.setValue(self._monitor_interval_ms)),
            (self._bg_click_check, lambda: self._bg_click_check.setChecked(self._settings.background_click)),
            (self._loop_check, lambda: self._loop_check.setChecked(self._timeline.loop)),
            (self._loop_count_spin, lambda: self._loop_count_spin.setValue(self._timeline.loop_count)),
        ):
            widget.blockSignals(True)
            setter()
            widget.blockSignals(False)
        self._threshold_label.setText(f"{int(self._settings.threshold * 100)}%")

        self._refresh_table()
        self._refresh_project_combo()
        self._detect_window()  # re-resolve target window for this project's target_app
        self._project.save_settings(self._settings)
        self._project.save_timeline(self._timeline)
        self._logger.info(f"Switched to project: {name}",
                          f"{len(self._timeline.actions)} actions")

    def _scale_to_window(self, action, window):
        """Convert an action's stored coords (capture-pixel space) to window logical points.

        Reference screenshots may be captured at Retina 2x, so the position picker
        records coordinates in image-pixel space. Clicks (CGEvent) use window points,
        so scale by window.width / screenshot.width. For 1x captures this is a no-op.
        """
        x, y = action.x, action.y
        if window is None or not window.width or not window.height:
            return x, y
        import cv2, os
        ref = None
        if action.screenshot_path and os.path.exists(action.screenshot_path):
            ref = cv2.imread(action.screenshot_path)
        if ref is None and self._recognizer.reference_image is not None:
            ref = self._recognizer.reference_image
        if ref is not None and ref.shape[1] > 0 and ref.shape[0] > 0:
            return (int(round(x * window.width / ref.shape[1])),
                    int(round(y * window.height / ref.shape[0])))
        return x, y

    def _perform_app_action(self, action, window):
        """Close or open the mirrored iPhone app via iPhone Mirroring controls.
        Runs on the automation thread (AppleScript + CGEvent only — no AppKit)."""
        from src import iphone_control

        def wait_ms(ms):
            if ms > 0:
                self._stop_event.wait(ms / 1000.0)

        if action.action_type == "close_app":
            if action.close_method == "home":
                self._logger.log(LogCategory.STATE_CHANGE, "📱 Close App → Home Screen")
                iphone_control.send_command("home")
            else:
                self._logger.log(LogCategory.STATE_CHANGE,
                                 "📱 Close App → force-quit (App Switcher → swipe up → Home)")
                iphone_control.send_command("app_switcher")
                wait_ms(800)
                if window is not None and not window.is_entire_screen and window.width and window.height:
                    w, h = window.width, window.height
                    self._click_engine.swipe(
                        int(w * 0.5), int(h * 0.62),
                        int(w * 0.5), int(h * 0.10),
                        duration_ms=350, window=window,
                        stop_event=self._stop_event,
                    )
                wait_ms(600)
                iphone_control.send_command("home")

        elif action.action_type == "open_app":
            if action.open_method == "tap_icon":
                self._logger.log(LogCategory.STATE_CHANGE, "📱 Open App → Home → tap icon")
                iphone_control.send_command("home")
                wait_ms(800)
                cx, cy = self._scale_to_window(action, window)
                self._click_engine.click_at(
                    cx, cy, window=window,
                    background=False, stop_event=self._stop_event,
                )
            else:
                name = action.app_name or ""
                self._logger.log(LogCategory.STATE_CHANGE,
                                 f"📱 Open App → Spotlight: '{name}'")
                iphone_control.send_command("spotlight")
                wait_ms(800)
                if name:
                    iphone_control.type_text(name, press_return=True)

        wait_ms(action.post_delay_ms)

    def _execute_action(self, action, i, cached, reason):
        """Perform an action's effect (click or app-lifecycle). Shared by recognition
        and 'after another trigger' firing. Does not handle pre-delay or cooldown."""
        self._signal_bridge.highlight_action.emit(i)

        # App-lifecycle actions (close / open the mirrored iPhone app)
        if action.action_type in ("close_app", "open_app"):
            self._perform_app_action(action, cached)
            self._signal_bridge.action_triggered.emit(i, reason)
            self._signal_bridge.status_update.emit(
                f"✅ #{i+1} '{action.label}' — {action.action_type}"
            )
            return

        # Bring window to front on the main thread (AppKit requirement)
        is_bg_click = self._settings.background_click
        if not is_bg_click:
            self._bring_to_front_done.clear()
            self._signal_bridge.bring_to_front.emit()
            self._bring_to_front_done.wait(timeout=2.0)
            time.sleep(0.05)

        clicks = max(1, action.repeat_count)
        click_interval = 1.0 / clicks if clicks > 1 else 0
        cx_pts, cy_pts = self._scale_to_window(action, cached)
        self._logger.click(
            f"Click #{i+1}: ({cx_pts}, {cy_pts}) x{clicks}",
            f"type={action.click_type}, bg={is_bg_click}"
        )
        for click_n in range(clicks):
            if self._stop_event.is_set():
                return
            self._click_engine.click_at(
                cx_pts, cy_pts,
                click_type=action.click_type,
                duration_ms=action.duration_ms,
                background=is_bg_click,
                stop_event=self._stop_event,
            )
            if click_n < clicks - 1 and click_interval > 0:
                self._stop_event.wait(click_interval)

        self._signal_bridge.action_triggered.emit(i, reason)
        self._signal_bridge.status_update.emit(
            f"✅ #{i+1} '{action.label}' clicked x{clicks}"
        )

    def _automation_loop(self):
        """Simple model: capture screen → compare ALL action screenshots → click first match → repeat.
        Also fires 'after another trigger' actions when their delay elapses.
        Runs forever until stopped.
        """
        import cv2
        from skimage.metrics import structural_similarity as ssim

        actions = self._timeline.actions

        # Per-action last-trigger timestamps (monotonic) for "after another trigger" actions
        self._trigger_times = {}
        # Latched countdown start per follower (so a continuously-matching reference
        # action doesn't keep resetting the delay)
        self._after_start = {}

        # Preload all action reference images
        action_refs = {}  # index -> numpy image
        for i, action in enumerate(actions):
            if not action.enabled:
                self._logger.info(f"#{i+1} ({action.label}) is DISABLED, skipping")
                continue
            if action.trigger_type == "after_trigger":
                self._logger.info(
                    f"#{i+1} ({action.label}) fires {action.delay_ms}ms after #{action.after_index}"
                )
                continue
            ref_img = None
            if action.screenshot_path:
                ref_img = self._project.load_action_screenshot(action.screenshot_path)
                if ref_img is not None:
                    self._logger.info(f"Loaded screenshot for #{i+1} ({action.label})")
                else:
                    self._logger.warning(
                        f"#{i+1} screenshot file not found: {action.screenshot_path}"
                    )
            if ref_img is None and self._recognizer.has_reference:
                ref_img = self._recognizer.reference_image
                self._logger.info(f"#{i+1} using global reference as fallback")
            if ref_img is not None:
                action_refs[i] = ref_img
            else:
                self._logger.warning(f"#{i+1} has NO reference image, will skip")

        # Parse text patterns once
        action_text_patterns = {}
        for i, action in enumerate(actions):
            if not action.enabled or action.trigger_type == "after_trigger":
                continue
            if action.match_texts and action.match_texts.strip():
                patterns = [t.strip() for t in action.match_texts.split(",") if t.strip()]
                action_text_patterns[i] = patterns
                self._logger.info(f"#{i+1} text patterns: {patterns}")

        self._logger.info(
            f"Ready: {len(action_refs)} screenshots, {len(action_text_patterns)} text matchers"
        )

        try:
            while not self._stop_event.is_set():
                # 1. Read current target window (hot-swappable: re-read each tick under lock)
                with self._window_lock:
                    cached = self._screen_capture.get_cached_window()

                # If cache was cleared (e.g. app quit), try one re-lookup
                if cached is None:
                    with self._window_lock:
                        cached = self._screen_capture.find_target_window(self._settings.target_app)

                image = self._screen_capture.capture_window(cached) if cached else None

                if image is None:
                    friendly = self._settings.target_app.split("::")[1] if "::" in self._settings.target_app else self._settings.target_app
                    self._logger.warning(f"Cannot capture '{friendly}' — window not found or inaccessible")
                    self._signal_bridge.status_update.emit("⚠️ No window")
                    self._stop_event.wait(self._monitor_interval_ms / 1000.0)
                    continue



                # 1c. Fire any due "after another trigger" actions (time-based, no recognition)
                now = time.monotonic()
                fired_after = False
                for i, action in enumerate(actions):
                    if self._stop_event.is_set():
                        return
                    if not action.enabled or action.trigger_type != "after_trigger":
                        continue
                    ref_last = self._trigger_times.get(action.after_index - 1)
                    if ref_last is None:
                        continue  # the action it follows hasn't triggered yet
                    start = self._after_start.get(i)
                    if start is None:
                        # Arm the countdown when the referenced action triggers after our
                        # last fire — latched, so a continuously-matching ref doesn't reset it
                        if ref_last > self._trigger_times.get(i, -1.0):
                            start = ref_last
                            self._after_start[i] = start
                        else:
                            continue
                    if (now - start) < (action.delay_ms / 1000.0):
                        continue  # delay not elapsed yet
                    self._logger.match(
                        f"#{i+1} '{action.label}' fired {action.delay_ms}ms after #{action.after_index}",
                        ""
                    )
                    self._execute_action(action, i, cached, f"after #{action.after_index} +{action.delay_ms}ms")
                    self._trigger_times[i] = time.monotonic()
                    self._after_start[i] = None  # consumed; re-arm on the next ref trigger
                    fired_after = True
                    break
                if fired_after:
                    self._stop_event.wait(0.5)
                    continue

                cur_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

                # 2. Compare against ALL action screenshots
                best_match_idx = -1
                best_similarity = 0.0
                best_reason = ""
                sim_scores = [0.0] * len(actions)

                for i, action in enumerate(actions):
                    if self._stop_event.is_set():
                        return

                    if not action.enabled:
                        continue

                    # Screenshot comparison
                    if i in action_refs:
                        ref = action_refs[i]
                        try:
                            ref_gray = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
                            compare_gray = cur_gray
                            if ref_gray.shape != compare_gray.shape:
                                compare_gray = cv2.resize(
                                    compare_gray,
                                    (ref_gray.shape[1], ref_gray.shape[0])
                                )
                            sim = float(ssim(ref_gray, compare_gray))
                        except Exception as e:
                            self._logger.warning(f"SSIM error for #{i+1}: {e}")
                            sim = 0.0

                        sim_scores[i] = sim
                        if sim >= action.threshold and sim > best_similarity:
                            best_similarity = sim
                            best_match_idx = i
                            best_reason = f"screenshot ({sim*100:.1f}%)"

                # Text matching — only if no screenshot match was found
                if best_match_idx < 0:
                    for i, action in enumerate(actions):
                        if self._stop_event.is_set():
                            return
                        if not action.enabled:
                            continue
                        if i in action_text_patterns:
                            try:
                                from src.ocr import text_matches_any
                                text_match, matched_text, all_texts = text_matches_any(
                                    image, action_text_patterns[i]
                                )
                                # (Raw OCR texts are intentionally not logged here to prevent UI spam)
                                if text_match:
                                    sim_scores[i] = 1.0  # Force text match to show as 100% locally
                                    best_match_idx = i
                                    best_reason = f'text: "{matched_text}"'
                                    break  # First text match wins
                            except Exception as e:
                                self._logger.warning(f"OCR error for #{i+1}: {e}")

                # 3. Update display
                self._signal_bridge.match_update.emit(
                    sim_scores, best_match_idx
                )

                # 4. If we found a match → fire it
                if best_match_idx >= 0:
                    action = actions[best_match_idx]
                    i = best_match_idx

                    self._logger.match(
                        f"#{i+1} '{action.label}' matched via {best_reason}",
                        f"threshold: {action.threshold*100:.0f}%"
                    )

                    # Wait delay after match
                    if action.delay_ms > 0:
                        self._signal_bridge.status_update.emit(
                            f"⏳ #{i+1} waiting {action.delay_ms}ms..."
                        )
                        self._stop_event.wait(action.delay_ms / 1000.0)
                        if self._stop_event.is_set():
                            return

                    self._execute_action(action, i, cached, best_reason)
                    self._trigger_times[i] = time.monotonic()

                    # Cooldown — screen will change after the action
                    self._stop_event.wait(1.0)
                else:
                    # No match — show scanning status
                    self._signal_bridge.status_update.emit(
                        f"🔍 Scanning all {len(actions)} actions..."
                    )
                    self._stop_event.wait(self._monitor_interval_ms / 1000.0)

        except Exception as e:
            self._logger.error(f"Automation error: {e}")
        finally:
            self._signal_bridge.automation_stopped.emit()

    def _on_match_update(self, sim_scores: list, best_match_idx: int):
        best_sim = max(sim_scores) if sim_scores else 0.0
        self._update_match_display(float(best_sim), best_match_idx >= 0)

        # Update per-row progress bars with smooth animation
        for i, sim in enumerate(sim_scores):
            bar = self._table.cellWidget(i, 3)  # current % progress bar is col 3
            if isinstance(bar, QProgressBar):
                target_val = int(sim * 100)
                
                if i == best_match_idx:
                    bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLORS['success']}; border-radius: 2px; }}")
                else:
                    bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {COLORS['accent']}; border-radius: 2px; }}")
                
                # Assign / Start animation safely
                if not hasattr(bar, '_anim'):
                    bar._anim = QPropertyAnimation(bar, b"value", parent=bar)
                    bar._anim.setEasingCurve(QEasingCurve.Type.OutQuad)
                
                bar._anim.stop()
                bar._anim.setDuration(max(100, min(self._monitor_interval_ms, 500)))
                bar._anim.setStartValue(bar.value())
                bar._anim.setEndValue(target_val)
                bar._anim.start()

    def _on_status_update(self, status: str):
        self._status_label.setText(status)

    def _on_bring_to_front(self):
        """Bring target window to front — runs on main thread (AppKit requirement)."""
        try:
            self._click_engine.bring_target_to_front()
        except Exception:
            pass
        finally:
            self._bring_to_front_done.set()

    def closeEvent(self, event):
        # Block table signals FIRST to prevent itemChanged firing during destruction
        self._table.blockSignals(True)

        # Stop timers immediately
        self._live_timer.stop()
        self._elapsed_timer.stop()

        try:
            self._auto_save()
        except Exception:
            pass

        # Signal automation thread to stop
        self._stop_event.set()
        self._bring_to_front_done.set()  # Unblock if waiting

        try:
            self._timeline_executor.stop()
        except Exception:
            pass

        # Wait for automation thread to finish
        if self._automation_thread and self._automation_thread.is_alive():
            self._automation_thread.join(timeout=2.0)

        # Disconnect all signal bridge connections to prevent signals during destruction
        try:
            self._signal_bridge.match_update.disconnect()
            self._signal_bridge.status_update.disconnect()
            self._signal_bridge.automation_stopped.disconnect()
            self._signal_bridge.new_log.disconnect()
            self._signal_bridge.highlight_action.disconnect()
            self._signal_bridge.action_triggered.disconnect()
            self._signal_bridge.bring_to_front.disconnect()
        except Exception:
            pass

        event.accept()
