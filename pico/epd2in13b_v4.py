# Driver for the Waveshare 2.13" e-Paper Module (B) V4 on a Raspberry Pi Pico,
# landscape, black and red planes.
#
# Derived from Waveshare's Pico_ePaper-2.13-B_V4.py (MIT licence, copyright
# Waveshare team, 2022), trimmed to the landscape class this project uses, with
# three changes:
#   - the busy wait calls an injected ``idle(ms)`` so the application can feed
#     its watchdog and light-sleep the core while the panel refreshes;
#   - ``display`` reorders the two framebuffers once and sends each as a single
#     SPI write instead of 8,000 one-byte transfers;
#   - no ``print`` chatter.
# Register sequence and framebuffer geometry are unchanged: they are what makes
# this panel show the right thing, and earlier attempts to "improve" them gave
# mirrored glyphs and all-red screens.

try:
    from machine import Pin, SPI
    import utime
except ImportError:  # CPython, for the tests
    Pin = SPI = utime = None

EPD_WIDTH = 122
EPD_HEIGHT = 250

RST_PIN = 12
DC_PIN = 8
CS_PIN = 9
BUSY_PIN = 13


def padded_width(width=EPD_WIDTH):
    """The controller's RAM row is whole bytes: 122 pixels become 128."""
    return width if width % 8 == 0 else (width // 8) * 8 + 8


def landscape_bytes(buf, bands, band_len):
    """Reorder a MONO_VLSB landscape framebuffer into the controller's RAM order.

    The landscape framebuffer is ``band_len`` pixels wide and ``bands`` byte
    rows tall; the controller wants the byte rows last-to-first. Pure, so it
    is tested on the desktop.
    """
    out = bytearray(len(buf))
    k = 0
    for j in range(bands - 1, -1, -1):
        out[k:k + band_len] = buf[j * band_len:(j + 1) * band_len]
        k += band_len
    return out


class EPD:
    """The panel in landscape: ``black`` and ``red`` are 250 x 128 framebufs.

    Pixel value 1 is white (no ink) on both planes and 0 is ink; fill both with
    1 before drawing. ``idle(ms)`` is called repeatedly while the panel is
    busy; the default just sleeps.
    """

    def __init__(self, idle=None):
        import framebuf
        self.idle = idle or (lambda ms: utime.sleep_ms(ms))
        self.reset_pin = Pin(RST_PIN, Pin.OUT)
        self.busy_pin = Pin(BUSY_PIN, Pin.IN, Pin.PULL_UP)
        self.cs_pin = Pin(CS_PIN, Pin.OUT)
        self.dc_pin = Pin(DC_PIN, Pin.OUT)
        self.width = padded_width()
        self.height = EPD_HEIGHT
        self.spi = SPI(1)
        self.spi.init(baudrate=4000_000)
        size = self.height * self.width // 8
        self.buffer_black = bytearray(size)
        self.buffer_red = bytearray(size)
        self.black = framebuf.FrameBuffer(self.buffer_black, self.height, self.width, framebuf.MONO_VLSB)
        self.red = framebuf.FrameBuffer(self.buffer_red, self.height, self.width, framebuf.MONO_VLSB)
        self.scratch = framebuf.FrameBuffer(bytearray(8), 8, 8, framebuf.MONO_HLSB)
        self.init()

    # --- low level -------------------------------------------------------

    def reset(self):
        self.reset_pin.value(1)
        utime.sleep_ms(50)
        self.reset_pin.value(0)
        utime.sleep_ms(2)
        self.reset_pin.value(1)
        utime.sleep_ms(50)

    def send_command(self, command):
        self.dc_pin.value(0)
        self.cs_pin.value(0)
        self.spi.write(bytearray([command]))
        self.cs_pin.value(1)

    def send_data(self, data):
        self.dc_pin.value(1)
        self.cs_pin.value(0)
        self.spi.write(bytearray([data]))
        self.cs_pin.value(1)

    def send_buffer(self, buf):
        self.dc_pin.value(1)
        self.cs_pin.value(0)
        self.spi.write(buf)
        self.cs_pin.value(1)

    def wait_idle(self):
        while self.busy_pin.value() == 1:
            self.idle(100)
        utime.sleep_ms(20)

    def turn_on_display(self):
        self.send_command(0x20)
        self.wait_idle()

    def set_window(self, xs, ys, xe, ye):
        self.send_command(0x44)
        self.send_data((xs >> 3) & 0xFF)
        self.send_data((xe >> 3) & 0xFF)
        self.send_command(0x45)
        self.send_data(ys & 0xFF)
        self.send_data((ys >> 8) & 0xFF)
        self.send_data(ye & 0xFF)
        self.send_data((ye >> 8) & 0xFF)

    def set_cursor(self, x, y):
        self.send_command(0x4E)
        self.send_data(x & 0xFF)
        self.send_command(0x4F)
        self.send_data(y & 0xFF)
        self.send_data((y >> 8) & 0xFF)

    # --- panel ------------------------------------------------------------

    def init(self):
        self.reset()
        self.wait_idle()
        self.send_command(0x12)      # software reset
        self.wait_idle()
        self.send_command(0x01)      # driver output control
        self.send_data(0xF9)
        self.send_data(0x00)
        self.send_data(0x00)
        self.send_command(0x11)      # data entry mode: landscape
        self.send_data(0x07)
        self.set_window(0, 0, self.width - 1, self.height - 1)
        self.set_cursor(0, 0)
        self.send_command(0x3C)      # border waveform
        self.send_data(0x05)
        self.send_command(0x18)      # built-in temperature sensor
        self.send_data(0x80)
        self.send_command(0x21)      # display update control
        self.send_data(0x80)
        self.send_data(0x80)
        self.wait_idle()

    def display(self):
        """Full refresh of both planes. Takes about 15 seconds."""
        bands = self.width // 8
        self.send_command(0x24)
        self.send_buffer(landscape_bytes(self.buffer_black, bands, self.height))
        self.send_command(0x26)
        self.send_buffer(landscape_bytes(self.buffer_red, bands, self.height))
        self.turn_on_display()

    def clear(self):
        size = self.height * self.width // 8
        self.send_command(0x24)
        self.send_buffer(bytearray([0xFF]) * size)
        self.send_command(0x26)
        self.send_buffer(bytearray([0xFF]) * size)
        self.turn_on_display()

    def sleep(self):
        """Deep-sleep the controller and hold it in reset. Call before power-off."""
        self.send_command(0x10)
        self.send_data(0x01)
        utime.sleep_ms(2000)
        self.reset_pin.value(0)
