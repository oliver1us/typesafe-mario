"""Cheap, view-only counterfactuals, not emulator rollouts or Jev predictions."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .actions import JUMP_ACTIONS, Action
from .state import MarioSnapshot

HORIZON_FRAMES = 45

ACTION_COLORS: dict[Action, tuple[int, int, int]] = {
    Action.NOOP: (185, 194, 207),
    Action.RIGHT: (81, 185, 255),
    Action.RIGHT_JUMP: (255, 213, 92),
    Action.RIGHT_RUN: (87, 220, 149),
    Action.RIGHT_RUN_JUMP: (198, 145, 255),
    Action.JUMP: (255, 157, 79),
    Action.LEFT: (255, 117, 149),
}


@dataclass(frozen=True)
class EstimatedTrajectory:
    action: Action
    # Offsets from Mario's current sprite origin, in source-frame pixels (y down).
    points: tuple[tuple[float, float], ...]
    end_reason: str


def sprite_geometry(snapshot: MarioSnapshot) -> tuple[int, int]:
    """SMB1 uses a 32px player origin; small Mario occupies its lower 16px."""
    return (16, 16) if snapshot.status == "small" else (0, 32)


def estimate_trajectories(
    snapshot: MarioSnapshot,
    actions: Sequence[Action] = tuple(Action),
    *,
    horizon_frames: int = HORIZON_FRAMES,
) -> tuple[EstimatedTrajectory, ...]:
    """Hold each macro once, using coarse tiles, inertia and constant enemy velocity.

    Stop at unknown tiles, solids or possible enemy contact. This intentionally
    does not model stomps, enemy AI, re-jumps, controller edges or safety changes.
    Neither the snapshot nor the real emulator/controller is modified.
    """
    if not 1 <= horizon_frames <= 120:
        raise ValueError("horizon_frames must be between 1 and 120")
    rows = snapshot.local_grid
    mario = next(((r, row.index("M")) for r, row in enumerate(rows) if "M" in row), None)
    if mario is None or snapshot.screen_y is None or snapshot.dead or snapshot.clear:
        return ()
    mario_row, mario_col = mario
    sprite_offset, height = sprite_geometry(snapshot)

    def cell(x: float, y: float) -> str | None:
        col = mario_col + math.floor((snapshot.x % 16 + x) / 16)
        row = mario_row + math.floor((snapshot.screen_y % 16 + sprite_offset + y) / 16)
        return rows[row][col] if 0 <= row < len(rows) and 0 <= col < len(rows[row]) else None

    result = []
    for action in actions:
        x = y = 0.0
        vx = max(-3.5, min(3.5, float(snapshot.dx)))
        vy = 0.0 if snapshot.grounded else max(-7.0, min(5.0, -float(snapshot.dy)))
        if snapshot.grounded and action in JUMP_ACTIONS:
            vy = -6.0 if abs(vx) > 2 else -5.2
        points = [(x, y)]
        reason = "horizon"
        target = {
            Action.RIGHT: 1.6,
            Action.RIGHT_JUMP: 1.6,
            Action.RIGHT_RUN: 2.8,
            Action.RIGHT_RUN_JUMP: 2.8,
            Action.LEFT: -1.6,
        }.get(action, 0.0)
        for tick in range(1, horizon_frames + 1):
            acceleration = 0.12 if target else 0.06
            vx += max(-acceleration, min(acceleration, target - vx))
            next_x = x + vx
            sides = [
                cell(next_x + edge, y + level) for edge in (2, 13) for level in (2, height - 2)
            ]
            if None in sides:
                reason = "unknown"
                break
            if "#" in sides:
                reason = "solid"
                break
            x = next_x
            support = [cell(x + edge, y + height) for edge in (2, 13)]
            if vy == 0 and "#" in support:
                next_y = y
            else:
                vy = min(5.0, vy + (0.22 if vy < 0 and action in JUMP_ACTIONS else 0.42))
                next_y = y + vy
                edge_y = next_y + height if vy >= 0 else next_y
                vertical = [cell(x + edge, edge_y) for edge in (2, 13)]
                if None in vertical:
                    reason = "unknown"
                    break
                if "#" in vertical:
                    if vy < 0:
                        reason = "solid"
                        break
                    # Snap the feet to the top of the contacted tile.
                    next_y = math.floor((snapshot.screen_y + sprite_offset + edge_y) / 16) * 16
                    next_y -= snapshot.screen_y + sprite_offset + height
                    vy = 0.0
            y = next_y
            points.append((x, y))
            if any(
                abs(x - (enemy.dx_pixels + (enemy.relative_velocity_x + snapshot.dx) * tick)) < 13
                and y + sprite_offset < enemy.dy_pixels + 16
                and y + sprite_offset + height > enemy.dy_pixels
                and enemy.kind != "flagpole"
                for enemy in snapshot.enemies
            ):
                reason = "enemy"
                break
        result.append(EstimatedTrajectory(action, tuple(points), reason))
    return tuple(result)
