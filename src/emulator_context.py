from unicorn import unicorn


class EmulatorContext(object):
    """
    holds emulator context related stuffs
    """

    def __init__(self, dwarf):
        import unicorn

        # map unicorn registers for the correct arch
        if dwarf.arch == 'arm':
            unicorn_consts = unicorn.arm_const
        elif dwarf.arch == 'arm64':
            unicorn_consts = unicorn.arm64_const
        elif dwarf.arch == 'ia32' or dwarf.arch == 'x64':
            unicorn_consts = unicorn.x86_const
        else:
            raise Exception('unsupported arch')

        self._unicorn_registers = {}

        for v in unicorn_consts.__dict__:
            if '_REG_' in v:
                reg = v.lower().split('_')[-1]
                if reg == 'invalid' or reg == 'ending':
                    continue
                self.__dict__[reg] = 0
                self._unicorn_registers[reg] = unicorn_consts.__dict__[v]

    def set_context(self, uc):
        for reg in self._unicorn_registers:
            try:
                self.__dict__[reg] = uc.reg_read(self._unicorn_registers[reg])
            except unicorn.UcError:
                pass
