import sys
import tempfile

from PySide6.QtWidgets import QApplication

from spiced.app.services import Services
from spiced.ui.main_window import NAV_ITEMS, MainWindow
from spiced.ui.theme import build_stylesheet

app = QApplication(sys.argv)
app.setStyleSheet(build_stylesheet())

tmp = tempfile.mktemp(suffix=".db")
services = Services(db_path=tmp)
project = services.projects.create_project("Test")
services.set_active_project(project.id)

window = MainWindow(services)
window.setWindowTitle("Spiced")
window.show()
app.processEvents()

index = NAV_ITEMS.index("Automated Testing")
window._stack.setCurrentIndex(index)
app.processEvents()

app.exec()
