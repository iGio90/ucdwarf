from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QColor
from PyQt5.QtWidgets import QHeaderView, QMenu

from ui.widgets.list_view import DwarfListView


class EmulatorContextList(DwarfListView):
    def __init__(self, parent):
        super().__init__()

        self.context_tab_widget = parent

        self._emulatorctx_model = QStandardItemModel(0, 3)
        self._emulatorctx_model.setHeaderData(0, Qt.Horizontal, 'Reg')
        self._emulatorctx_model.setHeaderData(0, Qt.Horizontal, Qt.AlignCenter, Qt.TextAlignmentRole)
        self._emulatorctx_model.setHeaderData(1, Qt.Horizontal, 'Value')
        self._emulatorctx_model.setHeaderData(1, Qt.Horizontal, Qt.AlignCenter, Qt.TextAlignmentRole)
        self._emulatorctx_model.setHeaderData(2, Qt.Horizontal, 'Decimal')

        self.setModel(self._emulatorctx_model)

        self.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_emulator_contextmenu)

    def _on_emulator_contextmenu(self, pos):
        index = self.indexAt(pos).row()
        glbl_pt = self.mapToGlobal(pos)
        context_menu = QMenu(self)
        if index != -1:
            # show contextmenu
            context_menu.exec_(glbl_pt)

    def set_context(self, ptr, context):
        self.context_tab_widget.setCurrentIndex(self.context_tab_widget.indexOf(self))

        context_ptr = ptr
        context = context.__dict__

        sorted_regs = self.context_tab_widget.get_sort_order()

        for register in sorted(context, key=lambda x: sorted_regs[x] if x in sorted_regs else len(sorted_regs)):
            if register.startswith('_') or register not in sorted_regs:
                continue

            reg_name = QStandardItem()
            reg_name.setTextAlignment(Qt.AlignCenter)
            reg_name.setForeground(QColor('#39c'))
            value_x = QStandardItem()
            # value_x.setTextAlignment(Qt.AlignCenter)
            value_dec = QStandardItem()
            # value_dec.setTextAlignment(Qt.AlignCenter)

            reg_name.setText(register)
            reg_name.setData(context_ptr, Qt.UserRole + 1)

            if context[register] is not None:
                if isinstance(context[register], int):
                    str_fmt = '0x{0:x}'
                    if self.uppercase_hex:
                        str_fmt = '0x{0:X}'
                    value_x.setText(str_fmt.format(context[register]))
                    value_dec.setText('{0:d}'.format(context[register]))

            self._emulatorctx_model.appendRow([reg_name, value_x, value_dec])
            self.resizeColumnToContents(0)
            self.resizeColumnToContents(1)
