# Agent Guide: typesafe-mario

This fork of `fhshaik/typesafe-mario` runs the Jev-backed SMB1 controller through
TypeSafe direct, OpenRouter, or an explicitly System One-compatible local server.
An offline heuristic, optional conservative guard, and Docker/noVNC workflow are
also available. [README.md](README.md) is the canonical user/command reference.

## Fork changes and layout

```text
src/typesafe_mario/
  jev_backend.py   # stdlib HTTP System One transport; backend/model/full URL selection
  policy.py        # TypeSafePolicy, optional SDK question types, HeuristicPolicy
  safety.py        # SafetyConfig + opt-in per-emulator-frame SafetyGuard
  cli.py           # argparse entry point and validation
  runner.py        # synchronous/realtime loops, jump edges, JSONL events and summaries
  state.py         # SMB1 RAM -> structured model state and debug views
  dashboard.py     # pygame telemetry, guard action/reason vs original model probabilities
  actions.py       # controller macros
tests/             # state, backend, CLI, dashboard, safety, runner, and entrypoint tests
Dockerfile         # Python 3.13 + emulator + TigerVNC + noVNC
compose.yml        # service config, host port 6081 -> container 6080, artifacts bind mount
docker-entrypoint.sh
.env.example       # safe configuration template; never commit the real .env
.opencode/agents/documenter.md
```

`typesafe-sdk` is an optional `typesafe` extra, not a required dependency. HTTP
transport and fallback question types work without it. Read current CLI/config
definitions before changing defaults or documenting new flags.

## Local development

Requires Python 3.13+ and, for emulator installation, any necessary native build
tools. Dashboard/game windows need a graphical session; headless runs do not.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[mario,dev]"
typesafe-mario state-demo
python -m unittest discover -s tests -p 'test_*.py' -v
python -m pytest -q
ruff format --check src tests
ruff check src tests
bash -n docker-entrypoint.sh
docker compose config --quiet
```

`state-demo`, unit tests, and `--policy heuristic` require no paid API calls.
Do not make billable provider calls merely to validate documentation. Distinguish
local/mocked checks, emulator smoke tests, and live backend validation in reports.
Do not expose credentials in examples, logs, diffs, or command output. Use quoted
placeholders such as `"your-openrouter-key"`; do not inspect or print actual `.env`
contents during routine reviews. `docker compose config --quiet` validates without
rendering interpolated secrets.

## Backend rules

| Backend | Credential | Default model |
|---|---|---|
| `direct` | `TYPESAFE_API_KEY` | `jev-latest` |
| `openrouter` | `OPENROUTER_API_KEY` | `typesafe/jev-1.13` |
| `ollama` | Optional `OLLAMA_API_KEY` | `nimble` |

Local CLI backend auto-detection is direct key > OpenRouter key > local server.
Docker's entrypoint defaults to `openrouter`. `--model` overrides the model;
`--base-url` overrides the **full** System One endpoint, not a root/chat URL.
Select a backend explicitly with an endpoint override to retain its model and
credential selection. `auto` plus an override selects a custom transport with
`jev-latest` and no automatically selected credential.

`OLLAMA_HOST` controls the host for the `ollama` transport. **Do not claim that
stock Ollama, a particular Ollama version, or arbitrary chat models implement
`/v1/systemone`.** This transport requires an explicitly compatible server; the
default `nimble` model string is not proof of availability. Direct/local live
compatibility has not been validated in this change. Never present mocked tests
as live-provider verification.

## Controller and evaluation rules

- Safety defaults to `off`; `--safety-mode conservative` is opt-in. Defaults are
  `--min-confidence 0.8`, `--danger-threshold 0.5`, and
  `--safety-margin-frames 6`. Thresholds are fractions from 0 to 1.
- The guard uses fresh RAM every emulator frame, even while a dashboard API
  request is pending. Grounded hazards/recovery can trigger forward jumps;
  known-gap momentum and rising forward jumps are preserved. Low confidence or
  normalized danger (`danger_score / 2`) only slows grounded `right_run` to
  `right` absent a more urgent rule. It is not a blanket confidence filter or
  a survival guarantee. Heuristic confidence is hardcoded to 1.0.
- The dashboard displays the guard-selected action/reason without rewriting
  model confidence/probabilities. The controller separately manages jump-button
  release/repress edges. Logs are not a full per-frame controller-input trace.
- `dashboard` is asynchronous and targets 60 fps; the world advances during API
  calls. `game` explicitly renders the synchronous loop, while `none` runs it
  without windows. Game/headless pause the world during API requests. Do not
  equate headless outcomes with real-time dashboard results.
- Settings are startup-only. **Restart**/`R` resets an episode, not safety,
  policy, or display flags. Changing them requires a new command/container.
- Compare matching policies, seeds, environments, cadence, decision budgets, and
  display modes. Use `episode_summary` (`best_progress`, `dead`, `stage_clear`,
  config) and intervention events. A single seed/offline heuristic comparison is
  not statistical evidence of better AI play; no model training is performed.
- New logs include `decision`, `safety_override`, and `episode_summary` events;
  filenames use UTC microseconds. Preserve compatibility awareness for old
  decision-only logs without an `event` field. Dashboard restarts reuse the log.
  There is no `run_start` event or full invocation record: retain comparison
  commands, seeds, environments, cadence, backends, and models alongside logs.

## Docker/noVNC workflows

```bash
docker compose build mario

# Free offline dashboard, guard enabled:
docker compose run --rm --service-ports mario --policy heuristic --safety-mode conservative

# Free headless smoke test, no X/VNC/noVNC processes:
docker compose run --rm mario --policy heuristic --display none --max-decisions 25

# Billable AI service only when explicitly intended:
export OPENROUTER_API_KEY="your-openrouter-key"
BACKEND=openrouter POLICY=typesafe SAFETY_MODE=conservative docker compose up --build
```

Open **http://localhost:6081/vnc.html**, connect, and use default VNC password
`mario`. TigerVNC is the X server; do **not** add Xvfb on the same display.
`tigervnc-tools` supplies `tigervncpasswd`. Defaults are local/trusted use only:
no TLS, public default password, Compose publishes on all host interfaces.

- `NOVNC_PORT=6082` selects a different **host** port in Compose; internal noVNC
  remains 6080. In standalone `docker run`, `NOVNC_PORT` instead sets the internal
  listener. See README before sharing a Compose `.env` with standalone Docker.
- `GAME_DISPLAY` selects `dashboard`/`game`/`none`; X11 `DISPLAY` is unrelated.
  `none` skips graphical servers entirely. `compose up` still publishes its port
  but no HTTP server runs in this mode.
- Trailing CLI flags override entrypoint environment defaults. Pass play flags
  directly after the service/image; do not duplicate `typesafe-mario play`.
- Compose persists logs/PNGs with `./artifacts:/app/artifacts`. Keep that mount
  when adding custom ROM mounts. Secrets and caches are excluded by `.dockerignore`.
- Rebuild after source/entrypoint/dependency changes; `compose run` alone reuses
  the image. Do not stop or replace an existing user service without instruction;
  use separate test containers/ports when necessary.
- Compose maps `host.docker.internal` to the Linux host gateway for compatible
  local servers. Host-only loopback listeners may still be unreachable.

## Environment and ROM scope

The tested `gym-super-mario-bros` 9.1.0 registers SMB1
`SuperMarioBros-W-S-v0` for worlds 1–8/stages 1–4, plus `SuperMarioBros-v0`.
Only `v0` is registered there: verify the actual registry on dependency upgrades
instead of recommending old `v1`/`v2`/`v3` variants. The package registers other
games, but this parser/controller/guard is calibrated for SMB1; smoke testing
focuses on World 1-1, not validated equivalent support for SMB2/SMB3.

The installed emulator package bundles game files; the repository itself has no
ROM. The current Python 3.13 image's SMB1 override target is
`/usr/local/lib/python3.13/site-packages/gym_super_mario_bros/_roms/super-mario-bros.nes`.
Use only lawfully obtained game files. Ownership of a cartridge/re-release does
not automatically authorize third-party ROM downloads.

## Continuous documentation maintenance

- English is the canonical language for project documentation and agent instructions.
  Update English first; add translations only when explicitly requested.
- After changes to features, user-visible behavior, setup, configuration, development
  workflows, or durable project instructions, invoke the `documenter` agent defined in
  `.opencode/agents/documenter.md` before completing the task. Include the task scope,
  relevant changes, new instructions, and validation results in the handoff.
- Documenter updates the affected documentation and checks it against the current
  implementation. If the agent is unavailable, perform the same documentation review
  directly. Changes with no documentation impact need only a brief explanation.
