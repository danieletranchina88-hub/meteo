import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import front_character as fch  # noqa: E402
import front_locator as fl  # noqa: E402


class ThermalWindSignTest(unittest.TestCase):
    """A zonal front with warm air to the south must have westerly shear.

    NH thermal wind: V_T is parallel to k x grad T, cold air on the left.
    With grad T pointing south, k x grad T points east.
    """

    def setUp(self):
        self.lon = np.arange(0.0, 20.01, 0.1)
        self.lat = np.arange(35.0, 50.01, 0.1)
        shape = (len(self.lat), len(self.lon))
        self.metrics = fl.grid_metrics(self.lon, self.lat)
        self.weak = np.full(shape, 5.0)
        self.strong = np.full(shape, 20.0)
        self.zero = np.zeros(shape)
        self.line = np.column_stack([np.linspace(3, 17, 40), np.full(40, 42.0)])
        self.warm_south = np.tile([0.0, -1.0], (40, 1))

    def test_balanced_front_aligns(self):
        alignment = fch.thermal_wind_alignment(
            self.line, self.warm_south,
            self.weak, self.zero, self.strong, self.zero,
            self.lon, self.lat, self.metrics,
        )
        self.assertGreater(alignment, 0.9)

    def test_anti_thermal_shear_is_rejected(self):
        alignment = fch.thermal_wind_alignment(
            self.line, self.warm_south,
            self.strong, self.zero, self.weak, self.zero,
            self.lon, self.lat, self.metrics,
        )
        self.assertLess(alignment, -0.9)


if __name__ == "__main__":
    unittest.main()
