import unittest

import layout
from fakes import FakeFB

SYMBOLS = {"btc": "BTC-USD", "vti": "VTI", "gld": "GLD", "p": "P", "orcl": "ORCL", "strc": "STRC", "ibit": "IBIT"}
QUOTES = {"BTC-USD": "109432.55", "VTI": "301.20", "GLD": "214.05", "P": "58.41", "ORCL": "190.77",
          "STRC": "98.10", "IBIT": "61.30", "timestamp": "05/23 07:12:03"}


class FormattingTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(layout.money("301.20"), "$301.20")
        self.assertEqual(layout.money("109432.55", as_int=True), "$109,432")
        self.assertEqual(layout.money("N/A"), "N/A")
        self.assertEqual(layout.money(None), "N/A")
        self.assertEqual(layout.money("abc"), "N/A")

    def test_group_thousands(self):
        for n, s in ((0, "0"), (999, "999"), (1000, "1,000"), (1234567, "1,234,567"), (-1234, "-1,234"),
                     (100000000, "100,000,000")):
            self.assertEqual(layout.group_thousands(n), s)

    def test_clock(self):
        self.assertEqual(layout.clock("05/23 07:12:03"), "05/23 07:12")
        self.assertEqual(layout.clock("odd"), "odd")
        self.assertEqual(layout.clock(None), "N/A")


class ViewTest(unittest.TestCase):
    def test_morning_shows_ibit(self):
        v = layout.view_from(QUOTES, "42", 3.214, 7 * 60 + 15, SYMBOLS)
        self.assertEqual(v["alt_label"], "IBIT")
        self.assertEqual(v["alt"], "$61.30")
        self.assertEqual(v["pstg"], "$58.41")
        self.assertEqual(v["v_g"], "1.41")
        self.assertEqual(v["sum"], "42")
        self.assertEqual(v["volts"], "3.21V")
        self.assertEqual(v["clock"], "05/23 07:12")
        self.assertEqual(v["btc"], "$109,432")

    def test_evening_shows_strc(self):
        v = layout.view_from(QUOTES, "42", 3.2, 19 * 60 + 15, SYMBOLS)
        self.assertEqual((v["alt_label"], v["alt"]), ("STRC", "$98.10"))

    def test_unknown_time_is_morning(self):
        self.assertEqual(layout.view_from(QUOTES, "42", 3.2, None, SYMBOLS)["alt_label"], "IBIT")

    def test_missing_everything_is_na(self):
        v = layout.view_from({}, None, None, None, SYMBOLS)
        for k in ("btc", "vti", "gld", "pstg", "orcl", "v_g", "p_v", "o_v", "alt", "sum", "clock", "volts"):
            self.assertEqual(v[k], "N/A", k)


class ComposeTest(unittest.TestCase):
    def views(self):
        yield layout.view_from(QUOTES, "42", 3.21, 7 * 60, SYMBOLS)
        yield layout.view_from({}, None, None, None, SYMBOLS)
        # Wide values: a nine-figure sum, a seven-figure BTC, four-figure prices.
        wide = dict(QUOTES, **{"BTC-USD": "1234567.89", "VTI": "1301.20", "GLD": "9214.05",
                               "P": "1058.41", "ORCL": "1190.77", "STRC": "1098.10"})
        yield layout.view_from(wide, "100,000,000", 3.6, 20 * 60, SYMBOLS)

    def test_every_view_validates(self):
        for y0 in (6, 0):
            for view in self.views():
                ops = layout.compose(view, y0)
                layout.validate(ops, y0)

    def test_uses_both_planes(self):
        planes = {op[1] for op in layout.compose(next(self.views()))}
        self.assertEqual(planes, {layout.BLACK, layout.RED})

    def test_validate_catches_overflow(self):
        ops = [("text", layout.BLACK, "x" * 40, 0, 10, 1, 1, layout.INK)]
        with self.assertRaisesRegex(ValueError, "right edge"):
            layout.validate(ops)

    def test_validate_catches_hidden_rows(self):
        with self.assertRaisesRegex(ValueError, "visible rows"):
            layout.validate([("text", layout.BLACK, "x", 0, 0, 1, 1, layout.INK)], 6)
        with self.assertRaisesRegex(ValueError, "visible rows"):
            layout.validate([("rect", layout.BLACK, 0, 120, 10, 10, layout.INK)], 6)

    def test_validate_catches_red_on_black(self):
        ops = [("rect", layout.BLACK, 0, 6, 250, 20, layout.INK),
               ("text", layout.RED, "no", 4, 8, 1, 1, layout.INK)]
        with self.assertRaisesRegex(ValueError, "red text over a black bar"):
            layout.validate(ops)


class RenderTest(unittest.TestCase):
    def test_dispatches_to_planes(self):
        black, red, scratch = FakeFB(250, 128), FakeFB(250, 128), FakeFB()
        ops = [("rect", layout.BLACK, 0, 6, 250, 20, layout.INK),
               ("text", layout.BLACK, "Hi", 4, 8, 2, 2, layout.PAPER),
               ("text", layout.RED, "V/G", 4, 70, 1, 1, layout.INK)]
        layout.render(ops, black, red, scratch)
        self.assertIn(("fill_rect", 0, 6, 250, 20, 0), black.calls)
        self.assertTrue(any(c[0] == "fill_rect" and c[5] == 1 for c in black.calls))
        self.assertEqual(red.calls, [("text", "V/G", 4, 70, 0)])


if __name__ == "__main__":
    unittest.main()
