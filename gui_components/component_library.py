"""
Component Library Widget

Displays available hardware components, grouped by the category each one
declares in the registry.
"""

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
from PySide6.QtCore import Qt, Signal

import registry


class ComponentLibrary(QTreeWidget):
    """
    Tree widget listing the registered components by category.

    Reads the registry rather than scanning ``hardware_models`` for classes.
    Module scanning also picked up imported base classes and helper types
    (ParamSpec, ActiveComponent, PassiveComponent), offering them as selectable
    components that crash when instantiated.
    """

    component_selected = Signal(str, object)  # (category, RegistryEntry)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setHeaderLabel("Component Library")
        self.setColumnCount(1)

        self.categories = registry.by_category()
        self._populate_library()
        self.itemClicked.connect(self._on_item_clicked)

    def _populate_library(self):
        """Build the tree from the registry."""
        for category, entries in self.categories.items():
            category_item = QTreeWidgetItem(self, [category])
            category_item.setExpanded(True)

            for entry in entries:
                comp_item = QTreeWidgetItem(category_item, [entry.label])
                comp_item.setData(0, Qt.UserRole, entry)
                if entry.doc:
                    comp_item.setToolTip(0, entry.doc)

    def _on_item_clicked(self, item, column):
        """Emit the selected registry entry."""
        entry = item.data(0, Qt.UserRole)
        if entry is not None:
            self.component_selected.emit(item.parent().text(0), entry)
