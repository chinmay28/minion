"""Text on a framebuf, at integer scales.

MicroPython's ``framebuf.FrameBuffer.text`` draws its built-in 8x8 font and
nothing else. To get a header that is readable from across the room we render
each character into an 8x8 scratch buffer and copy it out pixel by pixel as
``sx`` by ``sy`` blocks. Separate horizontal and vertical scales matter on a
250-pixel-wide panel: a 1x2 glyph is as tall as a 2x2 one but fits twice as
many characters on a line.

``fb`` and ``scratch`` only need ``text``, ``fill``, ``pixel`` and
``fill_rect``, so the tests drive this with fakes.
"""

GLYPH = 8


def text_width(s, sx=1):
    """Pixels a string occupies at horizontal scale ``sx``."""
    return GLYPH * len(s) * sx


def text_height(sy=1):
    return GLYPH * sy


def draw_text(fb, s, x, y, color, sx=1, sy=1, scratch=None):
    """Draw ``s`` with its top-left corner at (x, y) in ``color``.

    At 1x1 this is the native ``text`` call. At any other scale ``scratch``
    must be an 8x8 framebuf; each glyph is rendered there as 1-on-0 and the
    set pixels become ``sx`` by ``sy`` rectangles of ``color`` on ``fb``.
    """
    if sx == 1 and sy == 1:
        fb.text(s, x, y, color)
        return
    if scratch is None:
        raise ValueError("scaled text needs an 8x8 scratch framebuf")
    cx = x
    for ch in s:
        scratch.fill(0)
        scratch.text(ch, 0, 0, 1)
        for row in range(GLYPH):
            py = y + row * sy
            col = 0
            while col < GLYPH:
                if scratch.pixel(col, row):
                    # Merge a run of set pixels into one rectangle.
                    run = 1
                    while col + run < GLYPH and scratch.pixel(col + run, row):
                        run += 1
                    fb.fill_rect(cx + col * sx, py, run * sx, sy, color)
                    col += run
                else:
                    col += 1
        cx += GLYPH * sx
