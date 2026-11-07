from __future__ import annotations

from typing import Any


def fitted_size(source: tuple[int, int], bounds: tuple[int, int]) -> tuple[int, int]:
    """Fit without stretching or cropping; preserve the source aspect ratio."""
    if min(*source, *bounds) < 1:
        raise ValueError("frame and window dimensions must be positive")
    scale = min(bounds[0] / source[0], bounds[1] / source[1])
    return max(1, round(source[0] * scale)), max(1, round(source[1] * scale))


def draw_rgb_frame(pg: Any, screen: Any, frame: Any, bounds: Any) -> tuple[Any, tuple[int, int]]:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError(
            "Graphical displays need numpy. Install the mario extras first."
        ) from exc
    pixels = np.asarray(frame)
    if pixels.ndim != 3 or pixels.shape[2] < 3:
        raise ValueError(f"Expected an RGB frame, received shape {pixels.shape!r}")
    source = pg.surfarray.make_surface(pixels[:, :, :3].swapaxes(0, 1))
    target = pg.Rect((0, 0), fitted_size(source.get_size(), bounds.size))
    target.center = bounds.center
    screen.blit(pg.transform.scale(source, target.size), target.topleft)
    return target, source.get_size()


class GameWindow:
    """Large plain-game viewer; the runner retains its synchronous policy loop."""

    def __init__(self, width: int = 1440, height: int = 810) -> None:
        if width < 1 or height < 1:
            raise ValueError("game dimensions must be positive")
        try:
            import pygame
        except ImportError as exc:
            raise RuntimeError(
                "The game window needs pygame. Install the mario extras first."
            ) from exc
        self.pg = pygame
        pygame.init()
        pygame.display.set_caption("TypeSafe Mario · Esc or Q quits")
        self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()

    def draw(self, frame: Any) -> bool:
        for event in self.pg.event.get():
            if event.type == self.pg.QUIT or (
                event.type == self.pg.KEYDOWN and event.key in (self.pg.K_ESCAPE, self.pg.K_q)
            ):
                return False
            if event.type == self.pg.VIDEORESIZE:
                self.screen = self.pg.display.set_mode(
                    (max(1, event.w), max(1, event.h)), self.pg.RESIZABLE
                )
        self.screen.fill((15, 17, 21))
        if frame is not None:
            draw_rgb_frame(self.pg, self.screen, frame, self.screen.get_rect())
        self.pg.display.flip()
        self.clock.tick(60)
        return True

    def close(self) -> None:
        self.pg.quit()
