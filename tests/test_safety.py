from __future__ import annotations

import unittest
from dataclasses import replace

from typesafe_mario.actions import Action
from typesafe_mario.policy import Decision
from typesafe_mario.safety import SafetyConfig, SafetyGuard
from typesafe_mario.state import EnemyObservation, MarioStateParser


class SafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = MarioStateParser().parse({"x_pos": 100, "y_pos": 80})
        self.snapshot = replace(
            self.snapshot,
            grounded=True,
            airborne=False,
            dx=3,
            local_grid=("...........", "..M........", "###########"),
        )
        self.decision = Decision(Action.RIGHT_RUN, 0.9, {"right_run": 0.9}, 220)
        self.guard = SafetyGuard(SafetyConfig(mode="conservative"))

    def test_off_is_exact_passthrough(self) -> None:
        self.assertIs(SafetyGuard().apply(self.snapshot, self.decision), self.decision)

    def test_open_ground_high_confidence_is_unchanged(self) -> None:
        applied = self.guard.apply(self.snapshot, self.decision)
        self.assertEqual(applied.action, Action.RIGHT_RUN)
        self.assertIsNone(applied.safety_reason)
        self.assertEqual(applied.safety_mode, "conservative")

    def test_low_confidence_walks_but_does_not_falsify_probabilities(self) -> None:
        decision = replace(self.decision, confidence=0.3)
        applied = self.guard.apply(self.snapshot, decision)
        self.assertEqual(applied.action, Action.RIGHT)
        self.assertEqual(applied.proposed_action, Action.RIGHT_RUN)
        self.assertEqual(applied.confidence, 0.3)
        self.assertEqual(applied.probabilities, decision.probabilities)
        self.assertEqual(applied.safety_reason, "low_confidence_walk")

    def test_threshold_is_configurable_and_boundary_is_inclusive(self) -> None:
        guard = SafetyGuard(SafetyConfig(mode="conservative", min_confidence=0.3))
        self.assertEqual(
            guard.apply(self.snapshot, replace(self.decision, confidence=0.3)).action,
            Action.RIGHT_RUN,
        )

    def test_normalized_danger_slows_run(self) -> None:
        applied = self.guard.apply(self.snapshot, replace(self.decision, danger_score=1.0))
        self.assertEqual(applied.action, Action.RIGHT)
        self.assertEqual(applied.safety_reason, "high_danger_walk")

    def test_near_enemy_triggers_jump_even_at_high_confidence(self) -> None:
        enemy = EnemyObservation(0, 6, "goomba", 48, 0, -4)
        applied = self.guard.apply(replace(self.snapshot, enemies=(enemy,)), self.decision)
        self.assertEqual(applied.action, Action.RIGHT_RUN_JUMP)
        self.assertEqual(applied.safety_reason, "enemy_reaction_margin")

    def test_flagpole_and_vertically_separated_enemy_do_not_trigger_jump(self) -> None:
        for enemy in (
            EnemyObservation(0, 0x31, "flagpole", 32, 0, -3),
            EnemyObservation(0, 6, "goomba", 32, 80, -3),
            EnemyObservation(0, 6, "goomba", -32, 0, -3),
        ):
            with self.subTest(enemy=enemy):
                applied = self.guard.apply(replace(self.snapshot, enemies=(enemy,)), self.decision)
                self.assertIsNone(applied.safety_reason)

    def test_margin_advances_enemy_takeoff(self) -> None:
        enemy = EnemyObservation(0, 6, "goomba", 88, 0, -4)
        snapshot = replace(self.snapshot, enemies=(enemy,))
        no_margin = SafetyGuard(SafetyConfig(mode="conservative", margin_frames=0))
        self.assertIsNone(no_margin.apply(snapshot, self.decision).safety_reason)
        self.assertEqual(self.guard.apply(snapshot, self.decision).action, Action.RIGHT_RUN_JUMP)

    def test_extreme_latency_does_not_cause_arbitrarily_early_jump(self) -> None:
        enemy = EnemyObservation(0, 6, "goomba", 200, 0, -3)
        snapshot = replace(self.snapshot, enemies=(enemy,), last_response_delay_frames=1000)
        self.assertIsNone(self.guard.apply(snapshot, self.decision).safety_reason)

    def test_gap_and_obstacle_trigger_grounded_jump(self) -> None:
        for grid, reason in (
            (("...........", "..M........", "####...####"), "gap_ahead"),
            (("...........", "..M.#......", "###########"), "obstacle_ahead"),
        ):
            applied = self.guard.apply(replace(self.snapshot, local_grid=grid), self.decision)
            self.assertEqual(applied.action, Action.RIGHT_RUN_JUMP)
            self.assertEqual(applied.safety_reason, reason)

    def test_crossing_gap_keeps_momentum_regardless_of_uncertainty(self) -> None:
        for phase, expected in (("rising", Action.RIGHT_RUN_JUMP), ("falling", Action.RIGHT_RUN)):
            snapshot = replace(
                self.snapshot,
                grounded=False,
                airborne=True,
                crossing_gap=True,
                jump_phase=phase,
            )
            decision = replace(self.decision, action=Action.LEFT, confidence=0.1, danger_score=2)
            self.assertEqual(self.guard.apply(snapshot, decision).action, expected)

    def test_other_airborne_actions_are_not_braked_or_jumped_from_bad_geometry(self) -> None:
        snapshot = replace(self.snapshot, grounded=False, airborne=True)
        decision = replace(self.decision, confidence=0.1, danger_score=2)
        self.assertEqual(self.guard.apply(snapshot, decision).action, Action.RIGHT_RUN)

    def test_guard_jump_is_held_while_rising_even_if_next_proposal_releases_a(self) -> None:
        snapshot = replace(
            self.snapshot,
            grounded=False,
            airborne=True,
            jump_phase="rising",
            previous_action="right_run_jump",
        )
        applied = self.guard.apply(snapshot, self.decision)
        self.assertEqual(applied.action, Action.RIGHT_RUN_JUMP)
        self.assertEqual(applied.safety_reason, "hold_rising_jump")

    def test_missing_geometry_does_not_invent_a_gap(self) -> None:
        self.assertIsNone(
            self.guard.apply(replace(self.snapshot, local_grid=()), self.decision).safety_reason
        )

    def test_recovery_and_allowed_actions(self) -> None:
        snapshot = replace(self.snapshot, stalled_steps=5, previous_action="right")
        self.assertEqual(self.guard.apply(snapshot, self.decision).action, Action.RIGHT_RUN_JUMP)
        restricted = self.guard.apply(snapshot, self.decision, (Action.RIGHT_RUN,))
        self.assertEqual(restricted.action, Action.RIGHT_RUN)

    def test_invalid_configuration_is_rejected(self) -> None:
        for kwargs in (
            {"mode": "unknown"},
            {"min_confidence": 80},
            {"min_confidence": float("nan")},
            {"danger_threshold": -0.1},
            {"margin_frames": -1},
            {"margin_frames": 1.5},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                SafetyConfig(**kwargs)


if __name__ == "__main__":
    unittest.main()
