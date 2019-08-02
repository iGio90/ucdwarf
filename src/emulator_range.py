from dwarf.lib.types.range import Range


class EmulatorRange(Range):

    def read_data(self, dwarf):
        uc = dwarf.get_emulator().uc
        if uc is not None:
            self.data = uc.mem_read(self.base, self.size)
