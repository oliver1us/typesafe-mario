from __future__ import annotations

import io
import json
import tempfile
import unittest
from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from typesafe_mario.actions import Action
from typesafe_mario.dashboard import DashboardCommand
from typesafe_mario.policy import Decision, HeuristicPolicy
from typesafe_mario.runner import (
    _controller_action,
    _record_decision,
    _run_realtime_dashboard,
    run_episode,
)
from typesafe_mario.safety import SafetyConfig, SafetyGuard
from typesafe_mario.state import MarioStateParser


class RunnerTests(unittest.TestCase):
    def test_game_uses_large_rgb_viewer_and_closing_it_stops_the_loop(self) -> None:
        env = MagicMock(ram=None, env=None)
        env.reset.return_value = ("first-frame", {"x_pos": 40})
        env.step.return_value = ("next-frame", 1.0, False, False, {"x_pos": 41})
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("typesafe_mario.runner.create_mario_env", return_value=env) as create,
            patch("typesafe_mario.runner.GameWindow") as viewer,
            patch("typesafe_mario.runner.LiveDashboard") as dashboard,
        ):
            viewer.return_value.draw.side_effect = [True, False]
            path = run_episode(
                env_id="SuperMarioBros-1-1-v0",
                policy=HeuristicPolicy(),
                frames_per_decision=8,
                max_decisions=100,
                seed=123,
                artifacts_dir=Path(directory),
                display="game",
                game_width=1280,
                game_height=720,
            )
            records = [json.loads(line) for line in path.read_text().splitlines()]
        create.assert_called_once_with("SuperMarioBros-1-1-v0", render_mode="rgb_array")
        viewer.assert_called_once_with(width=1280, height=720)
        dashboard.assert_not_called()
        env.render.assert_not_called()
        env.step.assert_called_once()
        viewer.return_value.close.assert_called_once()
        env.close.assert_called_once()
        self.assertEqual(records[-1]["event"], "episode_summary")
        self.assertEqual(records[-1]["decisions"], 1)

    def test_viewer_initialization_failure_still_closes_environment(self) -> None:
        env = MagicMock(ram=None, env=None)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("typesafe_mario.runner.create_mario_env", return_value=env),
            patch("typesafe_mario.runner.GameWindow", side_effect=RuntimeError("no display")),
            self.assertRaisesRegex(RuntimeError, "no display"),
        ):
            run_episode(
                env_id="test",
                policy=HeuristicPolicy(),
                frames_per_decision=8,
                max_decisions=1,
                seed=123,
                artifacts_dir=Path(directory),
                display="game",
            )
        env.close.assert_called_once()

    def test_realtime_draw_uses_post_step_state(self) -> None:
        env = MagicMock(ram=None, env=None)
        env.step.return_value = ("new-frame", 0, False, False, {"x_pos": 41})
        dashboard = MagicMock()
        dashboard.draw.return_value = DashboardCommand.QUIT
        parser = MarioStateParser()
        with patch("typesafe_mario.runner.ThreadPoolExecutor") as executor:
            executor.return_value.__enter__.return_value.submit.return_value = Future()
            _run_realtime_dashboard(
                env=env,
                dashboard=dashboard,
                policy=HeuristicPolicy(),
                parser=parser,
                frame="old-frame",
                info={"x_pos": 40},
                log=io.StringIO(),
                frames_per_decision=8,
                max_decisions=10,
                screenshot_path=None,
                guard=SafetyGuard(),
            )
        frame, snapshot, _ = dashboard.draw.call_args.args
        self.assertEqual(frame, "new-frame")
        self.assertEqual((snapshot.x, snapshot.dx), (41, 1))

    def test_realtime_guard_intervenes_while_model_future_is_pending(self) -> None:
        class PendingExecutor:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def submit(self, *args):
                return Future()  # Never completes during this short simulation.

        class Env:
            ram = None

            def step(self, action):
                return None, 0, False, False, {}

        class Parser:
            def parse(self, *args, **kwargs):
                return snapshot

        class Dashboard:
            calls = 0

            def draw(self, frame, snapshot, decision, **kwargs):
                self.calls += 1
                self.asserted_action = decision.action
                return DashboardCommand.QUIT if self.calls == 3 else DashboardCommand.CONTINUE

        snapshot = replace(
            MarioStateParser().parse({}),
            grounded=True,
            dx=3,
            local_grid=("...........", "..M.#......", "###########"),
        )
        log = io.StringIO()
        dashboard = Dashboard()
        with patch("typesafe_mario.runner.ThreadPoolExecutor", PendingExecutor):
            _run_realtime_dashboard(
                env=Env(),
                dashboard=dashboard,
                policy=HeuristicPolicy(),
                parser=Parser(),
                frame=None,
                info={},
                log=log,
                frames_per_decision=8,
                max_decisions=10,
                screenshot_path=None,
                guard=SafetyGuard(SafetyConfig(mode="conservative")),
            )
        self.assertEqual(dashboard.asserted_action, Action.RIGHT_RUN_JUMP)
        records = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual(records[0]["event"], "safety_override")
        self.assertEqual(records[-1]["safety_interventions"], 1)

    def test_jump_release_only_when_a_was_previously_held(self) -> None:
        snapshot = replace(MarioStateParser().parse({}), grounded=True, action_frames=2)
        decision = Decision(Action.RIGHT_RUN_JUMP, 1, {}, 0)
        self.assertEqual(
            _controller_action(decision, snapshot, Action.RIGHT), Action.RIGHT_RUN_JUMP
        )
        self.assertEqual(
            _controller_action(decision, snapshot, Action.RIGHT_RUN_JUMP), Action.RIGHT_RUN
        )
        self.assertEqual(
            _controller_action(decision, replace(snapshot, action_frames=1), Action.RIGHT_RUN_JUMP),
            Action.RIGHT_RUN_JUMP,
        )
        self.assertEqual(
            _controller_action(decision, replace(snapshot, grounded=False), Action.RIGHT_RUN_JUMP),
            Action.RIGHT_RUN_JUMP,
        )

    def test_record_distinguishes_model_and_applied_action(self) -> None:
        log = io.StringIO()
        snapshot = MarioStateParser().parse({})
        decision = Decision(
            Action.RIGHT,
            0.3,
            {"right_run": 0.7},
            200,
            proposed_action=Action.RIGHT_RUN,
            safety_reason="low_confidence_walk",
            safety_mode="conservative",
        )
        _record_decision(
            log,
            decision_index=0,
            snapshot=snapshot,
            decision=decision,
            reward=1,
            terminated=False,
            truncated=False,
        )
        record = json.loads(log.getvalue())
        self.assertEqual(record["action"], "right")
        self.assertEqual(record["proposed_action"], "right_run")
        self.assertEqual(record["probabilities"], {"right_run": 0.7})

    def test_headless_run_checks_guard_between_decisions_and_writes_summary(self) -> None:
        class Env:
            ram = None
            count = 0

            def reset(self, **kwargs):
                return None, {"x_pos": 40}

            def step(self, action):
                self.count += 1
                return None, 1.0, self.count == 4, False, {"x_pos": 40 + self.count}

            def close(self):
                pass

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("typesafe_mario.runner.create_mario_env", return_value=Env()),
        ):
            path = run_episode(
                env_id="SuperMarioBros-1-1-v0",
                policy=HeuristicPolicy(),
                frames_per_decision=8,
                max_decisions=2,
                seed=123,
                artifacts_dir=Path(directory),
                display="none",
                safety_config=SafetyConfig(mode="conservative"),
            )
            records = [json.loads(line) for line in path.read_text().splitlines()]
        summary = records[-1]
        self.assertEqual(summary["event"], "episode_summary")
        self.assertEqual(summary["best_progress"], 44)
        self.assertTrue(summary["dead"])
        self.assertEqual(summary["safety_config"]["mode"], "conservative")


if __name__ == "__main__":
    unittest.main()
