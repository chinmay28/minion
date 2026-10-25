"""When to refresh, with no clock of our own.

The TPL5110 cuts the Pico's power and re-applies it every ``tick`` minutes,
but a timer resistor is not a calendar: ticks drift and the board has no RTC
across power cuts. So the device keeps a countdown in flash. On most wakes it
decrements the countdown and powers off again within a fraction of a second.
When the countdown reaches zero it refreshes, and, now that it has the time
from the network, counts how many ticks lie between now and the next target
hour and stores that. Each refresh therefore re-anchors the schedule, and the
timer's drift is bounded by half a tick instead of accumulating.
"""


def next_state(stored):
    """Decide what this wake does from the countdown read back from flash.

    ``stored`` is the file's text or None. Returns ``(due, remaining)``:
    ``due`` says whether to refresh now, and when it is False ``remaining`` is
    the new countdown to write back. A missing or unreadable file means
    refresh: the first boot, or a corrupted file, should paint the screen.
    """
    try:
        n = int(stored.strip())
    except (AttributeError, ValueError):
        return True, None
    if n <= 1:
        return True, None
    return False, n - 1


def minutes_until(now, target):
    """Minutes from ``now`` forward to ``target``, both minutes-of-day.

    Always in 1..1440: a target equal to now is a whole day away.
    """
    delta = (target - now) % 1440
    return delta if delta else 1440


def ticks_until_next(now, targets, tick):
    """How many ``tick``-minute wakes until the next refresh target.

    A target closer than half a tick is treated as the one this refresh
    served, since the timer can only land within half a tick of anything
    anyway; the schedule moves on to the following target. The result is
    rounded to the nearest tick and never below 1.
    """
    best = None
    for t in targets:
        delta = minutes_until(now, t)
        if 2 * delta < tick:
            delta += 1440
        if best is None or delta < best:
            best = delta
    if best is None:
        return 1
    ticks = (2 * best + tick) // (2 * tick)
    return ticks if ticks >= 1 else 1


def parse_quote_timestamp(text):
    """Minutes-of-day from the Home API's ``MM/DD HH:MM:SS`` timestamp.

    Returns None for anything that does not parse. This is the fallback clock
    when NTP is unavailable: it is the publish time, not now, so it can be a
    little stale, which the rounding in ticks_until_next absorbs.
    """
    try:
        clock = text.strip().split(" ")[1]
        parts = clock.split(":")
        h, m = int(parts[0]), int(parts[1])
    except (AttributeError, IndexError, ValueError):
        return None
    if not (0 <= h < 24 and 0 <= m < 60):
        return None
    return h * 60 + m
