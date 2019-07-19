from lib.types.range import Range


class EmulatorRange(Range):

    def read_data(self, base, length, require_data=True):
        uc = self.dwarf.get_emulator().uc
        if uc is not None:
            for base, tail, perm in uc.mem_regions():
                if base <= self.start_address <= tail:
                    self.base = base
                    self.tail = tail
                    self.start_offset = self.start_address - self.base
                    self.size = self.tail - self.base
                    break
            if self.base > 0 and require_data:
                # read data
                self.data = uc.mem_read(self.base, self.size)
