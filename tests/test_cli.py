from __future__ import annotations

import unittest
from unittest.mock import patch

from typesafe_mario.cli import build_parser, main


class CliTests(unittest.TestCase):
    def test_defaults_and_display_modes(self) -> None:
        for mode in ("dashboard", "game", "none"):
            args = build_parser().parse_args(["play", "--display", mode])
            self.assertEqual(args.display, mode)
            self.assertEqual(args.safety_mode, "off")
            self.assertEqual(args.min_confidence, 0.8)
            self.assertEqual(args.danger_threshold, 0.5)
            self.assertEqual(args.safety_margin_frames, 6)

    def test_invalid_numbers_are_rejected_before_running_game(self) -> None:
        for flag, value in (
            ("--min-confidence", "80"),
            ("--danger-threshold", "nan"),
            ("--safety-margin-frames", "-1"),
            ("--frames-per-decision", "0"),
            ("--max-decisions", "0"),
        ):
            with self.subTest(flag=flag), patch("sys.stderr"), self.assertRaises(SystemExit):
                build_parser().parse_args(["play", flag, value])

    @patch("typesafe_mario.cli.run_episode")
    def test_guard_configuration_is_forwarded_for_heuristic(self, run) -> None:
        main(
            [
                "play",
                "--policy",
                "heuristic",
                "--display",
                "none",
                "--safety-mode",
                "conservative",
                "--min-confidence",
                "0.85",
                "--danger-threshold",
                "0.4",
                "--safety-margin-frames",
                "10",
            ]
        )
        config = run.call_args.kwargs["safety_config"]
        self.assertEqual((config.mode, config.min_confidence), ("conservative", 0.85))
        self.assertEqual((config.danger_threshold, config.margin_frames), (0.4, 10))


if __name__ == "__main__":
    unittest.main()
