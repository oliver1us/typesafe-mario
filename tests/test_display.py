from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from typesafe_mario.display import GameWindow, fitted_size


class DisplayTests(unittest.TestCase):
    def test_fitted_size_preserves_aspect_and_fills_available_height(self):
        self.assertEqual(fitted_size((256, 240), (1440, 810)), (864, 810))
        self.assertEqual(fitted_size((256, 240), (800, 600)), (640, 600))
        self.assertEqual(fitted_size((256, 240), (256, 500)), (256, 240))
        for bounds in ((0, 600), (-1, 600)):
            with self.assertRaises(ValueError):
                fitted_size((256, 240), bounds)

    def test_game_window_is_large_resizable_and_handles_quit(self):
        try:
            import numpy as np
            import pygame as pg
        except ImportError:
            self.skipTest("pygame/numpy are optional Mario dependencies")
        with patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"}):
            window = GameWindow()
            try:
                self.assertEqual(window.screen.get_size(), (1440, 810))
                frame = np.full((240, 256, 3), (90, 120, 200), dtype=np.uint8)
                self.assertTrue(window.draw(frame))
                self.assertEqual(tuple(window.screen.get_at((720, 0)))[:3], (90, 120, 200))
                self.assertEqual(tuple(window.screen.get_at((0, 0)))[:3], (15, 17, 21))
                pg.event.post(pg.event.Event(pg.VIDEORESIZE, w=800, h=600, size=(800, 600)))
                self.assertTrue(window.draw(frame))
                self.assertEqual(window.screen.get_size(), (800, 600))
                with self.assertRaises(ValueError):
                    window.draw(np.zeros((240, 256), dtype=np.uint8))
                pg.event.post(pg.event.Event(pg.KEYDOWN, key=pg.K_ESCAPE))
                self.assertFalse(window.draw(frame))
                pg.event.post(pg.event.Event(pg.QUIT))
                self.assertFalse(window.draw(frame))
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
