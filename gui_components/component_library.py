"""
Component Library Widget

Displays available hardware components organized by category.
"""

import inspect
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt, Signal

import hardware_models


class ComponentLibrary(QTreeWidget):
    """
    Tree widget displaying available hardware components organized by type.
    """
    
    component_selected = Signal(str, object)  # Signal emitting (category, class)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setHeaderLabel("Component Library")
        self.setColumnCount(1)
        
        # Component categories
        self.categories = {
            "Amplifiers": [],
            "Cables": [],
            "Attenuators": [],
            "Filters": [],
            "Converters": [],
            "Other": []
        }
        
        self._populate_library()
        self.itemClicked.connect(self._on_item_clicked)
        
    def _populate_library(self):
        """Scan hardware_models module and categorize components."""
        
        # Get all classes from hardware_models
        for name, obj in inspect.getmembers(hardware_models, inspect.isclass):
            if name.startswith('_'):
                continue
                
            # Categorize based on naming conventions
            if 'LNA' in name or 'Amp' in name.upper() or name.startswith('ZX') or name.startswith('ASU'):
                self.categories["Amplifiers"].append((name, obj))
            elif 'cable' in name.lower() or 'SMA' in name or 'BCB' in name or 'RG' in name:
                self.categories["Cables"].append((name, obj))
            elif 'Attenuator' in name:
                self.categories["Attenuators"].append((name, obj))
            elif 'Filter' in name:
                self.categories["Filters"].append((name, obj))
            elif 'AD9082' in name or 'DAC' in name or 'ADC' in name:
                self.categories["Converters"].append((name, obj))
            else:
                self.categories["Other"].append((name, obj))
        
        # Build tree structure
        for category, components in self.categories.items():
            if not components:
                continue
                
            category_item = QTreeWidgetItem(self, [category])
            category_item.setExpanded(True)
            
            for comp_name, comp_class in sorted(components, key=lambda x: x[0]):
                comp_item = QTreeWidgetItem(category_item, [comp_name])
                comp_item.setData(0, Qt.UserRole, comp_class)
                
    def _on_item_clicked(self, item, column):
        """Handle item selection."""
        comp_class = item.data(0, Qt.UserRole)
        if comp_class is not None:
            # This is a component, not a category
            category = item.parent().text(0)
            self.component_selected.emit(category, comp_class)
