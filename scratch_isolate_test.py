import sys
from PySide6.QtWidgets import QApplication, QTabWidget, QVBoxLayout, QWidget

from spiced.ui.theme import build_stylesheet

app = QApplication(sys.argv)
app.setStyleSheet(build_stylesheet())  # the FULL real app stylesheet

w = QWidget()
layout = QVBoxLayout(w)
tabs = QTabWidget()  # plain QTabWidget, NOT PillTabWidget/PillTabBar
tabs.addTab(QWidget(), "Functional")
tabs.addTab(QWidget(), "Performance")
layout.addWidget(tabs)

# manual local override, same as the isolated test that worked
tabs.tabBar().setStyleSheet("QTabBar::tab { border-radius: 16px; }")

w.resize(400, 200)
w.setWindowTitle("IsolateTest")
w.show()
app.exec()
