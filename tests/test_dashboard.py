from __future__ import annotations

import os
import unittest
from dataclasses import replace
from unittest.mock import patch

from typesafe_mario.actions import JUMP_RELEASE_ACTION, Action
from typesafe_mario.dashboard import DashboardCommand, LiveDashboard, clamp01, dashed_segments
from typesafe_mario.policy import Decision
from typesafe_mario.state import MarioStateParser


class DashboardTests(unittest.TestCase):
    def test_clamp01_handles_missing_and_out_of_range_values(self) -> None:
        self.assertEqual(clamp01(None), 0.0)
        self.assertEqual(clamp01(-0.2), 0.0)
        self.assertEqual(clamp01(0.42), 0.42)
        self.assertEqual(clamp01(1.8), 1.0)

    def test_jump_macros_have_non_jump_release_frames(self) -> None:
        self.assertEqual(JUMP_RELEASE_ACTION[Action.RIGHT_JUMP], Action.RIGHT)
        self.assertEqual(JUMP_RELEASE_ACTION[Action.RIGHT_RUN_JUMP], Action.RIGHT_RUN)
        self.assertEqual(JUMP_RELEASE_ACTION[Action.JUMP], Action.NOOP)

    def test_dashboard_commands_are_stable_strings(self) -> None:
        self.assertEqual(DashboardCommand.RESTART, "restart")
        self.assertEqual(DashboardCommand.QUIT, "quit")

    def test_dashes_continue_across_vertices_and_skip_zero_length_edges(self) -> None:
        segments = dashed_segments(((0, 0), (0, 0), (5, 0), (20, 0)), dash=8, gap=4)
        self.assertEqual(segments, [((0, 0), (5, 0)), ((5, 0), (8, 0)), ((12, 0), (20, 0))])
        self.assertEqual(dashed_segments(((0, 0),)), [])
        with self.assertRaises(ValueError):
            dashed_segments(((0, 0), (10, 0)), gap=0)

    def test_overlay_renders_and_f_toggles_without_changing_decision(self) -> None:
        try:
            import numpy as np
            import pygame as pg
        except ImportError:
            self.skipTest("pygame/numpy are optional Mario dependencies")
        with patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"}):
            dashboard = LiveDashboard(show_trajectories=True)
            try:
                snapshot = replace(
                    MarioStateParser().parse({"x_pos": 32, "left_x_pos": 32, "y_pixel": 192}),
                    grounded=True,
                    local_grid=("...........",) * 4
                    + ("..M........", "...........")
                    + ("###########",) * 3,
                )
                decision = Decision(
                    Action.RIGHT_RUN_JUMP,
                    0.7,
                    {"right_run": 0.7, "right_run_jump": 0.3},
                    10,
                    proposed_action=Action.RIGHT_RUN,
                    safety_reason="obstacle",
                )
                frame = np.zeros((240, 256, 3), dtype=np.uint8)
                dashboard.draw(
                    frame, snapshot, decision, decision_index=1, episode_reward=0, waiting=True
                )
                overlay_pixels = pg.surfarray.array3d(dashboard.screen).copy()
                pg.event.post(pg.event.Event(pg.KEYDOWN, key=pg.K_f))
                dashboard.draw(frame, snapshot, decision, decision_index=1, episode_reward=0)
                self.assertFalse(dashboard.show_trajectories)
                self.assertFalse(
                    np.array_equal(overlay_pixels, pg.surfarray.array3d(dashboard.screen))
                )
                self.assertEqual(decision.probabilities["right_run"], 0.7)
                self.assertEqual(decision.proposed_action, Action.RIGHT_RUN)
                pg.event.post(pg.event.Event(pg.KEYDOWN, key=pg.K_r))
                command = dashboard.draw(
                    frame, snapshot, decision, decision_index=1, episode_reward=0
                )
                self.assertEqual(command, DashboardCommand.RESTART)
                self.assertFalse(dashboard.show_trajectories)
                # Missing frames/geometry are safe, including before the first model response.
                dashboard.show_trajectories = True
                dashboard.draw(None, snapshot, None, decision_index=0, episode_reward=0)
                dashboard.draw(
                    frame,
                    replace(snapshot, screen_x=None),
                    None,
                    decision_index=0,
                    episode_reward=0,
                )
                with patch.object(dashboard, "_text", wraps=dashboard._text) as text:
                    dashboard.draw(frame, snapshot, decision, decision_index=1, episode_reward=0)
                    labels = [call.args[0] for call in text.call_args_list]
                    self.assertIn("right run 70% [M]", labels)
                    self.assertIn("right run jump 30% [G]", labels)
                    text.reset_mock()
                    placeholder = Decision(
                        Action.RIGHT_RUN_JUMP,
                        0,
                        {},
                        0,
                        proposed_action=Action.NOOP,
                        safety_reason="gap_ahead",
                    )
                    dashboard.draw(
                        frame,
                        snapshot,
                        placeholder,
                        decision_index=0,
                        episode_reward=0,
                        waiting=True,
                    )
                    labels = [call.args[0] for call in text.call_args_list]
                    self.assertFalse(any("[M]" in label for label in labels))
                    self.assertIn("right run jump — [G]", labels)
            finally:
                dashboard.close()


if __name__ == "__main__":
    unittest.main()
