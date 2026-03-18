"""
iOS Auto-Clicker for macOS
Entry point — launches the GUI application.
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt


def check_macos():
    """Ensure we're running on macOS."""
    if sys.platform != "darwin":
        print("ERROR: This application only runs on macOS.")
        sys.exit(1)


def show_permission_dialog(app: QApplication):
    """Show a dialog about required permissions."""
    msg = QMessageBox()
    msg.setWindowTitle("Permissions Required")
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setText(
        "iOS Auto-Clicker requires the following macOS permissions:\n\n"
        "1. Screen Recording — to capture the iPhone Mirroring window\n"
        "2. Accessibility — to send clicks to the window\n\n"
        "Please enable both in:\n"
        "System Settings → Privacy & Security\n\n"
        "The app will work without them, but features will be limited."
    )
    msg.setStandardButtons(QMessageBox.StandardButton.Ok)
    msg.exec()


def main():
    check_macos()

    # High-DPI support
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

    app = QApplication(sys.argv)
    app.setApplicationName("iOS Auto-Clicker")
    app.setApplicationDisplayName("iOS Auto-Clicker")

    # Import main window (after QApplication is created)
    from src.gui.main_window import MainWindow

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
