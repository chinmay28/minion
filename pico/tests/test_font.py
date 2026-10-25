import unittest

import font
from fakes import FakeFB


class WidthTest(unittest.TestCase):
    def test_width_and_height(self):
        self.assertEqual(font.text_width("Minion"), 48)
        self.assertEqual(font.text_width("Minion", 2), 96)
        self.assertEqual(font.text_height(), 8)
        self.assertEqual(font.text_height(2), 16)


class DrawTest(unittest.TestCase):
    def test_native_at_1x1(self):
        fb = FakeFB(64, 16)
        font.draw_text(fb, "ab", 3, 4, 0)
        self.assertEqual(fb.calls, [("text", "ab", 3, 4, 0)])

    def test_scaled_needs_scratch(self):
        with self.assertRaises(ValueError):
            font.draw_text(FakeFB(64, 16), "a", 0, 0, 0, 2, 2)

    def test_scaled_geometry(self):
        fb, scratch = FakeFB(64, 32), FakeFB()
        font.draw_text(fb, "A", 10, 5, 0, sx=2, sy=3, scratch=scratch)
        rects = fb.rects()
        # The single pixel at (ord('A') % 8 = 1, 0) becomes a 2x3 block.
        self.assertIn(("fill_rect", 10 + 1 * 2, 5, 2, 3, 0), rects)
        # Row 7, all eight pixels, becomes one merged run 16 wide.
        self.assertIn(("fill_rect", 10, 5 + 7 * 3, 16, 3, 0), rects)
        self.assertEqual(len(rects), 2)

    def test_advances_per_character(self):
        fb, scratch = FakeFB(128, 16), FakeFB()
        font.draw_text(fb, "AB", 0, 0, 1, sx=2, sy=2, scratch=scratch)
        rows7 = [r for r in fb.rects() if r[2] == 14]
        self.assertEqual([r[1] for r in rows7], [0, 16])

    def test_colour_is_passed_through(self):
        fb, scratch = FakeFB(64, 16), FakeFB()
        font.draw_text(fb, "A", 0, 0, 1, sx=1, sy=2, scratch=scratch)
        self.assertTrue(all(r[5] == 1 for r in fb.rects()))


if __name__ == "__main__":
    unittest.main()
