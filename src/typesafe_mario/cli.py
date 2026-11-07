from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .policy import HeuristicPolicy, TypeSafePolicy
from .runner import run_episode
from .safety import SafetyConfig
from .state import MarioStateParser


def _positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return result


def _nonnegative_int(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return result


def _fraction(value: str) -> float:
    result = float(value)
    if not 0 <= result <= 1:
        raise argparse.ArgumentTypeError("use a fraction from 0 to 1 (80% = 0.8)")
    return result


def _demo_ram() -> bytearray:
    ram = bytearray(0x0800)
    # Mario position and one goomba ahead.
    ram[0x006D] = 0
    ram[0x0086] = 172
    ram[0x000F] = 1
    ram[0x0016] = 0x06
    ram[0x006E] = 0
    ram[0x0087] = 214
    ram[0x00CF] = 79
    # Fill the tile-map row immediately below Mario with solid ground.
    ground_row = (79 + 16 - 32) // 16
    for column in range(16):
        ram[0x0500 + ground_row * 16 + column] = 1
    return ram


def state_demo() -> int:
    info = {
        "world": 1,
        "stage": 1,
        "area": 1,
        "x_pos": 172,
        "y_pos": 79,
        "y_pixel": 79,
        "left_x_pos": 60,
        "progress": 172,
        "progress_max": 172,
        "status": "small",
        "player_state": 8,
        "life": 2,
        "coins": 0,
        "score": 200,
        "time": 387,
        "death": False,
        "clear": False,
    }
    snapshot = MarioStateParser().parse(info, _demo_ram(), previous_action="right")
    print(json.dumps(snapshot.to_state(), indent=2))
    print("\n--- TEXT VIEW ---\n")
    print(snapshot.to_text())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="typesafe-mario")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("state-demo", help="Show structured and text state without API calls")

    play = subparsers.add_parser("play", help="Run a Mario episode")
    play.add_argument("--env", default="SuperMarioBros-1-1-v0")
    play.add_argument(
        "--frames-per-decision",
        type=_positive_int,
        default=8,
        help="Minimum macro duration in emulator frames",
    )
    play.add_argument("--max-decisions", type=_positive_int, default=2000)
    play.add_argument("--seed", type=int, default=123)
    play.add_argument("--policy", choices=("typesafe", "heuristic"), default="typesafe")
    play.add_argument(
        "--backend",
        choices=("auto", "direct", "openrouter", "ollama"),
        default="auto",
        help="Jev transport. 'auto' picks from whichever API key is set.",
    )
    play.add_argument(
        "--model",
        help="Override the model id (e.g. typesafe/jev-1.13 on OpenRouter).",
    )
    play.add_argument(
        "--base-url", help="Override the full System One endpoint URL (not a chat endpoint)."
    )
    play.add_argument(
        "--safety-mode",
        choices=("off", "conservative"),
        default="off",
        help="Optional local safety guard; off preserves the original controller",
    )
    play.add_argument(
        "--min-confidence",
        type=_fraction,
        default=0.8,
        help="Below this confidence, walk rather than run on the ground (default: 0.8)",
    )
    play.add_argument(
        "--danger-threshold",
        type=_fraction,
        default=0.5,
        help="Normalized danger threshold for slowing down (default: 0.5)",
    )
    play.add_argument(
        "--safety-margin-frames",
        type=_nonnegative_int,
        default=6,
        help="Extra enemy-reaction margin in frames (default: 6, about 100 ms at 60 fps)",
    )
    play.add_argument(
        "--display",
        choices=("dashboard", "game", "none"),
        default="dashboard",
        help="Combined telemetry dashboard, plain game window, or headless mode",
    )
    play.add_argument("--artifacts-dir", type=Path, default=Path("artifacts"))
    play.add_argument(
        "--screenshot",
        type=Path,
        help="Save the first populated dashboard frame as a PNG",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "state-demo":
        return state_demo()
    if args.command == "play":
        if args.policy == "typesafe":
            policy = TypeSafePolicy(args.backend, model=args.model, base_url=args.base_url)
            print(f"Jev backend: {policy.describe()}")
        else:
            policy = HeuristicPolicy()
        log_path = run_episode(
            env_id=args.env,
            policy=policy,
            frames_per_decision=args.frames_per_decision,
            max_decisions=args.max_decisions,
            seed=args.seed,
            artifacts_dir=args.artifacts_dir,
            display=args.display,
            screenshot_path=args.screenshot,
            safety_config=SafetyConfig(
                mode=args.safety_mode,
                min_confidence=args.min_confidence,
                danger_threshold=args.danger_threshold,
                margin_frames=args.safety_margin_frames,
            ),
        )
        print(f"Run log: {log_path.resolve()}")
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
