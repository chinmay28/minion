"""Reading HomeAPI responses.

HomeAPI (https://github.com/chinmay28/HomeAPI) is a key-value store. A
single-entry response is the full record and the datum is its ``value``. A
stored value that is itself JSON comes back as-is, so the quotes entry is a
bare object, while a plain-text value is wrapped as ``{"data": "..."}``, which
is how the sum arrives. These helpers take the decoded JSON document and never
raise: a shape that does not match reads as missing, because the device runs
unattended and an ``N/A`` on the panel beats a crash.
"""

NA = "N/A"


def url_for(base, key):
    """``{base}/{key}``, tolerant of a trailing slash on the base."""
    return base.rstrip("/") + "/" + key


def parse_quotes(doc):
    """The quotes object: symbol -> price string, plus ``timestamp``.

    Values are coerced to str so a numeric publisher and the legacy string
    publisher render the same. An unusable document returns {} and callers
    treat that as "server unreachable".
    """
    if not isinstance(doc, dict):
        return {}
    value = doc.get("value")
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


def parse_text_value(doc):
    """A plain-text entry's value, or None when it is not there."""
    if not isinstance(doc, dict):
        return None
    value = doc.get("value")
    if isinstance(value, dict):
        value = value.get("data")
    if value is None or isinstance(value, (dict, list)):
        return None
    return str(value)


def ratio(a, b):
    """``a / b`` to two decimals as a string, or ``N/A``."""
    try:
        return "%.2f" % (float(a) / float(b))
    except (TypeError, ValueError, ZeroDivisionError):
        return NA
