import unittest

import homeapi

QUOTES_DOC = {
    "id": 1, "category": "minion", "key": "minion-quotes",
    "value": {"BTC-USD": "109432", "VTI": "301.20", "P": 58.41, "timestamp": "05/23 07:12:03"},
}


class UrlForTest(unittest.TestCase):
    def test_joins(self):
        self.assertEqual(homeapi.url_for("http://h:9999/api/entries", "minion-sum"),
                         "http://h:9999/api/entries/minion-sum")

    def test_trailing_slash(self):
        self.assertEqual(homeapi.url_for("http://h/api/entries/", "k"), "http://h/api/entries/k")


class ParseQuotesTest(unittest.TestCase):
    def test_values_as_strings(self):
        self.assertEqual(homeapi.parse_quotes(QUOTES_DOC),
                         {"BTC-USD": "109432", "VTI": "301.20", "P": "58.41", "timestamp": "05/23 07:12:03"})

    def test_bad_shapes_are_empty(self):
        for bad in (None, [], "x", {}, {"value": "text"}, {"value": {"data": "x"}}["value"]):
            self.assertEqual(homeapi.parse_quotes(bad), {}, repr(bad))

    def test_text_wrapped_value_is_not_quotes(self):
        # A plain-text entry mistakenly stored under the quotes key.
        self.assertEqual(homeapi.parse_quotes({"value": {"data": "oops"}}), {"data": "oops"})


class ParseTextValueTest(unittest.TestCase):
    def test_wrapped_text(self):
        self.assertEqual(homeapi.parse_text_value({"value": {"data": "42"}}), "42")

    def test_bare_scalars(self):
        self.assertEqual(homeapi.parse_text_value({"value": "42"}), "42")
        self.assertEqual(homeapi.parse_text_value({"value": 42}), "42")
        self.assertEqual(homeapi.parse_text_value({"value": {"data": 100000000}}), "100000000")

    def test_missing(self):
        for bad in (None, {}, {"value": None}, {"value": {}}, {"value": {"data": [1]}}, {"value": ["a"]}):
            self.assertIsNone(homeapi.parse_text_value(bad), repr(bad))


class RatioTest(unittest.TestCase):
    def test_two_decimals(self):
        self.assertEqual(homeapi.ratio("301.20", "214.05"), "1.41")
        self.assertEqual(homeapi.ratio(1, 3), "0.33")

    def test_failures_are_na(self):
        self.assertEqual(homeapi.ratio("N/A", "2"), "N/A")
        self.assertEqual(homeapi.ratio("1", "0"), "N/A")
        self.assertEqual(homeapi.ratio(None, "2"), "N/A")


if __name__ == "__main__":
    unittest.main()
