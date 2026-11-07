from __future__ import annotations

import unittest
from dataclasses import replace

from typesafe_mario.actions import Action
from typesafe_mario.state import EnemyObservation, MarioStateParser
from typesafe_mario.trajectories import ACTION_COLORS, estimate_trajectories


class TrajectoryTests(unittest.TestCase):
    def snapshot(self, **changes):
        snapshot = MarioStateParser().parse({"x_pos": 32, "y_pixel": 192, "left_x_pos": 32})
        return replace(
            snapshot,
            grounded=True,
            local_grid=("...........",) * 4 + ("..M........", "...........") + ("###########",) * 3,
            **changes,
        )

    def test_all_actions_have_unique_colors_and_share_origin_without_mutation(self):
        snapshot = self.snapshot()
        before = snapshot.to_debug_state()
        paths = estimate_trajectories(snapshot)
        self.assertEqual({path.action for path in paths}, set(Action))
        self.assertEqual(len(set(ACTION_COLORS.values())), len(Action))
        self.assertTrue(all(path.points[0] == (0, 0) for path in paths))
        self.assertEqual(snapshot.to_debug_state(), before)

    def test_running_moves_further_than_walking_and_jumping_rises(self):
        paths = {
            path.action: path for path in estimate_trajectories(self.snapshot(), horizon_frames=20)
        }
        self.assertGreater(paths[Action.RIGHT_RUN].points[-1][0], paths[Action.RIGHT].points[-1][0])
        self.assertLess(paths[Action.LEFT].points[-1][0], 0)
        self.assertEqual(paths[Action.NOOP].points[-1], (0, 0))
        self.assertLess(min(y for _, y in paths[Action.RIGHT_JUMP].points), -30)

    def test_inertia_does_not_disappear_on_noop(self):
        path = estimate_trajectories(self.snapshot(dx=3), [Action.NOOP], horizon_frames=5)[0]
        self.assertGreater(path.points[-1][0], 10)

    def test_airborne_jump_does_not_invent_a_second_takeoff(self):
        snapshot = replace(
            self.snapshot(),
            grounded=False,
            dy=-3,
            jump_phase="falling",
            local_grid=("...........",) * 4
            + ("..M........", "...........", "...........", "###########"),
        )
        path = estimate_trajectories(snapshot, [Action.JUMP], horizon_frames=1)[0]
        self.assertGreater(path.points[-1][1], 0)

    def test_paths_stop_at_walls_and_possible_enemy_contact(self):
        snapshot = replace(
            self.snapshot(),
            local_grid=("...........",) * 4 + ("..M.#......", "....#......") + ("###########",) * 3,
        )
        path = estimate_trajectories(snapshot, [Action.RIGHT_RUN])[0]
        self.assertEqual(path.end_reason, "solid")
        self.assertLess(path.points[-1][0], 32)
        snapshot = self.snapshot(enemies=(EnemyObservation(0, 6, "goomba", 32, 16),))
        path = estimate_trajectories(snapshot, [Action.RIGHT_RUN])[0]
        self.assertEqual(path.end_reason, "enemy")

    def test_unknown_tiles_truncate_instead_of_inventing_terrain(self):
        snapshot = replace(self.snapshot(), local_grid=("....",) * 4 + ("..M.", "....", "####"))
        path = estimate_trajectories(snapshot, [Action.RIGHT_RUN])[0]
        self.assertEqual(path.end_reason, "unknown")
        self.assertLess(len(path.points), 46)

    def test_gaps_allow_falling_but_flat_ground_supports_walking(self):
        snapshot = replace(
            self.snapshot(),
            local_grid=("...........",) * 4 + ("..M........", "...........") + ("####.......",) * 3,
        )
        path = estimate_trajectories(snapshot, [Action.RIGHT_RUN])[0]
        self.assertGreater(path.points[-1][1], 0)
        flat = estimate_trajectories(self.snapshot(), [Action.RIGHT_RUN])[0]
        self.assertTrue(all(y == 0 for _, y in flat.points))

    def test_missing_geometry_offscreen_and_terminal_states_have_no_paths(self):
        for changes in ({"local_grid": ()}, {"screen_y": None}, {"dead": True}, {"clear": True}):
            with self.subTest(changes=changes):
                self.assertEqual(estimate_trajectories(replace(self.snapshot(), **changes)), ())

    def test_invalid_horizons_are_rejected(self):
        for value in (0, -1, 121):
            with self.assertRaises(ValueError):
                estimate_trajectories(self.snapshot(), horizon_frames=value)

    def test_flagpole_is_not_an_enemy_collision_and_enemy_motion_is_projected(self):
        snapshot = self.snapshot(enemies=(EnemyObservation(0, 0x31, "flagpole", 32, 16),))
        path = estimate_trajectories(snapshot, [Action.RIGHT_RUN])[0]
        self.assertNotEqual(path.end_reason, "enemy")
        still = self.snapshot(enemies=(EnemyObservation(0, 6, "goomba", 50, 16),))
        approaching = self.snapshot(enemies=(EnemyObservation(0, 6, "goomba", 50, 16, -2),))
        still_path = estimate_trajectories(still, [Action.RIGHT_RUN])[0]
        approaching_path = estimate_trajectories(approaching, [Action.RIGHT_RUN])[0]
        self.assertEqual(approaching_path.end_reason, "enemy")
        self.assertLess(len(approaching_path.points), len(still_path.points))


if __name__ == "__main__":
    unittest.main()
