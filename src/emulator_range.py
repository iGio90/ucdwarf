class EmulatorRange:
    def __init__(self, base, size):
        self.base = base
        self.size = size
        self.data = bytes()

    def read_data(self, dwarf):
        uc = dwarf.get_emulator().uc
        if uc is not None:
            self.data = uc.mem_read(self.base, self.size)
