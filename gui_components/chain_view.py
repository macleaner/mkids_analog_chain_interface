"""
Chain View Widget

Displays and manages the current signal chain with reordering capabilities.
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QListWidget, QListWidgetItem, QPushButton, QMessageBox
)
from PySide6.QtCore import Qt

from signal_chain import SignalChain


class ChainView(QWidget):
    """
    View showing the current signal chain with reordering capabilities.
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.chain = SignalChain("User Chain")
        
        layout = QVBoxLayout(self)
        
        # Label
        label = QLabel("Current Chain")
        label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(label)
        
        # List widget
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        self.up_button = QPushButton("▲ Up")
        self.up_button.clicked.connect(self._move_up)
        button_layout.addWidget(self.up_button)
        
        self.down_button = QPushButton("▼ Down")
        self.down_button.clicked.connect(self._move_down)
        button_layout.addWidget(self.down_button)
        
        self.remove_button = QPushButton("✖ Remove")
        self.remove_button.clicked.connect(self._remove_selected)
        button_layout.addWidget(self.remove_button)
        
        self.clear_button = QPushButton("Clear All")
        self.clear_button.clicked.connect(self._clear_all)
        button_layout.addWidget(self.clear_button)
        
        layout.addLayout(button_layout)
        
    def add_component(self, component, description):
        """Add a component to the chain."""
        self.chain.add_component(component)
        
        item = QListWidgetItem(description)
        item.setData(Qt.UserRole, component)
        self.list_widget.addItem(item)
        
    def _move_up(self):
        """Move selected component up in the chain."""
        current_row = self.list_widget.currentRow()
        if current_row > 0:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row - 1, item)
            self.list_widget.setCurrentRow(current_row - 1)
            self._rebuild_chain()
            
    def _move_down(self):
        """Move selected component down in the chain."""
        current_row = self.list_widget.currentRow()
        if current_row < self.list_widget.count() - 1 and current_row >= 0:
            item = self.list_widget.takeItem(current_row)
            self.list_widget.insertItem(current_row + 1, item)
            self.list_widget.setCurrentRow(current_row + 1)
            self._rebuild_chain()
            
    def _remove_selected(self):
        """Remove selected component from chain."""
        current_row = self.list_widget.currentRow()
        if current_row >= 0:
            self.list_widget.takeItem(current_row)
            self._rebuild_chain()
            
    def _clear_all(self):
        """Clear all components from chain."""
        reply = QMessageBox.question(
            self, "Clear Chain",
            "Remove all components from the chain?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.list_widget.clear()
            self._rebuild_chain()
            
    def _rebuild_chain(self):
        """Rebuild the SignalChain object from current list."""
        self.chain = SignalChain("User Chain")
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            component = item.data(Qt.UserRole)
            self.chain.add_component(component)
    
    def get_chain(self):
        """Return the current SignalChain object."""
        self._rebuild_chain()
        return self.chain
