from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from typesafe_mario.cli import build_parser


@unittest.skipUnless(shutil.which("bash"), "Docker entrypoint requires bash")
class EntrypointTests(unittest.TestCase):
    def run_entrypoint(self, *arguments: str, **environment: str) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "typesafe-mario"
            executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            executable.chmod(0o755)
            result = subprocess.run(
                [
                    "bash",
                    str(Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"),
                    *arguments,
                ],
                env={"PATH": f"{directory}{os.pathsep}{os.environ['PATH']}", **environment},
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        return result.stdout.splitlines()

    def test_cli_headless_override_skips_graphical_services_and_wins_over_environment(self) -> None:
        argv = self.run_entrypoint(
            "--display",
            "none",
            "--policy",
            "heuristic",
            "--safety-mode",
            "off",
            GAME_DISPLAY="dashboard",
            POLICY="typesafe",
            SAFETY_MODE="conservative",
            MIN_CONFIDENCE="0.85",
            DANGER_THRESHOLD="0.4",
            SAFETY_MARGIN_FRAMES="10",
        )
        args = build_parser().parse_args(argv)
        self.assertEqual(
            (args.display, args.policy, args.safety_mode), ("none", "heuristic", "off")
        )
        self.assertEqual((args.min_confidence, args.danger_threshold), (0.85, 0.4))
        self.assertEqual(args.safety_margin_frames, 10)

    def test_equals_headless_form_and_quoted_model(self) -> None:
        argv = self.run_entrypoint("--display=none", MODEL="a model with spaces")
        self.assertEqual(build_parser().parse_args(argv).model, "a model with spaces")

    def test_environment_only_configuration(self) -> None:
        argv = self.run_entrypoint(
            GAME_DISPLAY="none", POLICY="heuristic", SAFETY_MODE="conservative"
        )
        args = build_parser().parse_args(argv)
        self.assertEqual(args.policy, "heuristic")
        self.assertEqual(args.safety_mode, "conservative")

    def test_trajectory_environment_default_and_cli_override(self) -> None:
        for value in ("true", "1", "yes", "on"):
            argv = self.run_entrypoint("--display=none", SHOW_TRAJECTORIES=value)
            self.assertTrue(build_parser().parse_args(argv).trajectories)
        argv = self.run_entrypoint("--display=none", "--no-trajectories", SHOW_TRAJECTORIES="true")
        self.assertFalse(build_parser().parse_args(argv).trajectories)
        argv = self.run_entrypoint("--display=none", "--trajectories", SHOW_TRAJECTORIES="false")
        self.assertTrue(build_parser().parse_args(argv).trajectories)

    def test_virtual_desktop_dimensions_set_game_size_but_cli_wins(self) -> None:
        argv = self.run_entrypoint("--display=none", DISPLAY_WIDTH="1280", DISPLAY_HEIGHT="720")
        args = build_parser().parse_args(argv)
        self.assertEqual((args.game_width, args.game_height), (1280, 720))
        argv = self.run_entrypoint("--display=none", "--game-width=960", DISPLAY_WIDTH="1280")
        self.assertEqual(build_parser().parse_args(argv).game_width, 960)


if __name__ == "__main__":
    unittest.main()
