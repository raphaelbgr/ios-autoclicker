"""
Timeline editor panel.
Visual interface for building and editing click action sequences.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QSpinBox, QComboBox, QCheckBox, QFileDialog, QDialog,
    QFormLayout, QDialogButtonBox, QLineEdit, QMessageBox, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from src.timeline import Timeline, ClickAction
from src.click_engine import ClickType
from src.gui.click_position_picker import ClickPositionPicker
from src.gui.styles import COLORS


class AddClickDialog(QDialog):
    """Dialog for adding/editing a click action with embedded screenshot picker."""

    def __init__(self, picker: ClickPositionPicker = None,
                 action: ClickAction = None, screen_capture=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Click Action" if action is None else "Edit Click Action")
        self.setMinimumSize(600, 700)

        self._selected_x = action.x if action else 0
        self._selected_y = action.y if action else 0
        self._screen_capture = screen_capture
        self._captured_image = None  # numpy array of captured screenshot
        self._existing_screenshot_path = action.screenshot_path if action else ""

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Screenshot preview header + capture button ──
        preview_header = QHBoxLayout()
        preview_label = QLabel("📸 Click on the screenshot to pick position:")
        preview_label.setObjectName("subheader")
        preview_header.addWidget(preview_label)
        preview_header.addStretch()

        if screen_capture is not None:
            capture_btn = QPushButton("📸 Capture Now")
            capture_btn.setToolTip("Take a fresh screenshot of the iPhone Mirroring window")
            capture_btn.clicked.connect(self._capture_screen)
            preview_header.addWidget(capture_btn)

        layout.addLayout(preview_header)

        self._local_picker = ClickPositionPicker()
        self._local_picker.setMinimumHeight(350)

        # Copy the reference image from the shared picker
        if picker and picker._original_image is not None:
            self._local_picker.set_pixmap(picker._original_image)
            # Show existing markers from timeline
            for mx, my, label in picker._markers:
                self._local_picker.add_marker(mx, my, label)

        # If editing and action has its own screenshot, show that instead
        if action and action.screenshot_path:
            import cv2, os
            if os.path.exists(action.screenshot_path):
                img = cv2.imread(action.screenshot_path)
                if img is not None:
                    self._local_picker.set_image(img)
                    self._captured_image = img

        self._local_picker.position_selected.connect(self._on_position_picked)
        layout.addWidget(self._local_picker, 1)

        # ── Coordinate display ──
        self._coord_label = QLabel(
            f"Selected: ({self._selected_x}, {self._selected_y})"
        )
        self._coord_label.setStyleSheet(
            f"color: {COLORS['success']}; font-weight: 600; font-size: 14px;"
        )
        layout.addWidget(self._coord_label)

        # ── Form fields ──
        form = QFormLayout()
        form.setSpacing(8)

        # Label
        self._label_edit = QLineEdit(action.label if action else "")
        self._label_edit.setPlaceholderText("e.g., Tap Play Button")
        form.addRow("Label:", self._label_edit)

        # Match threshold (per-action)
        thresh_layout = QHBoxLayout()
        self._threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self._threshold_slider.setRange(0, 100)
        self._threshold_slider.setValue(int((action.threshold if action else 0.85) * 100))
        self._threshold_slider.valueChanged.connect(self._on_threshold_changed)
        thresh_layout.addWidget(self._threshold_slider)
        self._threshold_label = QLabel(f"{self._threshold_slider.value()}%")
        self._threshold_label.setFixedWidth(40)
        thresh_layout.addWidget(self._threshold_label)
        form.addRow("Match threshold:", thresh_layout)

        # Delay after match
        self._delay_spin = QSpinBox()
        self._delay_spin.setRange(0, 600000)
        self._delay_spin.setSuffix(" ms")
        self._delay_spin.setSingleStep(100)
        self._delay_spin.setValue(action.delay_ms if action else 1000)
        form.addRow("Delay after match:", self._delay_spin)

        # Coordinates (manual entry)
        coord_layout = QHBoxLayout()
        self._x_spin = QSpinBox()
        self._x_spin.setRange(0, 5000)
        self._x_spin.setPrefix("X: ")
        self._x_spin.setValue(self._selected_x)
        self._x_spin.valueChanged.connect(self._on_coord_spin_changed)
        coord_layout.addWidget(self._x_spin)

        self._y_spin = QSpinBox()
        self._y_spin.setRange(0, 5000)
        self._y_spin.setPrefix("Y: ")
        self._y_spin.setValue(self._selected_y)
        self._y_spin.valueChanged.connect(self._on_coord_spin_changed)
        coord_layout.addWidget(self._y_spin)

        form.addRow("Position:", coord_layout)

        # Click type
        self._type_combo = QComboBox()
        self._type_combo.addItems(["Single Click", "Double Click", "Long Press"])
        if action:
            type_map = {
                ClickType.SINGLE: 0,
                ClickType.DOUBLE: 1,
                ClickType.LONG_PRESS: 2,
            }
            self._type_combo.setCurrentIndex(type_map.get(action.click_type, 0))
        form.addRow("Click type:", self._type_combo)

        # Duration (for long press)
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(50, 10000)
        self._duration_spin.setSuffix(" ms")
        self._duration_spin.setValue(action.duration_ms if action else 500)
        form.addRow("Hold duration:", self._duration_spin)

        # Text matching (OCR)
        self._match_texts_edit = QLineEdit(action.match_texts if action else "")
        self._match_texts_edit.setPlaceholderText("e.g., game over, victory, score  (comma-separated, OR logic)")
        form.addRow("Also matches text:", self._match_texts_edit)

        # Repeat count (clicks per trigger)
        self._repeat_spin = QSpinBox()
        self._repeat_spin.setRange(1, 50)
        self._repeat_spin.setValue(action.repeat_count if action else 1)
        self._repeat_spin.setToolTip("Number of clicks to fire when this action triggers (spaced within 1s)")
        form.addRow("Repeat clicks:", self._repeat_spin)

        layout.addLayout(form)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _capture_screen(self):
        """Capture a fresh screenshot from iPhone Mirroring."""
        if self._screen_capture is None:
            return
        image = self._screen_capture.capture_iphone_mirroring()
        if image is not None:
            self._local_picker.set_image(image)
            self._captured_image = image

    def _on_position_picked(self, x: int, y: int):
        self._selected_x = x
        self._selected_y = y
        self._x_spin.setValue(x)
        self._y_spin.setValue(y)
        self._coord_label.setText(f"Selected: ({x}, {y})")

    def _on_coord_spin_changed(self):
        self._selected_x = self._x_spin.value()
        self._selected_y = self._y_spin.value()
        self._coord_label.setText(
            f"Selected: ({self._selected_x}, {self._selected_y})"
        )

    def _on_threshold_changed(self, value: int):
        self._threshold_label.setText(f"{value}%")

    def get_action(self) -> ClickAction:
        """Build a ClickAction from the dialog values."""
        type_map = {
            0: ClickType.SINGLE,
            1: ClickType.DOUBLE,
            2: ClickType.LONG_PRESS,
        }
        return ClickAction(
            delay_ms=self._delay_spin.value(),
            x=self._x_spin.value(),
            y=self._y_spin.value(),
            click_type=type_map.get(self._type_combo.currentIndex(), ClickType.SINGLE),
            duration_ms=self._duration_spin.value(),
            label=self._label_edit.text(),
            screenshot_path=self._existing_screenshot_path,
            threshold=self._threshold_slider.value() / 100.0,
            match_texts=self._match_texts_edit.text().strip(),
            repeat_count=self._repeat_spin.value(),
        )

    def get_screenshot(self):
        """Return the captured screenshot image (numpy array) or None."""
        return self._captured_image


class TimelineEditor(QWidget):
    """Timeline editor with table view and action management."""

    timeline_changed = pyqtSignal()

    def __init__(self, timeline: Timeline,
                 picker: ClickPositionPicker = None,
                 screen_capture=None, parent=None):
        super().__init__(parent)
        self._timeline = timeline
        self._picker = picker
        self._screen_capture = screen_capture
        self._setup_ui()
        self._refresh_table()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Header with controls ──
        header_layout = QHBoxLayout()

        title = QLabel("⏱ Click Timeline")
        title.setObjectName("header")
        header_layout.addWidget(title)
        header_layout.addStretch()

        # Timeline name
        self._name_edit = QLineEdit(self._timeline.name)
        self._name_edit.setFixedWidth(200)
        self._name_edit.textChanged.connect(self._on_name_changed)
        header_layout.addWidget(QLabel("Name:"))
        header_layout.addWidget(self._name_edit)

        layout.addLayout(header_layout)

        # ── Action Buttons ──
        btn_layout = QHBoxLayout()

        add_btn = QPushButton("➕ Add Click")
        add_btn.clicked.connect(self._add_action)
        btn_layout.addWidget(add_btn)

        edit_btn = QPushButton("✏️ Edit Selected")
        edit_btn.clicked.connect(self._edit_action)
        btn_layout.addWidget(edit_btn)

        remove_btn = QPushButton("🗑 Remove Selected")
        remove_btn.clicked.connect(self._remove_action)
        btn_layout.addWidget(remove_btn)

        clear_btn = QPushButton("🧹 Clear All")
        clear_btn.clicked.connect(self._clear_actions)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()

        import_btn = QPushButton("📥 Import")
        import_btn.clicked.connect(self._import_timeline)
        btn_layout.addWidget(import_btn)

        export_btn = QPushButton("📤 Export")
        export_btn.clicked.connect(self._export_timeline)
        btn_layout.addWidget(export_btn)

        layout.addLayout(btn_layout)

        # ── Actions Table ──
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "#", "Time (ms)", "X", "Y", "Type", "Label"
        ])

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        self._table.setColumnWidth(0, 40)
        self._table.setColumnWidth(1, 100)
        self._table.setColumnWidth(2, 70)
        self._table.setColumnWidth(3, 70)
        self._table.setColumnWidth(4, 100)

        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.doubleClicked.connect(self._edit_action)
        layout.addWidget(self._table)

        # ── Loop Controls ──
        loop_group = QGroupBox("Loop Settings")
        loop_layout = QHBoxLayout(loop_group)

        self._loop_check = QCheckBox("Loop timeline")
        self._loop_check.setChecked(self._timeline.loop)
        self._loop_check.toggled.connect(self._on_loop_changed)
        loop_layout.addWidget(self._loop_check)

        loop_layout.addWidget(QLabel("Repeat count:"))
        self._loop_count_spin = QSpinBox()
        self._loop_count_spin.setRange(0, 9999)
        self._loop_count_spin.setValue(self._timeline.loop_count)
        self._loop_count_spin.setSpecialValueText("∞ Infinite")
        self._loop_count_spin.valueChanged.connect(self._on_loop_count_changed)
        loop_layout.addWidget(self._loop_count_spin)

        loop_layout.addStretch()

        self._duration_label = QLabel("Total duration: 0 ms")
        self._duration_label.setObjectName("subheader")
        loop_layout.addWidget(self._duration_label)

        layout.addWidget(loop_group)

    def _refresh_table(self):
        """Rebuild the table from the timeline data."""
        actions = self._timeline.actions
        self._table.setRowCount(len(actions))

        type_names = {
            ClickType.SINGLE: "Single",
            ClickType.DOUBLE: "Double",
            ClickType.LONG_PRESS: "Long Press",
        }

        for i, action in enumerate(actions):
            items = [
                QTableWidgetItem(str(i + 1)),
                QTableWidgetItem(str(action.delay_ms)),
                QTableWidgetItem(str(action.x)),
                QTableWidgetItem(str(action.y)),
                QTableWidgetItem(type_names.get(action.click_type, action.click_type)),
                QTableWidgetItem(action.label),
            ]

            for j, item in enumerate(items):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(i, j, item)

        self._duration_label.setText(
            f"Total duration: {self._timeline.total_duration_ms} ms"
        )

        # Update markers on picker
        if self._picker:
            self._picker.clear_markers()
            for i, action in enumerate(actions):
                self._picker.add_marker(action.x, action.y, f"#{i+1}")

    def _add_action(self):
        dialog = AddClickDialog(picker=self._picker,
                                screen_capture=self._screen_capture, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            action = dialog.get_action()
            self._timeline.add_action(action)
            self._refresh_table()
            self.timeline_changed.emit()

    def _edit_action(self):
        row = self._table.currentRow()
        if row < 0:
            return
        actions = self._timeline.actions
        if row >= len(actions):
            return
        dialog = AddClickDialog(
            picker=self._picker, action=actions[row],
            screen_capture=self._screen_capture, parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._timeline.update_action(row, dialog.get_action())
            self._refresh_table()
            self.timeline_changed.emit()

    def _remove_action(self):
        row = self._table.currentRow()
        if row >= 0:
            self._timeline.remove_action(row)
            self._refresh_table()
            self.timeline_changed.emit()

    def _clear_actions(self):
        reply = QMessageBox.question(
            self, "Clear Timeline",
            "Remove all click actions?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._timeline.clear()
            self._refresh_table()
            self.timeline_changed.emit()

    def _on_name_changed(self, text: str):
        self._timeline.name = text

    def _on_loop_changed(self, checked: bool):
        self._timeline.loop = checked
        self.timeline_changed.emit()

    def _on_loop_count_changed(self, value: int):
        self._timeline.loop_count = value
        self.timeline_changed.emit()

    def _import_timeline(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Import Timeline", "",
            "JSON Files (*.json);;All Files (*)"
        )
        if filepath:
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
                self.timeline_changed.emit()
            except Exception as e:
                QMessageBox.warning(self, "Import Error", str(e))

    def _export_timeline(self):
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Export Timeline", f"{self._timeline.name}.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if filepath:
            try:
                self._timeline.save(filepath)
            except Exception as e:
                QMessageBox.warning(self, "Export Error", str(e))

    def set_timeline(self, timeline: Timeline):
        """Replace the current timeline."""
        self._timeline = timeline
        self._name_edit.setText(timeline.name)
        self._loop_check.setChecked(timeline.loop)
        self._loop_count_spin.setValue(timeline.loop_count)
        self._refresh_table()

    def get_timeline(self) -> Timeline:
        return self._timeline
