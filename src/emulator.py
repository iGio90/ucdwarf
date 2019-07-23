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
import binascii

import capstone
import unicorn

from capstone import (Cs, CS_ARCH_ARM, CS_ARCH_ARM64, CS_ARCH_X86, CS_MODE_32,
                      CS_MODE_64, CS_MODE_ARM, CS_MODE_THUMB,
                      CS_MODE_LITTLE_ENDIAN)
from importlib._bootstrap import spec_from_loader, module_from_spec
from importlib._bootstrap_external import SourceFileLoader
from lib import utils
from lib.types.instruction import Instruction
from lib.prefs import Prefs
from lib.types.range import Range
from PyQt5.QtCore import pyqtSignal, QThread

from plugins.ucdwarf.src.emulator_context import EmulatorContext

VFP = "4ff4700001ee500fbff36f8f4ff08043e8ee103a"


STEP_MODE_NONE = 0
STEP_MODE_SINGLE = 1
STEP_MODE_FUNCTION = 2
STEP_MODE_JUMP = 3


class EmulatorThread(QThread):
    onCmdCompleted = pyqtSignal(str, name='onCmdCompleted')
    onError = pyqtSignal(str, name='onError')

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.emulator = None
        self.cmd = ''

    def run(self):
        if self.emulator and self.cmd:
            try:
                result = self.emulator.api(self.cmd)
                self.onCmdCompleted.emit(str(result))
            except Emulator.EmulatorSetupFailedError as error:
                result = False
                self.onError.emit(str(error))
            except Emulator.EmulatorAlreadyRunningError as error:
                result = False
                self.onError.emit(str(error))


class Emulator(QThread):
    class EmulatorSetupFailedError(Exception):
        """ Setup Failed
        """

    class EmulatorAlreadyRunningError(Exception):
        """ isrunning
        """

    onEmulatorSetup = pyqtSignal(list, name='onEmulatorSetup')
    onEmulatorStart = pyqtSignal(name='onEmulatorStart')
    onEmulatorStop = pyqtSignal(name='onEmulatorStop')
    onEmulatorStep = pyqtSignal(name='onEmulatorStep')
    onEmulatorHook = pyqtSignal(Instruction, name='onEmulatorHook')
    onEmulatorMemoryHook = pyqtSignal(list, name='onEmulatorMemoryHook')
    onEmulatorMemoryRangeMapped = pyqtSignal(
        list, name='onEmulatorMemoryRangeMapped')
    onEmulatorLog = pyqtSignal(str, name='onEmulatorLog')

    # setup errors
    ERR_INVALID_TID = 1
    ERR_INVALID_CONTEXT = 2
    ERR_SETUP_FAILED = 3

    def __init__(self, dwarf):
        super(Emulator, self).__init__()

        self.setTerminationEnabled(True)
        self.dwarf = dwarf
        self._prefs = Prefs()

        self._setup_done = False
        self._blacklist_regs = []

        self.cs = None
        self.uc = None

        self.context = None
        self.thumb = False
        self.end_ptr = 0
        self.step_mode = STEP_MODE_NONE

        self.current_context = None

        self._current_instruction = 0
        self._next_instruction = 0
        self._current_cpu_mode = 0

        self._request_stop = False

        # configurations
        self.callbacks_path = None
        self.callbacks = None
        self.instructions_delay = 0

        self._start_address = 0
        self._end_address = 0

        # prevent emulator loop for any reason
        # i.e through custom callback
        # we don't want any UI freeze, so we just setup a n00b way to check if we are looping
        # inside the same instruction for N times.
        # notice that when an unmapped memory region is required during emulation, this will be taken from target proc
        # and mapped into unicorn context. Later, the code fallback to execute the same instruction once again
        self._anti_loop = 0

        # reset single instance preferences
        from plugins.ucdwarf.plugin import EMULATOR_CALLBACKS_PATH
        self._prefs.put(EMULATOR_CALLBACKS_PATH, '')

    def setup_arm(self):
        self.thumb = self.context.pc.thumb
        if self.thumb:
            self._current_cpu_mode = unicorn.UC_MODE_THUMB
            self.cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
            self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_THUMB)
            # Enable VFP instr
            self.uc.mem_map(0x1000, 1024)
            self.uc.mem_write(0x1000, binascii.unhexlify(VFP))
            self.uc.emu_start(0x1000 | 1, 0x1000 + len(VFP))
            self.uc.mem_unmap(0x1000, 1024)
        else:
            self.cs = Cs(CS_ARCH_ARM, CS_MODE_ARM)
            self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM, unicorn.UC_MODE_ARM)
            self._current_cpu_mode = unicorn.UC_MODE_ARM

    def setup_arm64(self):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_LITTLE_ENDIAN)
        self.cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
        self._current_cpu_mode = unicorn.UC_MODE_LITTLE_ENDIAN

    def setup_x86(self):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_32)
        self.cs = Cs(CS_ARCH_X86, CS_MODE_32)

    def setup_x64(self):
        self.uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_64)
        self.cs = Cs(CS_ARCH_X86, CS_MODE_64)

    def _setup(self, user_arch=None, user_mode=None, cs_arch=None, cs_mode=None):
        if user_arch is not None and user_mode is not None:
            try:
                self.uc = unicorn.Uc(user_arch, user_mode)
                self.cs = Cs(cs_arch, cs_mode)

                self.thumb = user_mode == unicorn.UC_MODE_THUMB
            except:
                raise self.EmulatorSetupFailedError('Unsupported arch')
        else:
            if self.dwarf.arch == 'arm':
                self.setup_arm()
            elif self.dwarf.arch == 'arm64':
                self.setup_arm64()
            elif self.dwarf.arch == 'ia32':
                self.setup_x86()
            elif self.dwarf.arch == 'x64':
                self.setup_x64()
            else:
                # unsupported arch
                raise self.EmulatorSetupFailedError('Unsupported arch')

        if not self.uc or not self.cs:
            raise self.EmulatorSetupFailedError('Unicorn or Capstone missing')

        # enable capstone details
        if self.cs is not None:
            self.cs.detail = True

        if not self.context.is_native_context:
            raise self.EmulatorSetupFailedError('Cannot run emulator on non-native context')

        err = self.map_range(self.context.pc.value)
        if err:
            raise self.EmulatorSetupFailedError('Mapping failed')

        self.current_context = EmulatorContext(self.dwarf)
        for reg in self.current_context._unicorn_registers:
            if reg in self.context.__dict__:
                if reg not in self._blacklist_regs:
                    self.uc.reg_write(self.current_context._unicorn_registers[reg], self.context.__dict__[reg].value)

        self.uc.hook_add(unicorn.UC_HOOK_CODE, self.hook_code)
        self.uc.hook_add(unicorn.UC_HOOK_MEM_WRITE | unicorn.UC_HOOK_MEM_READ,
                         self.hook_mem_access)
        self.uc.hook_add(
            unicorn.UC_HOOK_MEM_FETCH_UNMAPPED |
            unicorn.UC_HOOK_MEM_WRITE_UNMAPPED |
            unicorn.UC_HOOK_MEM_READ_UNMAPPED, self.hook_unmapped)
        self.current_context.set_context(self.uc)
        return 0

    def run(self):
        # dont call this func
        if not self._setup_done:
            return
        try:
            if self.thumb and self._start_address % 2 != 1:
                self._start_address += 1
            self.uc.emu_start(self._start_address, 0xffffffffffffffff)  # end is handled in hook_code
        except unicorn.UcError as e:
            self.log_to_ui('[*] error: ' + str(e))
        except Exception as e:
            self.log_to_ui('[*] error: ' + str(e))

        self._setup_done = False
        self.onEmulatorStop.emit()

    def api(self, parts):
        """
        expose api to js side for allowing emulator interaction while scripting
        :param parts: arr -> cmd api split by ":::"
        :return: the result from the api
        """
        cmd = parts[0]
        if cmd == 'clean':
            return self.clean()
        elif cmd == 'setup':
            custom_uc_arch = None
            custom_cs_arch = None
            custom_uc_mode = None
            custom_cs_mode = None
            if len(parts) > 3:
                try:
                    arch = 'UC_ARCH_' + parts[2].upper()
                    if arch in unicorn.__dict__:
                        custom_uc_arch = unicorn.__dict__[arch]
                        arch = 'CS_ARCH_' + parts[2].upper()
                        custom_cs_arch = capstone.__dict__[arch]
                    mode = 'UC_MODE_' + parts[3].upper()
                    if mode in unicorn.__dict__:
                        custom_uc_mode = unicorn.__dict__[mode]
                        mode = 'CS_MODE_' + parts[3].upper()
                        custom_cs_mode = capstone.__dict__[mode]
                except:
                    custom_uc_arch = None
                    custom_cs_arch = None
                    custom_uc_mode = None
                    custom_cs_mode = None

            if custom_uc_arch is not None and custom_uc_mode is not None:
                err = self.setup(
                    parts[1], user_arch=custom_uc_arch, user_mode= custom_uc_mode,
                    cs_arch=custom_cs_arch, cs_mode=custom_cs_mode)
            else:
                err = self.setup(parts[1])
            if err > 0:
                self.context = None
            return err
        elif cmd == 'start':
            until = 0
            if len(parts) > 1:
                try:
                    until = int(parts[1])
                except:
                    pass
            return self.emulate(until=until)
        elif cmd == 'step':
            step_mode = STEP_MODE_SINGLE
            if len(parts) > 1:
                try:
                    step_mode = int(parts[1])
                except:
                    pass
            return self.emulate(step_mode=step_mode)

    def clean(self):
        if self.isRunning():
            raise self.EmulatorAlreadyRunningError()

        self._current_instruction = 0
        self._next_instruction = 0
        self._current_cpu_mode = 0
        self.context = None
        return 0

    def hook_code(self, uc, address, size, user_data):
        # QApplication.processEvents()
        if self._request_stop:
            self.log_to_ui('Error: Emulator stopped - reached end')
            self.stop()
            return

        # anti loop checks
        if self._anti_loop == address:
            self.log_to_ui('Error: Emulator stopped - looping')
            self.stop()
            return

        self._current_instruction = address

        # check if pc/eip is end_ptr
        pc = 0  # address should be pc too ???
        if self.dwarf.arch == 'arm':
            pc = uc.reg_read(unicorn.arm_const.UC_ARM_REG_PC)
        elif self.dwarf.arch == 'arm64':
            pc = uc.reg_read(unicorn.arm64_const.UC_ARM64_REG_PC)
        elif self.dwarf.arch == 'ia32':
            pc = uc.reg_read(unicorn.x86_const.UC_X86_REG_EIP)
        elif self.dwarf.arch == 'x64':
            pc = uc.reg_read(unicorn.x86_const.UC_X86_REG_RIP)

        if self.thumb:
            pc = pc | 1

        if pc == self._end_address:
            self._request_stop = True

        # set the current context
        self.current_context.set_context(uc)

        instruction = None
        try:
            try:
                data = bytes(uc.mem_read(address, size))
                assembly = self.cs.disasm(data, address)
            except:
                self.log_to_ui('Error: Emulator stopped - disasm')
                self.stop()
                return

            for i in assembly:
                # QApplication.processEvents()

                instruction = Instruction(self.dwarf, i, context=self.current_context)

                self.onEmulatorHook.emit(instruction)
                if self.callbacks is not None:
                    try:
                        self.callbacks.hook_code(self, instruction, address, size)
                    except:
                        # hook code not implemented in callbacks
                        pass

                if not instruction.is_jump and not instruction.is_call:
                    self._next_instruction = address + i.size
                else:
                    if instruction.is_call:
                        self._next_instruction = instruction.call_address
                    elif instruction.is_jump:
                        self._next_instruction = instruction.jump_address

                    if instruction.should_change_arm_instruction_set:
                        if self.thumb:
                            self._current_cpu_mode = unicorn.UC_MODE_ARM
                            self.thumb = False
                        else:
                            self._current_cpu_mode = unicorn.UC_MODE_THUMB
                            self.thumb = True
                        self.cs.mode(self._current_cpu_mode)
                break

            # time.sleep(self.instructions_delay)
        except:
            self.log_to_ui('Error: Emulator stopped')
            self.stop()
            return

        if self.step_mode != STEP_MODE_NONE:
            if self.step_mode == STEP_MODE_SINGLE:
                self.stop()
            elif self.step_mode == STEP_MODE_FUNCTION:
                if instruction is not None and instruction.is_call:
                    self.stop()
            elif self.step_mode == STEP_MODE_JUMP:
                if instruction is not None and instruction.is_jump:
                    self.stop()

    def hook_mem_access(self, uc, access, address, size, value, user_data):
        v = value
        if access == unicorn.UC_MEM_READ:
            v = int.from_bytes(uc.mem_read(address, size), 'little')
        self.onEmulatorMemoryHook.emit([uc, access, address, v])
        if self.callbacks is not None:
            try:
                self.callbacks.hook_memory_access(self, access, address, size, v)
            except:
                # hook code not implemented in callbacks
                pass

    def hook_unmapped(self, uc, access, address, size, value, user_data):
        self.log_to_ui(
            "[*] Trying to access an unmapped memory address at 0x%x" %
            address)
        err = self.map_range(address)
        if err > 0:
            self.log_to_ui(
                '[*] Error %d mapping range at %s' % (err, hex(address)))
            return False
        return True

    def invalidate_configurations(self):
        from plugins.ucdwarf.plugin import EMULATOR_CALLBACKS_PATH, EMULATOR_INSTRUCTIONS_DELAY
        self.callbacks_path = self._prefs.get(EMULATOR_CALLBACKS_PATH, '')
        self.instructions_delay = self._prefs.get(EMULATOR_INSTRUCTIONS_DELAY, 0)

    def map_range(self, address):
        Range.build_or_get(self.dwarf, address, cb=self.on_memory_read)
        return 0

    def on_memory_read(self, dwarf_range):
        try:
            self.uc.mem_map(dwarf_range.base, dwarf_range.size)
        except Exception as e:
            self.dwarf.log(e)
            return 301

        try:
            self.uc.mem_write(dwarf_range.base, dwarf_range.data)
        except Exception as e:
            self.dwarf.log(e)
            return 302

        self.log_to_ui("[*] Mapped %d at 0x%x" % (dwarf_range.size, dwarf_range.base))
        self.onEmulatorMemoryRangeMapped.emit([dwarf_range.base, dwarf_range.size])

    def setup(self, tid=0, user_arch=None, user_mode=None, cs_arch=None, cs_mode=None):
        if tid == 0:
            # get current context tid if none provided
            tid = self.dwarf.context_tid

        # make sure it's int < pp: why make sure its int and then using str(tid) later??
        #                       when calling from api its str
        if isinstance(tid, str):
            try:
                tid = int(tid)
            except ValueError:
                return self.ERR_INVALID_TID

        if not isinstance(tid, int):
            return self.ERR_INVALID_TID

        self.context = None
        if str(tid) in self.dwarf.contexts:
            self.context = self.dwarf.contexts[str(tid)]

        if tid == 0 or self.context is None or not self.context.is_native_context:
            # prevent emulation if out-of-context
            return self.ERR_INVALID_CONTEXT

        try:
            self._setup(user_arch=user_arch, user_mode=user_mode, cs_arch=cs_arch, cs_mode=cs_mode)
            self.onEmulatorSetup.emit([user_arch, user_mode])
        except self.EmulatorSetupFailedError:
            return self.ERR_SETUP_FAILED
        return 0

    def start(self, priority=QThread.HighPriority):
        # dont call this func
        if not self._setup_done:
            return
        return super().start(priority=priority)

    def emulate(self, until=0, step_mode=STEP_MODE_NONE, user_arch=None, user_mode=None, cs_arch=None, cs_mode=None):
        if self.isRunning():
            raise self.EmulatorAlreadyRunningError()

        if isinstance(until, str):
            try:
                until = int(until, 16)
            except ValueError:
                until = 0

        if until and isinstance(until, int):
            self.end_ptr = utils.parse_ptr(until)
            if self.end_ptr == 0:
                # invalid end pointer
                raise self.EmulatorSetupFailedError('Invalid EndPtr')

        if self.context is None:
            err = self.setup(user_arch=user_arch, user_mode=user_mode, cs_arch=cs_arch, cs_mode=cs_mode)
            if err > 0:
                # make sure context is None if setup failed for any reason. we want a clean setup later
                self.context = None

                err_msg = 'unhandled error'
                if err == self.ERR_INVALID_TID:
                    err_msg = 'invalid thread id'
                elif err == self.ERR_INVALID_CONTEXT:
                    err_msg = 'invalid context'
                raise self.EmulatorSetupFailedError('Setup failed: %s' % err_msg)

        # calculate the start address
        address = self._next_instruction
        if address == 0:
            if self.uc._arch == unicorn.UC_ARCH_ARM:
                address = self.uc.reg_read(unicorn.arm_const.UC_ARM_REG_PC)
            elif self.uc._arch == unicorn.UC_ARCH_ARM64:
                address = self.uc.reg_read(unicorn.arm64_const.UC_ARM64_REG_PC)
            elif self.uc._arch == unicorn.UC_ARCH_X86 and self.uc._mode == unicorn.UC_MODE_32:
                address = self.uc.reg_read(unicorn.x86_const.UC_X86_REG_EIP)
            elif self.uc._arch == unicorn.UC_ARCH_X86 and self.uc._mode == unicorn.UC_MODE_64:
                address = self.uc.reg_read(unicorn.x86_const.UC_X86_REG_RIP)
            else:
                raise self.EmulatorSetupFailedError('Unsupported arch')

        if until > 0:
            self.log_to_ui('[*] start emulation from %s to %s' % (hex(address), hex(self.end_ptr)))
        else:
            if step_mode == STEP_MODE_NONE or step_mode == STEP_MODE_SINGLE:
                self.log_to_ui('[*] stepping %s' % hex(address))
            elif step_mode == STEP_MODE_FUNCTION:
                self.log_to_ui('[*] stepping to next function call')
            elif step_mode == STEP_MODE_JUMP:
                self.log_to_ui('[*] stepping to next jump')
        self.onEmulatorStart.emit()

        # invalidate prefs before start
        self.invalidate_configurations()

        # load callbacks if needed
        if self.callbacks_path is not None and self.callbacks_path != '':
            try:
                spec = spec_from_loader(
                    "callbacks",
                    SourceFileLoader("callbacks", self.callbacks_path))
                self.callbacks = module_from_spec(spec)
                spec.loader.exec_module(self.callbacks)
            except Exception as e:
                self.log_to_ui('[*] failed to load callbacks: %s' % str(e))
                # reset callbacks path
                from plugins.ucdwarf.plugin import EMULATOR_CALLBACKS_PATH
                self._prefs.put(EMULATOR_CALLBACKS_PATH, '')
                self.callbacks_path = ''
                self.callbacks = None
        else:
            self.callbacks = None

        # until is 0 (i.e we are stepping)
        if until == 0 and step_mode == STEP_MODE_NONE:
            self.step_mode = STEP_MODE_SINGLE
        else:
            self.step_mode = step_mode

        self._start_address = address
        if self.thumb:
            if self._start_address % 2 == 0:
                self._start_address = self._start_address | 1
        else:
            if self._start_address % 2 != 0:
                self._start_address -= 1
        self._end_address = self.end_ptr
        self._setup_done = True
        self.start()

    def stop(self):
        if self.isRunning():
            self.uc.emu_stop()

    def log_to_ui(self, what):
        self.onEmulatorLog.emit(what)
