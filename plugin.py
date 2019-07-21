"""
Dwarf - Copyright (C) 2019 Giovanni Rocca (iGio90)

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <https://www.gnu.org/licenses/>
"""
import os

from PyQt5.QtCore import QObject, pyqtSignal

from plugins.ucdwarf.src.emulator import Emulator, EmulatorThread
from plugins.ucdwarf.src.emulator_context_widget import EmulatorContextList
from ui.widget_console import DwarfConsoleWidget


EMULATOR_CALLBACKS_PATH = 'emulator_callbacks_path'
EMULATOR_INSTRUCTIONS_DELAY = 'emulator_instructions_delay'


class Plugin(QObject):
    onEmulatorApi = pyqtSignal(list, name='onEmulatorApi')

    @staticmethod
    def __get_plugin_info__():
        return {
            'name': 'ucdwarf',
            'description': 'unicorn emulator in Dwarf',
            'version': '1.0.0',
            'author': 'iGio90',
            'homepage': 'https://github.com/iGio90/ucdwarf',
            'license': 'https://www.gnu.org/licenses/gpl-3.0',
        }

    def __get_top_menu_actions__(self):
        return []

    def __get_agent__(self):
        self.app.dwarf.onReceiveCmd.connect(self._on_receive_cmd)

        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'agent.js'), 'r') as f:
            return f.read()

    def __init__(self, app):
        super().__init__()
        self.app = app

        self.console = None
        self.emulator_panel = None
        self.emulator = None
        self._emu_queue = []
        self._emu_thread = None

        self.app.session_manager.sessionCreated.connect(self._on_session_created)
        self.app.session_manager.sessionStopped.connect(self._on_session_stopped)
        self.app.onSystemUIElementCreated.connect(self._on_ui_element_created)
        self.app.onSystemUIElementRemoved.connect(self._on_close_tab)

    def _on_session_created(self):
        self.emulator = Emulator(self.app.dwarf)
        self._emu_thread = EmulatorThread(self)
        self._emu_thread.onCmdCompleted.connect(self._on_emu_completed)
        self._emu_thread.onError.connect(self._on_emu_error)
        self._emu_thread.emulator = self.emulator

        self.onEmulatorApi.connect(self._on_emulator_api)

        self.app.panels_menu.addSeparator()
        self.app.panels_menu.addAction('Emulator', self.create_widget)

    def _on_session_stopped(self):
        pass

    def _on_receive_cmd(self, args):
        message, data = args
        if 'payload' in message:
            what = message['payload']
            parts = what.split(':::')
            if len(parts) < 2:
                return

            cmd = parts[0]
            if cmd == 'emulator':
                self.onEmulatorApi.emit(parts[1:])

    def _on_emulator_api(self, data):
        if self.emulator and self._emu_thread:
            if not self._emu_thread.isRunning():
                self._emu_thread.cmd = data
                self._emu_thread.start()
            else:
                self._emu_queue.append(data)

    def _on_emu_completed(self, result):
        self.log(result)  # todo: send back to script???
        if self._emu_queue:
            self._emu_thread.cmd = self._emu_queue[0]
            self._emu_queue = self._emu_queue[1:]
            self._emu_thread.start()
        else:
            self._emu_thread.cmd = ''

    def _on_emu_error(self, err_str):
        self.log(err_str)
        if self._emu_queue:
            self._emu_queue.clear()

    def _on_ui_element_created(self, elem, widget):
        if elem == 'console':
            self.console = DwarfConsoleWidget(self.app, has_input=False)
            widget.qtabs.addTab(self.console, 'emulator')
        elif elem == 'registers':
            self.context_widget = widget
            self.emulator_context_widget = EmulatorContextList(self.context_widget)
            self.context_widget.addTab(self.emulator_context_widget, 'emulator')

    def _on_close_tab(self, tab_name):
        if tab_name == 'emulator':
            self.emulator_panel = None

    def create_widget(self):
        if self.emulator_panel is not None:
            return self.emulator_panel

        from plugins.ucdwarf.src.panel_emulator import EmulatorPanel
        self.emulator_panel = EmulatorPanel(self)
        self.app.main_tabs.addTab(self.emulator_panel, 'Emulator')
        self.app.main_tabs.setCurrentIndex(self.app.main_tabs.indexOf(self.emulator_panel))
        return self.emulator_panel

    def log(self, what):
        self.console.log(str(what))
