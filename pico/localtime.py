"""Civil time arithmetic with no datetime module.

MicroPython has no ``datetime`` and no zoneinfo, and the RTC after an NTP sync
holds UTC. This module turns a UTC calendar tuple into local wall-clock time
for a zone described by a standard-time offset and, optionally, the United
States daylight-saving rule (second Sunday in March to first Sunday in
November, switching at 02:00 local).

Everything here is pure arithmetic on integers so it runs identically under
CPython, which is where the tests live.
"""


def days_from_civil(y, m, d):
    """Days since 1970-01-01 for a proleptic Gregorian date."""
    y -= m <= 2
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    """Inverse of days_from_civil: (year, month, day)."""
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return (y + (m <= 2), m, d)


def weekday(y, m, d):
    """0 = Sunday ... 6 = Saturday."""
    return (days_from_civil(y, m, d) + 4) % 7


def nth_sunday(y, m, n):
    """Day of month of the n-th Sunday (n >= 1) in the given month."""
    first = (7 - weekday(y, m, 1)) % 7 + 1
    return first + 7 * (n - 1)


def us_dst_active(y, m, d, minute_of_day):
    """Whether US daylight saving is in effect at a *standard-time* instant.

    DST starts at 02:00 standard time on the second Sunday of March and ends
    at 02:00 daylight time, which is 01:00 standard time, on the first Sunday
    of November. Comparing in standard time keeps the rule free of the
    skipped and repeated hours.
    """
    if m < 3 or m > 11:
        return False
    if 3 < m < 11:
        return True
    if m == 3:
        start = nth_sunday(y, 3, 2)
        return d > start or (d == start and minute_of_day >= 120)
    end = nth_sunday(y, 11, 1)
    return d < end or (d == end and minute_of_day < 60)


def to_local(utc, std_offset_minutes, us_dst=False):
    """Convert a UTC (year, month, day, hour, minute, ...) tuple to local time.

    Returns (year, month, day, hour, minute). ``std_offset_minutes`` is the
    zone's standard-time offset from UTC (Pacific is -480). With ``us_dst``
    the US rule adds an hour while daylight saving is in effect.
    """
    y, mo, d, h, mi = utc[0], utc[1], utc[2], utc[3], utc[4]
    total = days_from_civil(y, mo, d) * 1440 + h * 60 + mi + std_offset_minutes
    ly, lm, ld = civil_from_days(total // 1440)
    mod = total % 1440
    if us_dst and us_dst_active(ly, lm, ld, mod):
        total += 60
        ly, lm, ld = civil_from_days(total // 1440)
        mod = total % 1440
    return (ly, lm, ld, mod // 60, mod % 60)


def minute_of_day(local):
    """Minutes since local midnight for a tuple from to_local()."""
    return local[3] * 60 + local[4]
