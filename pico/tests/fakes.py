"""Stand-ins for framebuf objects. Just enough surface for font and layout."""


class FakeFB:
    """Records drawing calls and keeps a pixel grid for the scratch role.

    ``text`` draws a fixed pattern per character so scaling can be checked:
    each glyph lights the pixel at (ord(ch) % 8, 0) and the whole row 7.
    """

    def __init__(self, w=8, h=8):
        self.w, self.h = w, h
        self.grid = [[0] * w for _ in range(h)]
        self.calls = []

    def fill(self, c):
        self.calls.append(("fill", c))
        for row in self.grid:
            for i in range(self.w):
                row[i] = c

    def text(self, s, x, y, c):
        self.calls.append(("text", s, x, y, c))
        for i, ch in enumerate(s):
            gx = x + i * 8
            self._set(gx + ord(ch) % 8, y, c)
            for col in range(8):
                self._set(gx + col, y + 7, c)

    def pixel(self, x, y):
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.grid[y][x]
        return 0

    def fill_rect(self, x, y, w, h, c):
        self.calls.append(("fill_rect", x, y, w, h, c))
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self._set(xx, yy, c)

    def _set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.grid[y][x] = c

    def rects(self):
        return [c for c in self.calls if c[0] == "fill_rect"]
