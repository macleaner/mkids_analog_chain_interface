#!/usr/bin/env python3
"""
Analog Chain Builder GUI

A graphical interface for building and analyzing RF signal chains.
Allows users to select components, specify parameters, and construct
signal chains interactively.
"""

import sys
from PySide6.QtWidgets import QApplication

from gui_components import MainWindow


def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
