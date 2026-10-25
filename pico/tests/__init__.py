"""Desktop tests for the pure modules. Run from the repo root:

    python3 -m unittest discover -s pico/tests -t pico

Modules are imported flat, as they are on the device.
"""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)                    # fakes
sys.path.insert(0, os.path.dirname(_here))  # the firmware modules, flat as on the device
