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
  dashboard.py     # pygame telemetry + opt-in action paths; original model probabilities
  trajectories.py  # view-only coarse macro estimates; no emulator rollouts/provider calls
  display.py       # shared RGB scaling + large resizable synchronous game viewer
  actions.py       # controller macros
tests/             # state, backend, CLI, display/paths, dashboard, safety, runner, container
Dockerfile         # Python 3.13 builder/runtime stages + emulator + TigerVNC + noVNC
requirements-docker.txt # pinned Docker runtime dependencies; local extras retain ranges
compose.yml        # service config, 127.0.0.1:6080 -> container 6080, artifacts bind mount
entrypoint.sh
.env.example       # safe configuration template; never commit the real .env
docs/container-maintenance.md # image design, offline checks, SBOM and scanning
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
bash -n entrypoint.sh
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
  calls. `game` draws RGB frames through a resizable pygame viewer at a target
  60 fps, not the native emulator human viewer. It defaults to 1440×810;
  `--game-width`/`--game-height` accept positive initial dimensions, unused in
  other modes. Scaling is nearest-neighbor, aspect-preserving, and letterboxed.
  Esc/Q/close exits gracefully with an episode summary. `none` has no window.
  Game/headless retain synchronous decisions and pause during API requests;
  game window events are handled between calls. Do not equate headless outcomes
  with real-time dashboard results.
- Dashboard paths default off (`--trajectories`/`--no-trajectories`). **F** toggles
  visibility even without the startup flag, and that state survives **Restart**/`R`.
  This view-only exception changes no policy/controller behavior or provider
  calls. `game`/`none` ignore paths; dashboard screenshots include them if visible.
  Policy, safety, display mode, and initial dimensions still require a new
  command/container; episode restart does not reload settings.
- Paths use the fresh displayed RAM/camera snapshot, while weights are from the
  latest completed decision and can be older/pending. Seven colors match bars
  while visible; selected macro is bold, M/white endpoint ring marks the original
  proposal, G marks the guard override. Never rewrite original probabilities or
  call them survival odds. The legend belongs below the image, not over Mario.
- Trajectories hold each macro once for up to 45 frames (0.75 s at 60 fps), with
  simple physics, coarse tiles, and constant enemy horizontal velocity. They can
  overlap/truncate; airborne geometry is unreliable. Contact/unknown/horizon
  markers are illustrative, not survival guarantees. No Jev internal futures,
  emulator clones/rollouts, sequence tree, stomps, enemy AI, re-jumps, controller
  edges, or future guard changes are modeled. Do not draw paths without usable
  geometry/visible position or for parsed dead/cleared states. `screen_x` and
  `screen_y` are display/debug-only, excluded from model-facing JSON.
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
mkdir -p artifacts
export MARIO_UID="$(id -u)" MARIO_GID="$(id -g)"
docker compose build mario

# Free offline dashboard, guard enabled:
docker compose run --rm --service-ports mario --policy heuristic --safety-mode conservative

# Optional view-only paths (run instead of the previous container on that port):
docker compose run --rm --service-ports mario --policy heuristic --trajectories

# Free headless smoke test, no X/VNC/noVNC processes:
docker compose run --rm mario --policy heuristic --display none --max-decisions 25

# Billable AI service only when explicitly intended:
export OPENROUTER_API_KEY="your-openrouter-key"
BACKEND=openrouter POLICY=typesafe SAFETY_MODE=conservative docker compose up --build
```

Open **http://localhost:6080/vnc.html**, connect, and use default VNC password
`mario`. TigerVNC is the X server; do **not** add Xvfb on the same display.
`tigervnc-tools` supplies `tigervncpasswd`. Defaults are local/trusted use only:
no TLS and a public default password. Compose publishes on **127.0.0.1** by default;
`NOVNC_BIND_ADDRESS=0.0.0.0` deliberately exposes the port to other machines,
without adding transport security. Prefer an SSH tunnel for remote access (see
README). The script does not print the VNC password. Repository defaults and
`.env.example` use loopback and host port **6080**; keep machine-specific host
ports/LAN exposure only in the ignored `.env`, not committed defaults or examples.
An existing `.env` can override the browser port/binding; do not read it during
routine documentation validation.

- The image runs as `mario`, UID/GID 1000 by default. `MARIO_UID`/`MARIO_GID`
  are build arguments exposed through Compose; match the intended artifacts owner
  and rebuild after changes. Run host-ID commands above as a normal non-root user.
  Existing root-owned artifacts require a deliberate one-time ownership/permission
  migration; see README. Never chown user artifacts automatically, delete old logs,
  use `chmod 777`, or overwrite a real `.env` during validation.
- `entrypoint.sh` preflights the last `--artifacts-dir PATH`/`--artifacts-dir=PATH`
  before graphics/policy startup, reports actual UID/GID on failure, and makes no
  ownership changes. `--help` skips artifacts/graphics checks.
- Compose uses `init: true`, `read_only: true`, `cap_drop: [ALL]`, and
  `no-new-privileges:true`; `/tmp` is a `rw,nosuid,nodev,mode=1777` tmpfs.
  `HOME=/tmp/mario` holds ephemeral VNC credentials/caches, and X TCP is disabled.
  The artifacts bind stays writable/persistent. Standalone `docker run` inherits
  the non-root image user, not Compose's restrictions; add the corresponding
  flags explicitly (README examples). Custom output/screenshot paths need an
  appropriate writable mount when the root filesystem is read-only.
- `NOVNC_PORT=6082` selects a different **host** port in Compose; internal noVNC
  remains 6080. In standalone `docker run`, `NOVNC_PORT` instead sets the internal
  listener. See README before sharing a Compose `.env` with standalone Docker.
- `GAME_DISPLAY` selects `dashboard`/`game`/`none`; X11 `DISPLAY` is unrelated.
  `none` skips graphical servers entirely. `compose up` still publishes its port
  but no HTTP server runs in this mode.
- `SHOW_TRAJECTORIES=false` controls initial dashboard visibility; accepted values
  are lowercase `true/1/yes/on` and `false/0/no/off`. Invalid values fail startup;
  trailing `--trajectories`/`--no-trajectories` override valid environment defaults.
  The existing `.env.example` intentionally opts in with `SHOW_TRAJECTORIES=true`;
  preserve it rather than confusing that template choice with CLI/Compose defaults.
- `DISPLAY_WIDTH`/`DISPLAY_HEIGHT` default to 1440/810 and set both the TigerVNC
  desktop and initial plain game window size, not the fixed dashboard layout.
  Trailing `--game-width`/`--game-height` override only the window, not the desktop.
- Trailing CLI flags override entrypoint environment defaults. Pass play flags
  directly after the service/image; do not duplicate `typesafe-mario play`.
- Compose persists logs/PNGs with `./artifacts:/app/artifacts`. Keep that mount
  when adding custom ROM mounts. Secrets and caches are excluded by `.dockerignore`.
- Rebuild after source/entrypoint/dependency changes; `compose run` alone reuses
  the image. Do not stop or replace an existing user service without instruction;
  use separate test containers/ports when necessary.
- Compose maps `host.docker.internal` to the Linux host gateway for compatible
  local servers. Host-only loopback listeners may still be unreachable.

### Container maintenance rules

- Keep compilers/development headers in the builder only. Runtime installs normal
  wheels via a BuildKit wheelhouse mount, not editable source. Preserve the
  `/usr/local/lib/python3.13/site-packages/` ROM override path unless documenting
  an intentional migration. Keep Debian's graphical stack, fonts/GLU, Node, and
  distro Python this pass; do not assume they are unused or switch to Alpine.
- Refresh the Python multi-platform base digest and Docker runtime pins together
  for security updates; local `pyproject.toml` ranges are unchanged. APT packages
  and isolated build dependencies are not fully locked: do not call this a fully
  hermetic build or claim a clean scan without running one.
- Follow [container maintenance](docs/container-maintenance.md) for isolated
  offline smoke tests, image measurements, SBOM/scanning, and version refreshes.
  Report measured image bytes separately from APT simulation estimates and build
  cache usage. Never present pending checks as passed, security hardening as
  rootless-Docker verification, or local/mocked checks as provider validation.

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
