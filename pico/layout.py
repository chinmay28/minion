"""What the panel shows, as data.

``compose`` turns the fetched values into a list of drawing operations, and
``validate`` checks that list against the panel's geometry: nothing runs off
the right edge, nothing lands in the rows the panel cannot show, and no red
text sits on a black bar (the tri-color controller cannot draw red over
black, it comes out as black). ``render`` is the only part that touches a
framebuffer, so the layout itself is tested under CPython with no hardware.

Geometry: the 2.13" B is 250 x 122, but in landscape the framebuffer is
250 x 128 because the controller's RAM is padded to whole bytes. The six
spare rows sit at the top of the framebuffer, so visible rows are
``y0 .. y0 + 122`` with ``y0 = 6``. That value is empirical; if a build shows
the gap at the bottom instead, set ``VISIBLE_Y0 = 0`` in config.
"""

import font
from homeapi import NA, ratio

WIDTH = 250
VISIBLE_H = 122
FB_H = 128

BLACK = "black"   # the black/white plane
RED = "red"       # the red plane
INK = 0           # pixel value that shows colour on either plane
PAPER = 1         # pixel value that stays white (or, on a black bar, white text)

MARGIN = 4

# Operations are plain tuples so they are cheap to build on the device and
# trivial to assert on in tests.
#   ("rect", plane, x, y, w, h, color)
#   ("text", plane, s, x, y, sx, sy, color)


def money(value, as_int=False):
    """``$301.20`` for a price string, ``$109,432`` with as_int, or ``N/A``."""
    if value is None or value == NA:
        return NA
    try:
        if as_int:
            return "$" + group_thousands(int(float(value)))
        float(value)
        return "$" + str(value)
    except (TypeError, ValueError):
        return NA


def group_thousands(n):
    """``1234567`` -> ``1,234,567``. MicroPython's format() has no ``,``."""
    sign = "-" if n < 0 else ""
    digits = str(abs(n))
    out = ""
    while len(digits) > 3:
        out = "," + digits[-3:] + out
        digits = digits[:-3]
    return sign + digits + out


def clock(timestamp):
    """``05/23 07:12`` from the API's ``05/23 07:12:03``; the input otherwise."""
    if not timestamp:
        return NA
    parts = timestamp.split(" ")
    if len(parts) == 2 and parts[1].count(":") == 2:
        return parts[0] + " " + parts[1][:5]
    return timestamp


def view_from(quotes, sum_text, volts, now_minutes, symbols):
    """Flatten fetched data into the strings the layout draws.

    ``symbols`` maps roles to Home API keys: btc, vti, gld, p, orcl, strc,
    ibit. The footer alternates like the Pi Zero build did: the morning
    refresh shows IBIT, the evening one STRC. An unknown time counts as
    morning.
    """
    def q(role):
        return quotes.get(symbols[role], NA)

    vti, gld, p, orcl = q("vti"), q("gld"), q("p"), q("orcl")
    evening = now_minutes is not None and now_minutes >= 12 * 60
    alt_role = "strc" if evening else "ibit"
    return {
        "btc": money(q("btc"), as_int=True),
        "vti": money(vti),
        "gld": money(gld),
        "pstg": money(p),
        "orcl": money(orcl),
        "v_g": ratio(vti, gld),
        "p_v": ratio(p, vti),
        "o_v": ratio(orcl, vti),
        "alt_label": alt_role.upper(),
        "alt": money(q(alt_role)),
        "sum": sum_text if sum_text is not None else NA,
        "clock": clock(quotes.get("timestamp")),
        "volts": ("%.2fV" % volts) if volts is not None else NA,
    }


def compose(view, y0=6):
    """Drawing operations for a view dict from view_from()."""
    ops = []
    bottom = y0 + VISIBLE_H

    # Header bar: title and BTC, white on black.
    header_h = 20
    ops.append(("rect", BLACK, 0, y0, WIDTH, header_h, INK))
    ops.append(("text", BLACK, "Minion", MARGIN, y0 + 2, 2, 2, PAPER))
    btc = view["btc"]
    ops.append(("text", BLACK, btc, WIDTH - MARGIN - font.text_width(btc), y0 + 2, 1, 2, PAPER))

    # Two columns of quotes, tall glyphs.
    left, right = MARGIN, WIDTH // 2 + 3
    row1, row2 = y0 + header_h + 4, y0 + header_h + 26
    ops.append(("text", BLACK, "VTI " + view["vti"], left, row1, 1, 2, INK))
    ops.append(("text", BLACK, "GLD " + view["gld"], left, row2, 1, 2, INK))
    ops.append(("text", BLACK, "PSTG " + view["pstg"], right, row1, 1, 2, INK))
    ops.append(("text", BLACK, "ORCL " + view["orcl"], right, row2, 1, 2, INK))

    # Divider, then the ratio strip in red.
    divider_y = row2 + 20
    ops.append(("rect", BLACK, 0, divider_y, WIDTH, 1, INK))
    ratio_y = divider_y + 5
    third = WIDTH // 3
    ops.append(("text", RED, "V/G " + view["v_g"], MARGIN, ratio_y, 1, 1, INK))
    ops.append(("text", RED, "P/V " + view["p_v"], third + MARGIN, ratio_y, 1, 1, INK))
    ops.append(("text", RED, "O/V " + view["o_v"], 2 * third + MARGIN, ratio_y, 1, 1, INK))

    # Footer bar: two centred lines, white on black.
    footer_h = 22
    footer_y = bottom - footer_h
    ops.append(("rect", BLACK, 0, footer_y, WIDTH, footer_h, INK))
    line1 = view["clock"] + "  " + view["alt_label"] + " " + view["alt"]
    line2 = "SUM " + view["sum"] + "  " + view["volts"]
    for i, line in enumerate((line1, line2)):
        x = (WIDTH - font.text_width(line)) // 2
        ops.append(("text", BLACK, line, x if x > MARGIN else MARGIN, footer_y + 2 + i * 10, 1, 1, PAPER))
    return ops


def validate(ops, y0=6):
    """Raise ValueError naming every operation that breaks the panel's rules."""
    problems = []
    bottom = y0 + VISIBLE_H
    bars = [op for op in ops if op[0] == "rect" and op[1] == BLACK and op[6] == INK]
    for op in ops:
        if op[0] == "rect":
            _, plane, x, y, w, h, _ = op
            s = None
        else:
            _, plane, s, x, y, sx, sy, _ = op
            w, h = font.text_width(s, sx), font.text_height(sy)
        label = repr(s) if s is not None else "rect"
        if x < 0 or x + w > WIDTH:
            problems.append("%s runs past the right edge: x=%d w=%d" % (label, x, w))
        if y < y0 or y + h > bottom:
            problems.append("%s leaves the visible rows: y=%d h=%d" % (label, y, h))
        if op[0] == "text" and plane == RED:
            for bar in bars:
                _, _, bx, by, bw, bh, _ = bar
                if x < bx + bw and x + w > bx and y < by + bh and y + h > by:
                    problems.append("%s is red text over a black bar" % label)
                    break
    if problems:
        raise ValueError("; ".join(problems))


def render(ops, black, red, scratch):
    """Execute operations on the two planes (both pre-filled with PAPER)."""
    planes = {BLACK: black, RED: red}
    for op in ops:
        if op[0] == "rect":
            _, plane, x, y, w, h, color = op
            planes[plane].fill_rect(x, y, w, h, color)
        else:
            _, plane, s, x, y, sx, sy, color = op
            font.draw_text(planes[plane], s, x, y, color, sx, sy, scratch)
