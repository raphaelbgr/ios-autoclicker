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
    QHeaderView, QCheckBox, QLineEdit, QTextEdit,
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
        self._load_saved_data()
        self._check_permissions()

        self._logger.add_listener(self._on_log_entry_from_thread)
        self._logger.info("Application started", "iOS Auto-Clicker ready")

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

        # Window detection
        detect_layout = QHBoxLayout()
        self._window_status = QLabel("No window detected")
        self._window_status.setObjectName("statusLabel")
        self._window_status.setStyleSheet("font-size: 11px; padding: 4px 8px;")
        detect_layout.addWidget(self._window_status, 1)

        detect_btn = QPushButton("🔍 Detect")
        detect_btn.setFixedWidth(80)
        detect_btn.clicked.connect(self._detect_window)
        detect_layout.addWidget(detect_btn)
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
        self._table.setColumnWidth(5, 45)
        self._table.setColumnWidth(6, 45)
        self._table.setColumnWidth(7, 70)

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
        window = self._screen_capture.find_iphone_mirroring_window()
        if window:
            self._window_status.setText(
                f"✅ {window.owner_name} ({window.width}×{window.height})"
            )
            self._window_status.setStyleSheet(
                f"font-size: 11px; padding: 4px 8px; color: {COLORS['success']};"
            )
        else:
            self._window_status.setText("❌ Not found — open iPhone Mirroring")
            self._window_status.setStyleSheet(
                f"font-size: 11px; padding: 4px 8px; color: {COLORS['error']};"
            )

    def _capture_screen(self):
        image = self._screen_capture.capture_iphone_mirroring()
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
        image = self._screen_capture.capture_iphone_mirroring()
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
            items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(f"{int(action.threshold * 100)}%{has_screenshot}"),
                None,  # Placeholder for the Current% Progress Bar
                QTableWidgetItem(f"{action.delay_ms}"),
                QTableWidgetItem(str(action.x)),
                QTableWidgetItem(str(action.y)),
                QTableWidgetItem(type_names.get(action.click_type, action.click_type)),
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

    def _add_action(self):
        from src.gui.timeline_editor import AddClickDialog
        dialog = AddClickDialog(
            picker=self._preview,
            screen_capture=self._screen_capture,
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
        self._logger.info(
            "Make sure Accessibility permission is enabled",
            "System Settings → Privacy & Security → Accessibility"
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

        window = self._screen_capture.find_iphone_mirroring_window()
        if window is None:
            QMessageBox.warning(
                self, "Window Not Found",
                "Could not find the iPhone Mirroring window.\n"
                "Make sure it's open and visible."
            )
            return

        self._is_running = True
        self._stop_event.clear()
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._set_editing_locked(True)  # Lock editing
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

    def _stop_automation(self):
        self._stop_event.set()
        self._timeline_executor.stop()
        self._logger.log(LogCategory.STATE_CHANGE, "Automation stop requested")

    def _on_automation_stopped(self):
        self._is_running = False
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._set_editing_locked(False)  # Unlock editing
        self._elapsed_timer.stop()
        self._clear_row_highlights()
        # Keep the last-triggered label visible so user sees final state
        self._status_label.setText("⏸ Idle")
        self._status_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; "
            f"background-color: {COLORS['bg_card']}; "
            f"border: 1px solid {COLORS['border']};"
        )
        self._logger.log(LogCategory.STATE_CHANGE, "Automation stopped")

    def _automation_loop(self):
        """Simple model: capture screen → compare ALL action screenshots → click first match → repeat.
        No sequential logic, no loop counting, no triggered tracking.
        Runs forever until stopped.
        """
        import cv2
        from skimage.metrics import structural_similarity as ssim

        actions = self._timeline.actions

        # Preload all action reference images
        action_refs = {}  # index -> numpy image
        for i, action in enumerate(actions):
            if not action.enabled:
                self._logger.info(f"#{i+1} ({action.label}) is DISABLED, skipping")
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
            if not action.enabled:
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
                # 1. Capture current screen
                image = self._screen_capture.capture_iphone_mirroring()
                if image is None:
                    self._signal_bridge.status_update.emit("⚠️ No window")
                    self._stop_event.wait(self._monitor_interval_ms / 1000.0)
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

                # 4. If we found a match → click it
                if best_match_idx >= 0:
                    action = actions[best_match_idx]
                    i = best_match_idx

                    self._signal_bridge.highlight_action.emit(i)
                    self._logger.match(
                        f"#{i+1} '{action.label}' matched via {best_reason}",
                        f"threshold: {action.threshold*100:.0f}%"
                    )

                    # Wait delay
                    if action.delay_ms > 0:
                        self._signal_bridge.status_update.emit(
                            f"⏳ #{i+1} waiting {action.delay_ms}ms..."
                        )
                        self._stop_event.wait(action.delay_ms / 1000.0)
                        if self._stop_event.is_set():
                            return

                    # Bring window to front on the main thread (AppKit requirement)
                    is_bg_click = self._settings.background_click
                    if not is_bg_click:
                        self._bring_to_front_done.clear()
                        self._signal_bridge.bring_to_front.emit()
                        self._bring_to_front_done.wait(timeout=2.0)
                        time.sleep(0.05)

                    # Execute clicks (repeat_count times within 1s window)
                    clicks = max(1, action.repeat_count)
                    click_interval = 1.0 / clicks if clicks > 1 else 0
                    self._logger.click(
                        f"Click #{i+1}: ({action.x}, {action.y}) x{clicks}",
                        f"type={action.click_type}, delay={action.delay_ms}ms, bg={is_bg_click}"
                    )
                    for click_n in range(clicks):
                        if self._stop_event.is_set():
                            return
                        self._click_engine.click_at(
                            action.x, action.y,
                            click_type=action.click_type,
                            duration_ms=action.duration_ms,
                            background=is_bg_click,
                            stop_event=self._stop_event,
                        )
                        if click_n < clicks - 1 and click_interval > 0:
                            self._stop_event.wait(click_interval)

                    self._signal_bridge.action_triggered.emit(i, best_reason)
                    self._signal_bridge.status_update.emit(
                        f"✅ #{i+1} '{action.label}' clicked x{clicks}"
                    )

                    # Cooldown — screen will change after click
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
