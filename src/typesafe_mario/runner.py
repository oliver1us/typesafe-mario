from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .actions import ACTION_TO_INDEX, JUMP_ACTIONS, JUMP_RELEASE_ACTION, Action
from .dashboard import DashboardCommand, LiveDashboard
from .policy import Decision, Policy
from .safety import SafetyConfig, SafetyGuard
from .state import MarioStateParser


def _unwrap_ram(env: Any) -> Any:
    current = env
    visited: set[int] = set()
    while id(current) not in visited:
        visited.add(id(current))
        ram = getattr(current, "ram", None)
        if ram is not None:
            return ram
        next_env = getattr(current, "env", None)
        if next_env is None:
            break
        current = next_env
    return None


def create_mario_env(env_id: str, render_mode: str = "human") -> Any:
    try:
        import gym_super_mario_bros  # noqa: F401
        import gymnasium as gym
        from gym_super_mario_bros.actions import SIMPLE_MOVEMENT
        from nes_py.wrappers import JoypadSpace
    except ImportError as exc:
        raise RuntimeError(
            'Mario dependencies are missing. Install with: pip install -e ".[mario]"'
        ) from exc

    env = gym.make(env_id, render_mode=render_mode)
    return JoypadSpace(env, SIMPLE_MOVEMENT)


def _record_decision(
    log: Any,
    *,
    decision_index: int,
    snapshot: Any,
    decision: Decision,
    reward: float,
    terminated: bool,
    truncated: bool,
    control_snapshot: Any = None,
) -> None:
    record = {
        "event": "decision",
        "decision": decision_index,
        "state": snapshot.to_state(),
        "debug_state": snapshot.to_debug_state(),
        "state_text": snapshot.to_text(),
        "action": decision.action.value,
        "proposed_action": (decision.proposed_action or decision.action).value,
        "safety_mode": decision.safety_mode,
        "safety_reason": decision.safety_reason,
        "control_state": (control_snapshot or snapshot).to_state(),
        "confidence": decision.confidence,
        "probabilities": dict(decision.probabilities),
        "jump_needed_probability": decision.jump_needed_probability,
        "danger_score": decision.danger_score,
        "latency_ms": decision.latency_ms,
        "reward": reward,
        "terminated": bool(terminated),
        "truncated": bool(truncated),
    }
    log.write(json.dumps(record, separators=(",", ":")) + "\n")
    log.flush()


def _controller_action(decision: Decision, snapshot: Any, previous: Action | None) -> Action:
    if (
        snapshot.grounded
        and decision.action in JUMP_ACTIONS
        and previous in JUMP_ACTIONS
        and snapshot.action_frames >= 2
    ):
        # The first jump frame can still report grounded: do not release A yet.
        # After a landing, release a previously held button before a new takeoff.
        return JUMP_RELEASE_ACTION[decision.action]
    return decision.action


def _record_override(log: Any, snapshot: Any, decision: Decision, frame_index: int) -> None:
    log.write(
        json.dumps(
            {
                "event": "safety_override",
                "frame": frame_index,
                "state": snapshot.to_state(),
                "proposed_action": (decision.proposed_action or decision.action).value,
                "action": decision.action.value,
                "safety_reason": decision.safety_reason,
                "confidence": decision.confidence,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    log.flush()


def _record_summary(
    log: Any,
    snapshot: Any,
    guard: SafetyGuard,
    decisions: int,
    overrides: int,
    *,
    terminated: bool,
    truncated: bool,
) -> None:
    log.write(
        json.dumps(
            {
                "event": "episode_summary",
                "best_progress": snapshot.best_progress,
                "dead": snapshot.dead or (terminated and not snapshot.clear),
                "stage_clear": snapshot.clear,
                "terminated": bool(terminated),
                "truncated": bool(truncated),
                "decisions": decisions,
                "safety_interventions": overrides,
                "safety_config": asdict(guard.config),
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    log.flush()


def _run_realtime_dashboard(
    *,
    env: Any,
    dashboard: LiveDashboard,
    policy: Policy,
    parser: MarioStateParser,
    frame: Any,
    info: dict[str, Any],
    log: Any,
    frames_per_decision: int,
    max_decisions: int,
    screenshot_path: Path | None,
    guard: SafetyGuard,
) -> None:
    actions = tuple(Action)
    active_decision: Decision | None = None
    pending: Future[Decision] | None = None
    pending_snapshot: Any = None
    pending_index = 0
    pending_request_frame = 0
    next_index = 0
    frame_index = 0
    last_request_frame = -frames_per_decision
    episode_reward = 0.0
    reward_since_decision = 0.0
    previous_action: Action | None = None
    previous_reward = 0.0
    previous_latency_ms = 0.0
    previous_response_delay_frames = 0
    screenshot_saved = False
    terminated = truncated = False
    interventions = 0
    last_override = None
    summary_recorded = False

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="typesafe-jev") as executor:
        while True:
            snapshot = parser.parse(
                info,
                _unwrap_ram(env),
                previous_action=previous_action.value if previous_action else None,
                previous_reward=previous_reward,
                previous_latency_ms=previous_latency_ms,
                previous_response_delay_frames=previous_response_delay_frames,
            )

            if pending is not None and pending.done():
                active_decision = pending.result()
                previous_latency_ms = active_decision.latency_ms
                previous_response_delay_frames = frame_index - pending_request_frame
                snapshot = replace(
                    snapshot, last_response_delay_frames=previous_response_delay_frames
                )
                applied = guard.apply(snapshot, active_decision, actions)
                _record_decision(
                    log,
                    decision_index=pending_index,
                    snapshot=pending_snapshot,
                    decision=applied,
                    reward=reward_since_decision,
                    terminated=terminated,
                    truncated=truncated,
                    control_snapshot=snapshot,
                )
                print(
                    f"#{pending_index:04d} x={pending_snapshot.x:04d} "
                    f"action={applied.action.value:<15} "
                    f"confidence={active_decision.confidence:.2f} "
                    f"latency={active_decision.latency_ms:.0f}ms"
                    + (f" guard={applied.safety_reason}" if applied.safety_reason else "")
                )
                pending = None
                reward_since_decision = 0.0

            run_ended = bool(
                snapshot.dead
                or snapshot.clear
                or terminated
                or truncated
                or (next_index >= max_decisions and pending is None)
            )
            if run_ended and not summary_recorded:
                _record_summary(
                    log,
                    snapshot,
                    guard,
                    next_index,
                    interventions,
                    terminated=terminated,
                    truncated=truncated,
                )
                summary_recorded = True

            if (
                not run_ended
                and pending is None
                and next_index < max_decisions
                and frame_index - last_request_frame >= frames_per_decision
            ):
                pending_snapshot = snapshot
                pending_index = next_index
                pending = executor.submit(policy.choose, snapshot, actions)
                pending_request_frame = frame_index
                next_index += 1
                last_request_frame = frame_index

            applied = guard.apply(
                snapshot, active_decision or Decision(Action.NOOP, 0.0, {}, 0.0), actions
            )
            if not run_ended:
                override = (
                    (applied.action, applied.safety_reason) if applied.safety_reason else None
                )
                if override is not None and override != last_override:
                    interventions += 1
                    _record_override(log, snapshot, applied, frame_index)
                last_override = override
                action = _controller_action(applied, snapshot, previous_action)
                frame, reward, terminated, truncated, info = env.step(ACTION_TO_INDEX[action])
                previous_action = action
                previous_reward = float(reward)
                reward_since_decision += float(reward)
                episode_reward += float(reward)
                frame_index += 1

            command = dashboard.draw(
                frame,
                snapshot,
                applied if active_decision or applied.safety_reason else None,
                decision_index=max(0, next_index - 1),
                episode_reward=episode_reward,
                waiting=pending is not None,
                run_ended=run_ended,
            )
            if screenshot_path is not None and active_decision is not None and not screenshot_saved:
                dashboard.save(screenshot_path)
                screenshot_saved = True
            if command == DashboardCommand.QUIT:
                if not summary_recorded:
                    _record_summary(
                        log,
                        snapshot,
                        guard,
                        next_index,
                        interventions,
                        terminated=terminated,
                        truncated=truncated,
                    )
                break
            if command == DashboardCommand.RESTART:
                if not summary_recorded:
                    _record_summary(
                        log,
                        snapshot,
                        guard,
                        next_index,
                        interventions,
                        terminated=terminated,
                        truncated=truncated,
                    )
                if pending is not None:
                    pending.cancel()
                frame, info = env.reset()
                parser.reset()
                active_decision = None
                pending = None
                pending_snapshot = None
                pending_index = 0
                pending_request_frame = 0
                next_index = 0
                frame_index = 0
                last_request_frame = -frames_per_decision
                episode_reward = 0.0
                reward_since_decision = 0.0
                previous_action = None
                previous_reward = 0.0
                previous_latency_ms = 0.0
                previous_response_delay_frames = 0
                terminated = truncated = False
                interventions = 0
                last_override = None
                summary_recorded = False
                print("--- Restarted ---")


def run_episode(
    *,
    env_id: str,
    policy: Policy,
    frames_per_decision: int,
    max_decisions: int,
    seed: int,
    artifacts_dir: Path,
    display: str = "dashboard",
    screenshot_path: Path | None = None,
    safety_config: SafetyConfig | None = None,
) -> Path:
    if frames_per_decision < 1:
        raise ValueError("frames_per_decision must be at least 1")
    if max_decisions < 1:
        raise ValueError("max_decisions must be at least 1")

    if display not in {"dashboard", "game", "none"}:
        raise ValueError("display must be dashboard, game, or none")
    render_mode = "human" if display == "game" else "rgb_array"
    env = create_mario_env(env_id, render_mode=render_mode)
    guard = SafetyGuard(safety_config)
    dashboard = LiveDashboard(safety_mode=guard.config.mode) if display == "dashboard" else None
    parser = MarioStateParser(
        goal=f"Reach the flag in {env_id} without dying.",
        decision_horizon_frames=frames_per_decision,
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    log_path = artifacts_dir / f"run-{timestamp}.jsonl"

    frame, info = env.reset(seed=seed)

    try:
        with log_path.open("w", encoding="utf-8") as log:
            if dashboard:
                _run_realtime_dashboard(
                    env=env,
                    dashboard=dashboard,
                    policy=policy,
                    parser=parser,
                    frame=frame,
                    info=info,
                    log=log,
                    frames_per_decision=frames_per_decision,
                    max_decisions=max_decisions,
                    screenshot_path=screenshot_path,
                    guard=guard,
                )
                return log_path

            previous_action: Action | None = None
            actions = tuple(Action)
            snapshot = parser.parse(info, _unwrap_ram(env), previous_response_delay_frames=0)
            interventions = 0
            last_override = None
            frame_index = 0
            decisions = 0
            terminated = truncated = False
            for decision_index in range(max_decisions):
                if snapshot.dead or snapshot.clear:
                    break

                request_snapshot = snapshot
                decision = policy.choose(snapshot, actions)
                applied = guard.apply(snapshot, decision, actions)
                first_applied = applied
                decisions += 1
                total_reward = 0.0
                terminated = truncated = False
                for _ in range(frames_per_decision):
                    applied = guard.apply(snapshot, decision, actions)
                    override = (
                        (applied.action, applied.safety_reason) if applied.safety_reason else None
                    )
                    if override is not None and override != last_override:
                        interventions += 1
                        _record_override(log, snapshot, applied, frame_index)
                    last_override = override
                    action = _controller_action(applied, snapshot, previous_action)
                    frame, reward, terminated, truncated, info = env.step(ACTION_TO_INDEX[action])
                    if display == "game":
                        env.render()
                    previous_action = action
                    frame_index += 1
                    total_reward += float(reward)
                    snapshot = parser.parse(
                        info,
                        _unwrap_ram(env),
                        previous_action=action.value,
                        previous_reward=float(reward),
                        previous_latency_ms=decision.latency_ms,
                        previous_response_delay_frames=0,
                    )
                    if terminated or truncated:
                        break

                _record_decision(
                    log,
                    decision_index=decision_index,
                    snapshot=request_snapshot,
                    decision=first_applied,
                    reward=total_reward,
                    terminated=terminated,
                    truncated=truncated,
                )
                print(
                    f"#{decision_index:04d} x={request_snapshot.x:04d} "
                    f"action={first_applied.action.value:<15} "
                    f"confidence={decision.confidence:.2f} latency={decision.latency_ms:.0f}ms"
                    + (
                        f" guard={first_applied.safety_reason}"
                        if first_applied.safety_reason
                        else ""
                    )
                )

                if terminated or truncated:
                    break
            _record_summary(
                log,
                snapshot,
                guard,
                decisions,
                interventions,
                terminated=terminated,
                truncated=truncated,
            )
    finally:
        if dashboard:
            dashboard.close()
        env.close()
        close = getattr(policy, "close", None)
        if callable(close):
            close()

    return log_path
