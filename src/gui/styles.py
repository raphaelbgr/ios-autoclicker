"""
Dark theme stylesheet for the iOS Auto-Clicker GUI.
Modern, polished appearance with a consistent color palette.
"""

# Color palette
COLORS = {
    "bg_primary": "#1a1a2e",
    "bg_secondary": "#16213e",
    "bg_tertiary": "#0f3460",
    "bg_card": "#1e2746",
    "bg_input": "#0d1b36",
    "accent": "#e94560",
    "accent_hover": "#ff6b81",
    "accent_secondary": "#533483",
    "success": "#00d2d3",
    "warning": "#feca57",
    "error": "#ff6b6b",
    "text_primary": "#eaf0fb",
    "text_secondary": "#a0aec0",
    "text_muted": "#636e7f",
    "border": "#2d3a5c",
    "border_focus": "#e94560",
    "scrollbar": "#2d3a5c",
    "scrollbar_hover": "#3d4a6c",
}

STYLESHEET = f"""
/* ─── Global ────────────────────────────────────────── */
QMainWindow, QWidget {{
    background-color: {COLORS["bg_primary"]};
    color: {COLORS["text_primary"]};
    font-family: "Helvetica Neue", "Helvetica";
    font-size: 13px;
}}

/* ─── Tab Widget ────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    background-color: {COLORS["bg_secondary"]};
    padding: 8px;
}}

QTabBar::tab {{
    background-color: {COLORS["bg_tertiary"]};
    color: {COLORS["text_secondary"]};
    border: 1px solid {COLORS["border"]};
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 10px 20px;
    margin-right: 2px;
    font-weight: 500;
}}

QTabBar::tab:selected {{
    background-color: {COLORS["bg_secondary"]};
    color: {COLORS["accent"]};
    border-bottom: 2px solid {COLORS["accent"]};
    font-weight: 600;
}}

QTabBar::tab:hover:!selected {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text_primary"]};
}}

/* ─── Buttons ───────────────────────────────────────── */
QPushButton {{
    background-color: {COLORS["bg_tertiary"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 500;
    min-height: 20px;
}}

QPushButton:hover {{
    background-color: {COLORS["accent_secondary"]};
    border-color: {COLORS["accent"]};
}}

QPushButton:pressed {{
    background-color: {COLORS["accent"]};
}}

QPushButton:disabled {{
    background-color: {COLORS["bg_input"]};
    color: {COLORS["text_muted"]};
    border-color: {COLORS["bg_input"]};
}}

QPushButton#startButton {{
    background-color: {COLORS["success"]};
    color: {COLORS["bg_primary"]};
    font-weight: 700;
    font-size: 14px;
    padding: 12px 32px;
    border: none;
    border-radius: 8px;
}}

QPushButton#startButton:hover {{
    background-color: #00e5e5;
}}

QPushButton#stopButton {{
    background-color: {COLORS["accent"]};
    color: white;
    font-weight: 700;
    font-size: 14px;
    padding: 12px 32px;
    border: none;
    border-radius: 8px;
}}

QPushButton#stopButton:hover {{
    background-color: {COLORS["accent_hover"]};
}}

/* ─── Labels ────────────────────────────────────────── */
QLabel {{
    color: {COLORS["text_primary"]};
}}

QLabel#header {{
    font-size: 18px;
    font-weight: 700;
    color: {COLORS["accent"]};
    padding: 4px 0;
}}

QLabel#subheader {{
    font-size: 14px;
    font-weight: 500;
    color: {COLORS["text_secondary"]};
}}

QLabel#statusLabel {{
    font-size: 14px;
    font-weight: 600;
    padding: 8px 16px;
    border-radius: 6px;
    background-color: {COLORS["bg_card"]};
    border: 1px solid {COLORS["border"]};
}}

/* ─── Inputs ────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {COLORS["bg_input"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    padding: 8px 12px;
    selection-background-color: {COLORS["accent"]};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {COLORS["border_focus"]};
}}

QComboBox {{
    background-color: {COLORS["bg_input"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    padding: 8px 12px;
    min-width: 120px;
}}

QComboBox::drop-down {{
    border: none;
    width: 30px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    selection-background-color: {COLORS["accent"]};
}}

/* ─── Slider ────────────────────────────────────────── */
QSlider::groove:horizontal {{
    border: none;
    height: 6px;
    background-color: {COLORS["bg_input"]};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background-color: {COLORS["accent"]};
    border: none;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}}

QSlider::handle:horizontal:hover {{
    background-color: {COLORS["accent_hover"]};
}}

QSlider::sub-page:horizontal {{
    background-color: {COLORS["accent"]};
    border-radius: 3px;
}}

/* ─── Table ─────────────────────────────────────────── */
QTableWidget {{
    background-color: {COLORS["bg_input"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    gridline-color: {COLORS["border"]};
    selection-background-color: {COLORS["accent_secondary"]};
}}

QTableWidget::item {{
    padding: 6px 8px;
}}

QHeaderView::section {{
    background-color: {COLORS["bg_tertiary"]};
    color: {COLORS["text_secondary"]};
    border: none;
    border-bottom: 2px solid {COLORS["accent"]};
    padding: 8px;
    font-weight: 600;
}}

/* ─── Scrollbar ─────────────────────────────────────── */
QScrollBar:vertical {{
    background-color: {COLORS["bg_primary"]};
    width: 10px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background-color: {COLORS["scrollbar"]};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLORS["scrollbar_hover"]};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: {COLORS["bg_primary"]};
    height: 10px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal {{
    background-color: {COLORS["scrollbar"]};
    border-radius: 5px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS["scrollbar_hover"]};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ─── Text Edit (Log Viewer) ────────────────────────── */
QTextEdit {{
    background-color: {COLORS["bg_input"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    padding: 8px;
    font-family: "Menlo", "Monaco", "Consolas";
    font-size: 12px;
}}

/* ─── Group Box ─────────────────────────────────────── */
QGroupBox {{
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    margin-top: 16px;
    padding-top: 16px;
    font-weight: 600;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 8px;
    color: {COLORS["accent"]};
}}

/* ─── Progress Bar ──────────────────────────────────── */
QProgressBar {{
    background-color: {COLORS["bg_input"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 6px;
    text-align: center;
    color: {COLORS["text_primary"]};
    height: 20px;
}}

QProgressBar::chunk {{
    background-color: {COLORS["accent"]};
    border-radius: 5px;
}}

/* ─── Tooltip ───────────────────────────────────────── */
QToolTip {{
    background-color: {COLORS["bg_card"]};
    color: {COLORS["text_primary"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 4px;
    padding: 6px;
}}

/* ─── Frame (Card) ──────────────────────────────────── */
QFrame#card {{
    background-color: {COLORS["bg_card"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 12px;
}}
"""
