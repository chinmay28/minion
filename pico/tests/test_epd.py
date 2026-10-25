import unittest

import epd2in13b_v4 as epd


class GeometryTest(unittest.TestCase):
    def test_padded_width(self):
        self.assertEqual(epd.padded_width(122), 128)
        self.assertEqual(epd.padded_width(128), 128)
        self.assertEqual(epd.padded_width(8), 8)


class LandscapeBytesTest(unittest.TestCase):
    def test_reverses_band_order(self):
        buf = bytearray(b"abcdef")
        self.assertEqual(epd.landscape_bytes(buf, 2, 3), bytearray(b"defabc"))

    def test_single_band_is_identity(self):
        self.assertEqual(epd.landscape_bytes(bytearray(b"xyz"), 1, 3), bytearray(b"xyz"))

    def test_full_panel_size_and_mapping(self):
        bands, band_len = 16, 250
        buf = bytearray(i % 256 for i in range(bands * band_len))
        out = epd.landscape_bytes(buf, bands, band_len)
        self.assertEqual(len(out), 4000)
        # First band out is the last band in.
        self.assertEqual(out[:band_len], buf[15 * band_len:16 * band_len])
        self.assertEqual(out[-band_len:], buf[:band_len])


if __name__ == "__main__":
    unittest.main()
