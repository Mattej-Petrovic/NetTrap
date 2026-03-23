from __future__ import annotations

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from nettrap.gui.theme import get_stylesheet


def create_app():
    if QApplication.instance() is None:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    app = QApplication.instance() or QApplication(
        ["NetTrap", "-style", "fusion"] if os.name == "nt" else []
    )
    app.setApplicationName("NetTrap")
    app.setStyleSheet(get_stylesheet())
    return app
