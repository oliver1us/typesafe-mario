from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

from .actions import Action
from .policy import Decision
from .state import MarioSnapshot


@dataclass(frozen=True)
class SafetyConfig:
    mode: str = "off"
    min_confidence: float = 0.8
    danger_threshold: float = 0.5
    margin_frames: int = 6

    def __post_init__(self) -> None:
        if self.mode not in {"off", "conservative"}:
            raise ValueError("safety mode must be off or conservative")
        for name in ("min_confidence", "danger_threshold"):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if not isinstance(self.margin_frames, int) or self.margin_frames < 0:
            raise ValueError("safety margin must be a non-negative number of frames")


class SafetyGuard:
    """Optional actuation-time guard, not a calibrated survival predictor.

    Use fresh geometry rather than blindly thresholding model confidence. This
    also works between model responses and leaves the original probabilities
    unchanged so interventions can be audited.
    """

    def __init__(self, config: SafetyConfig | None = None) -> None:
        self.config = config or SafetyConfig()

    def apply(
        self,
        snapshot: MarioSnapshot,
        decision: Decision,
        actions: Sequence[Action] = tuple(Action),
    ) -> Decision:
        if self.config.mode == "off" or snapshot.dead or snapshot.clear:
            return decision

        def override(action: Action, reason: str) -> Decision:
            if action not in actions or action == decision.action:
                return replace(decision, safety_mode=self.config.mode)
            return replace(
                decision,
                action=action,
                proposed_action=decision.proposed_action or decision.action,
                safety_reason=reason,
                safety_mode=self.config.mode,
            )

        # Braking or releasing A while rising over a known gap can be fatal.
        if not snapshot.grounded:
            if snapshot.crossing_gap:
                action = (
                    Action.RIGHT_RUN_JUMP if snapshot.jump_phase == "rising" else Action.RIGHT_RUN
                )
                return override(action, "preserve_gap_momentum")
            if snapshot.jump_phase == "rising" and snapshot.previous_action in {
                Action.RIGHT_JUMP.value,
                Action.RIGHT_RUN_JUMP.value,
            }:
                return override(Action.RIGHT_RUN_JUMP, "hold_rising_jump")
            return replace(decision, safety_mode=self.config.mode)

        # The local guard sees current RAM, so do not add an unbounded API delay
        # to the takeoff distance: a very early jump can land on the enemy.
        horizon = (
            min(12, snapshot.decision_horizon_frames + snapshot.last_response_delay_frames)
            + self.config.margin_frames
        )
        # Allow for Mario's width and the extra frames needed to gain clearance.
        speed = max(1, snapshot.dx)
        enemy_window = speed * (horizon + 8) + 16
        threatening_enemies = [
            enemy
            for enemy in snapshot.enemies
            if enemy.kind != "flagpole"
            and abs(enemy.dy_pixels) <= 24
            and 0
            <= enemy.dx_pixels
            <= max(enemy_window, max(0, -enemy.relative_velocity_x) * (horizon + 8) + 16)
        ]
        terrain = snapshot.navigation_features()
        # Never initiate a terrain jump from unreliable airborne geometry. The
        # lookahead is capped at three tiles: jumping too early also causes falls.
        lookahead = min(3, max(2, math.ceil((speed * horizon + 16) / 16)))
        gap = terrain.get("gap_distance_tiles")
        obstacle = terrain.get("obstacle_distance_tiles")
        reason = None
        if gap is not None and gap <= lookahead:
            reason = "gap_ahead"
        elif obstacle is not None and obstacle <= lookahead:
            reason = "obstacle_ahead"
        elif threatening_enemies:
            reason = "enemy_reaction_margin"
        elif snapshot.stalled_steps >= 4 and snapshot.previous_action in {
            Action.RIGHT.value,
            Action.RIGHT_RUN.value,
        }:
            reason = "blocked_forward_motion"

        if reason:
            return override(Action.RIGHT_RUN_JUMP, reason)

        danger = (decision.danger_score or 0.0) / 2.0
        uncertain = decision.confidence < self.config.min_confidence
        if decision.action == Action.RIGHT_RUN and (
            uncertain or danger >= self.config.danger_threshold
        ):
            # Walk, not stop. Do not invent a jump from low confidence alone.
            return override(
                Action.RIGHT, "low_confidence_walk" if uncertain else "high_danger_walk"
            )
        return replace(decision, safety_mode=self.config.mode)
