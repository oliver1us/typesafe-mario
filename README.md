# TypeSafe Mario

An experimental controller for the original Super Mario Bros., using TypeSafe's
Jev decision model or an offline heuristic. This fork adds direct/OpenRouter/local
System One transports, an optional conservative controller guard, dashboard action
trajectories, a resizable plain game viewer, and Docker/noVNC.

The model receives **structured JSON from emulator RAM, not screenshots**. It
chooses a controller macro; the optional guard can change that macro using fresh
RAM before each emulator frame. Neither model confidence nor conservative mode
guarantees survival. This is an inference harness, not a training pipeline.

```text
NES emulator -> RAM parser -> structured JSON -> policy -> optional guard -> controller
                  ^                                    |
                  +-------------- next frame ----------+
```

## Quick start: Docker, no API key

Requires a BuildKit-enabled Docker Engine and a recent Docker Compose v2
supporting optional `env_file` entries. No host Python installation is needed.
Run the commands as your normal non-root host user. For an existing, especially
root-owned `artifacts` directory, follow the [one-time permissions migration](#artifact-permissions-and-upgrading)
before starting a container.

```bash
# Match the image user to the host owner of the writable output directory (Linux).
mkdir -p artifacts
export MARIO_UID="$(id -u)" MARIO_GID="$(id -g)"
docker compose build mario
docker compose run --rm --service-ports mario --policy heuristic --safety-mode off

# Optional approximate action trajectories; still offline, with no API calls.
# Run this instead of the previous container, not on the same occupied port.
docker compose run --rm --service-ports mario --policy heuristic --trajectories --safety-mode off
```

Open **http://localhost:6080/vnc.html**, click **Connect**, and enter the default
VNC password **`mario`**. Press **R** or click **Restart** to reset an episode;
press **F** to show/hide approximate action trajectories, and **Esc** or **Q** to
quit. **F** works even without `--trajectories`; its visibility setting survives
episode restarts. The dashboard stays open after an episode ends. Stop an attached
container with **Ctrl+C**. Policy, safety settings, and display mode still require
a new command/container.

Compose defaults to **127.0.0.1:6080**, forwarding to noVNC's internal **6080**.
An existing ignored `.env` can override the host port and binding; use its
configured port in the browser URL. If occupied, prefix the command with
`NOVNC_PORT=6082` and open port 6082 instead. Do not start two containers on the
same published port. Rebuild after source/entrypoint changes: `docker compose run`
by itself reuses the existing image.

**Security:** Compose publishes on **127.0.0.1 only** by default. The VNC password
is still public and noVNC has no TLS. Explicit `NOVNC_BIND_ADDRESS=0.0.0.0` exposes
the port to other machines; it does not secure the connection. Prefer an SSH
tunnel for remote access, keeping the remote service bound to loopback:

```bash
# Run on your client; assumes the remote host uses the default noVNC port.
ssh -N -L 6080:127.0.0.1:6080 user@host
```

Then open **http://localhost:6080/vnc.html** on the client. An authenticated TLS
proxy is another option. `VNC_PASSWORD` changes the password, not transport
security. Keep machine-specific port/LAN overrides in your ignored `.env`, not
the committed defaults.

## Local installation and commands

Requires Python **3.13+**. The Mario extras include the native `nes-py` emulator;
a C/C++ build toolchain may be needed. Dashboard/game modes need a graphical
session; headless mode does not.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[mario,dev]"

# Inspect example model-facing JSON and debug text; no emulator/API call.
typesafe-mario state-demo

# Offline smoke test; no provider credentials or API costs.
typesafe-mario play --policy heuristic --display none --max-decisions 25

# Offline dashboard, with and without the optional guard.
typesafe-mario play --policy heuristic --display dashboard --safety-mode off
typesafe-mario play --policy heuristic --display dashboard --safety-mode conservative

# View-only approximate paths; F toggles them without changing the controller.
typesafe-mario play --policy heuristic --display dashboard --trajectories

# Large plain game window; resize it or set its initial dimensions explicitly.
typesafe-mario play --policy heuristic --display game --game-width 1280 --game-height 720

# AI dashboard: this and other typesafe-policy runs can incur API charges.
export OPENROUTER_API_KEY="your-openrouter-key"
typesafe-mario play --policy typesafe --backend openrouter --display dashboard \
  --safety-mode conservative --min-confidence 0.8 --danger-threshold 0.5 \
  --safety-margin-frames 6

# Plain game window, no telemetry dashboard; disable the guard explicitly.
typesafe-mario play --policy typesafe --backend openrouter --display game --safety-mode off

# Disable all windows; fixed seed and decision budget.
typesafe-mario play --policy typesafe --backend openrouter --display none \
  --seed 123 --frames-per-decision 8 --max-decisions 100 --safety-mode conservative
```

On Windows PowerShell, create the environment with `py -3.13 -m venv .venv`,
activate with `.venv\Scripts\Activate.ps1`, and set credentials with
`$env:OPENROUTER_API_KEY = "your-openrouter-key"`. Then use the same CLI commands.
The SDK is **optional**: `python -m pip install -e ".[typesafe]"` adds its question
types, but HTTP transport also works without it.

### Display modes change execution timing

| `--display` | Behavior |
|---|---|
| `dashboard` (default) | Combined game/telemetry window, targeted at 60 fps. Requests run asynchronously; the world keeps advancing while a response is pending. |
| `game` | Resizable pygame game-only window, initially 1440×810, drawing RGB frames at a target 60 fps. Decisions remain synchronous; the world pauses during API calls. |
| `none` | No window. Same synchronous decision loop as `game`; suitable for repeatable offline smoke tests. |

Conservative mode reevaluates RAM each emulator frame in all modes, including
while a dashboard request is pending. Headless results are **not** a measurement
of real-time dashboard performance. `--frames-per-decision` is the minimum request
cadence in the dashboard; slow API calls can make the actual cadence longer.

The plain game viewer replaces the native 256×240 emulator window. It uses
nearest-neighbor scaling with the source aspect ratio preserved, so side/top bars
are normal rather than stretching or cropping the game. `--game-width` and
`--game-height` set positive initial pixel dimensions **only for `game`**, not the
dashboard layout. **Esc**, **Q**, or closing the game window ends the run gracefully
and writes an episode summary; unlike the dashboard, it does not stay open for an
episode restart. A pending synchronous policy call must finish before window
events can be handled.

### CLI reference

Use `typesafe-mario --help` and `typesafe-mario play --help` for the full interface.

| Play option | Default | Meaning |
|---|---|---|
| `--policy typesafe\|heuristic` | `typesafe` | AI judgments or the offline smoke-test controller. |
| `--backend auto\|direct\|openrouter\|ollama` | `auto` | AI transport; ignored by the heuristic. |
| `--model ID` | Backend-specific | Override the model ID. |
| `--base-url URL` | Backend-specific | **Full** System One endpoint URL, not a chat endpoint. |
| `--env ID` | `SuperMarioBros-1-1-v0` | Registered Gymnasium environment. |
| `--seed N` | `123` | Initial environment-reset seed. |
| `--frames-per-decision N` | `8` | Positive nominal macro length/request cadence in emulator frames. |
| `--max-decisions N` | `2000` | Positive decision limit per episode; not a wall-clock timeout. |
| `--display dashboard\|game\|none` | `dashboard` | Telemetry window, plain game, or no window. |
| `--game-width N`, `--game-height N` | `1440`, `810` | Positive initial plain game window dimensions; unused by dashboard/headless modes. |
| `--trajectories`, `--no-trajectories` | Disabled | Initial dashboard action-path visibility; **F** toggles it at runtime. Ignored in `game`/`none`. |
| `--safety-mode off\|conservative` | `off` | Opt in to the local guard. |
| `--min-confidence F` | `0.8` | Walk instead of ground-running below this model confidence. |
| `--danger-threshold F` | `0.5` | Walk instead of ground-running at/above normalized danger. |
| `--safety-margin-frames N` | `6` | Nonnegative extra reaction margin. |
| `--artifacts-dir PATH` | `artifacts` | JSONL output directory. Container entrypoint defaults to `/app/artifacts`. |
| `--screenshot PATH` | Disabled | Save the first populated dashboard frame as PNG, including trajectories if visible; dashboard only. |

Both threshold flags accept fractions **0–1**, not percentages: use `0.8`, not
`80`. **Restart** only resets the episode and does not reload CLI flags or
environment variables. Policy, safety, display mode, and initial dimensions need
a new command; dashboard trajectory visibility is the view-only **F** exception.

### Dashboard trajectories: approximate, view-only

Enable with `--trajectories` (default **off**) or press **F** in the dashboard.
Seven colored dashed paths show a cheap estimate for holding each legal macro
once, for **up to 45 frames (0.75 seconds at 60 fps)**. They use simple acceleration,
gravity and inertia, coarse local tiles, and constant enemy horizontal velocity.
They are **not Jev's internal futures**, emulator clones/rollouts, or an
action-sequence tree. Enabling or toggling them adds no provider calls and changes
neither policy decisions nor controller behavior. No extra dependencies are needed
beyond the existing Mario extras.

- Paths start at Mario in the current displayed frame using fresh RAM position
  and camera coordinates. Probability weights come from the **latest completed
  decision**, which can be older than that frame while another response is pending.
- The legend sits below the game image. Colors match the probability bars while
  the overlay is visible; the selected macro is bold. **M** marks the original
  policy/model proposal, also shown by a white endpoint ring; **G** marks the guard's
  macro when it overrides that proposal. Original probabilities are unchanged:
  they are **not survival odds**. The free heuristic's weights are one-hot, not
  learned predictions.
- Paths end early at blocking solid or possible enemy contact (**×**), or at
  unknown geometry/the horizon (**○**). No paths are drawn without usable local
  geometry and visible position, or when the parsed state is dead/cleared.
- Paths can overlap or truncate almost immediately. Airborne tile geometry is
  especially unreliable. Stomps, enemy AI, repeated jumps, controller button
  release/repress edges, and future guard interventions are not modeled. Neither
  a clear-looking path nor its weight guarantees survival.

The overlay is dashboard-only; `game` and `none` ignore these flags. A dashboard
`--screenshot` includes it only if visible when the first populated frame is saved.

## AI backends

All transports send System One `state` and `questions` to `/v1/systemone`. An
OpenAI-compatible chat-completions endpoint alone is **not** sufficient.

| Backend | Default full endpoint | Credential | Default model |
|---|---|---|---|
| `direct` | `https://api.typesafe.ai/v1/systemone` | `TYPESAFE_API_KEY` | `jev-latest` |
| `openrouter` | `https://openrouter.ai/api/v1/systemone` | `OPENROUTER_API_KEY` | `typesafe/jev-1.13` |
| `ollama` | `http://localhost:11434/v1/systemone` | Optional `OLLAMA_API_KEY` | `nimble` |

Local CLI `auto` chooses a nonempty `TYPESAFE_API_KEY`, then
`OPENROUTER_API_KEY`, otherwise `ollama`. The Docker entrypoint/Compose default is
**`openrouter`**, not `auto`.

```bash
# TypeSafe direct; requires an account/key with access to the endpoint/model.
export TYPESAFE_API_KEY="your-typesafe-key"
typesafe-mario play --backend direct --model jev-latest --display dashboard

# Override the complete endpoint, keeping OpenRouter's model/key selection.
# Only send credentials to a server you trust.
typesafe-mario play --backend openrouter \
  --base-url https://your-systemone-proxy.example/v1/systemone --display none --max-decisions 25

# ONLY with a server explicitly implementing the System One protocol.
OLLAMA_HOST=http://localhost:11434 typesafe-mario play --backend ollama \
  --model nimble --display none --max-decisions 25
```

`OLLAMA_HOST` controls the `ollama` host; `/v1/systemone` is appended. Installing
stock Ollama or pulling a chat model does **not** establish compatibility with
this protocol. The `nimble` string is a transport default, not a verified model
availability claim. Live Ollama and direct-provider compatibility have not been
validated in this change. A 404 can mean an unsupported endpoint as well as a
bad model ID.

Prefer an explicit backend with `--base-url`: this retains that backend's model
and credential variable. `--backend auto --base-url ...` instead selects a custom
transport with default model `jev-latest` and no automatically selected key.
There is no chat-protocol adapter. For AI without OpenRouter, choose `direct`
with `TYPESAFE_API_KEY`, or `ollama` with an explicitly compatible server. For
**no APIs at all**, use `--policy heuristic`; it ignores backend/model/URL and
credential settings and never calls a provider.

## Conservative mode: opt-in, not a survival promise

`--safety-mode off` is the default and bypasses the guard. In `conservative` mode:

- Fresh grounded geometry can replace a proposal with `right_run_jump` for a
  nearby gap, obstacle, threatening enemy, or blocked forward movement.
- Enemy timing uses cadence plus measured response delay (that sum capped at
  12 frames), the configurable margin, eight clearance frames, and player width.
  Grounded terrain lookahead is capped at three tiles to limit premature jumps.
- Over a known gap, the guard preserves forward momentum; it also holds a rising
  forward jump rather than prematurely releasing the jump button.
- On otherwise open ground, only `right_run` becomes `right` when confidence is
  **below** `min_confidence` or normalized danger is **at least** the threshold.
  Normalized danger is the model's three-level score divided by two. Uncertainty
  alone does not invent a jump, stop every action, or brake an airborne crossing.

The dashboard shows the guard-selected action and override reason separately
from the **original** model confidence/probabilities. These probabilities are not
survival odds. The heuristic always reports confidence `1.0` and no danger score,
so changing `--min-confidence` cannot tune its behavior; geometry rules still apply.

For example, `--min-confidence 0.9 --danger-threshold 0.4
--safety-margin-frames 8` makes the relevant walking/anticipation rules trigger
earlier. More conservative thresholds are not necessarily better: slowing or
jumping too early can also cause death. The guard is a local rule set, not a
trained improvement to Jev, and cannot guarantee level completion.

## Docker Compose workflows

Optional configuration: copy `.env.example` to `.env` **only if you do not already
have one**, add a provider key only for a remote AI backend, and keep it untracked.
Compose loads `.env`; the local Python CLI does not. Shell variables override
Compose's `.env` values. The build context excludes `.env`, artifacts, and common caches.
The template opts into `SHOW_TRAJECTORIES=true`; without that setting, Compose
and the CLI default to hidden paths. If you persist `MARIO_UID`/`MARIO_GID` in an
existing `.env`, use your actual output-directory owner IDs, not necessarily the
template's `1000` values. Rebuild after changing them.

**Offline `.env` setup:** set `POLICY=heuristic` and leave API keys blank.
`BACKEND=openrouter` can remain: provider settings are ignored by the heuristic.
`BACKEND=none` is not valid; leaving `BACKEND` blank defaults to `openrouter`,
not offline mode.

```bash
# Offline dashboard with the guard enabled.
docker compose run --rm --service-ports mario --policy heuristic --safety-mode conservative

# Same free controller with approximate paths; F toggles visibility.
docker compose run --rm --service-ports mario --policy heuristic --safety-mode conservative \
  --trajectories

# AI service with explicit startup settings (provider usage may be billable).
export OPENROUTER_API_KEY="your-openrouter-key"
BACKEND=openrouter POLICY=typesafe GAME_DISPLAY=dashboard SAFETY_MODE=conservative \
  MIN_CONFIDENCE=0.8 DANGER_THRESHOLD=0.5 SAFETY_MARGIN_FRAMES=6 docker compose up --build
# Stop the service when finished:
docker compose down

# Plain game in the browser; no telemetry dashboard, guard disabled.
docker compose run --rm --service-ports mario --policy heuristic --display game --safety-mode off

# Change both the virtual desktop and initial game size through the environment.
GAME_DISPLAY=game DISPLAY_WIDTH=1280 DISPLAY_HEIGHT=720 POLICY=heuristic docker compose up

# Headless: no X server, VNC or noVNC is started; no browser connection is expected.
docker compose run --rm mario --policy heuristic --display none --safety-mode conservative \
  --seed 123 --frames-per-decision 8 --max-decisions 100

# Another level and a PNG of the dashboard; host files persist under ./artifacts.
docker compose run --rm --service-ports mario --policy heuristic --env SuperMarioBros-1-2-v0 \
  --display dashboard --safety-mode conservative --trajectories \
  --screenshot /app/artifacts/dashboard.png
```

Append play flags after `mario`; do **not** add `typesafe-mario play` because the
entrypoint already supplies it. Trailing CLI flags override environment defaults,
so these examples work even if `.env` selects another policy/display/safety mode.
To change the running Compose service, stop/recreate it with the new settings;
there is no in-game safety toggle. Only trajectory visibility has a runtime **F**
toggle. Run browser examples one at a time on a given published port.
`docker compose up` still publishes its port in headless mode, but no HTTP server
listens there.

### Container configuration

These are entrypoint/Compose settings, not automatic local CLI configuration.

| Environment variable | Default | Purpose |
|---|---|---|
| `POLICY` | `typesafe` | `typesafe` or `heuristic`. |
| `BACKEND` | `openrouter` | `auto`, `direct`, `openrouter`, or `ollama`. |
| `OPENROUTER_API_KEY`, `TYPESAFE_API_KEY` | Empty | Selected remote backend credential. |
| `MODEL`, `BASE_URL` | Unset | Model override and full System One endpoint override. |
| `OLLAMA_HOST` | Compose: `http://host.docker.internal:11434`; local CLI: `http://localhost:11434` | Only for a compatible System One server. |
| `OLLAMA_API_KEY` | Unset | Optional local-server bearer token; supply through `.env`/`env_file` or `docker compose run -e OLLAMA_API_KEY`. |
| `GAME_DISPLAY` | `dashboard` | `dashboard`, `game`, or `none`; do not use X11's `DISPLAY` for this. |
| `SHOW_TRAJECTORIES` | `false` | Initial dashboard overlay visibility: `true/1/yes/on` or `false/0/no/off` (lowercase); other values fail startup. Trailing `--trajectories`/`--no-trajectories` override valid defaults. |
| `SAFETY_MODE` | `off` | `off` or `conservative`. |
| `MIN_CONFIDENCE` | `0.8` | Model-confidence walking threshold. |
| `DANGER_THRESHOLD` | `0.5` | Normalized-danger walking threshold. |
| `SAFETY_MARGIN_FRAMES` | `6` | Extra reaction margin; about 100 ms at 60 fps. |
| `FRAMES_PER_DECISION`, `MAX_DECISIONS` | `8`, `2000` | Cadence/macro length and episode decision limit. |
| `SEED`, `ENV_ID` | `123`, `SuperMarioBros-1-1-v0` | Initial reset seed and level. |
| `DISPLAY_WIDTH`, `DISPLAY_HEIGHT` | `1440`, `810` | Positive TigerVNC desktop dimensions and initial `game` window size; dashboard layout remains fixed. |
| `VNC_PORT` | `5901` | Internal loopback-only TigerVNC port. |
| `NOVNC_PORT` | `6080` | Compose host port; internal noVNC stays `6080`. In `docker run`, this variable instead sets the internal listener. |
| `NOVNC_BIND_ADDRESS` | `127.0.0.1` | Compose host binding only. Explicit `0.0.0.0` allows LAN exposure; no TLS is added. Standalone Docker uses `-p` instead. |
| `MARIO_UID`, `MARIO_GID` | `1000`, `1000` | **Build arguments**, passed by Compose from shell/`.env`. Set the image's non-root `mario` user/group; rebuild to change them. |
| `VNC_PASSWORD` | `mario` | Script default, not baked into image environment or printed at startup. Classic VNC authentication, no TLS; local/trusted access only. |

For example, `SHOW_TRAJECTORIES=true POLICY=heuristic docker compose up` starts an
offline dashboard with paths, unless `GAME_DISPLAY` selects another mode. Append
`--no-trajectories` to a `docker compose run ... mario` command to start with them
hidden. Trailing `--game-width 960 --game-height 720` overrides the initial game
window dimensions but does **not** resize the TigerVNC desktop; use
`DISPLAY_WIDTH`/`DISPLAY_HEIGHT` when changing both.

Compose binds **`./artifacts:/app/artifacts`**, so logs/PNGs survive container
removal. A `--artifacts-dir` outside that mount needs another writable mount;
the Compose root filesystem is read-only, and `/tmp` is ephemeral. Keep screenshots
under `/app/artifacts` too.
For a compatible host-side System One server, Compose supplies the
`host.docker.internal` host-gateway mapping; the host service must be reachable
from the container, not bound exclusively to host loopback.

### Artifact permissions and upgrading

The image now runs as **`mario` (UID/GID 1000 by default)** instead of root. Bind
mounts retain host ownership; the image's `/app/artifacts` ownership cannot fix
the mounted directory. Existing logs are not deleted or automatically chowned.
For example, a root-owned `0:0` directory with mode `755` is not writable by a
host-matched `1001:1001` container user.

On Linux, inspect ownership, then deliberately migrate **only the artifacts
directory** if it should belong to your current account. Do not run this against
an unrelated output directory or while another container is writing there:

```bash
id -u; id -g
mkdir -p artifacts
ls -ldn artifacts

# One-time ownership adjustment, only after reviewing the directory above.
# Preserves the files; do not use chmod 777 or delete logs to work around this.
sudo chown -R "$(id -u):$(id -g)" ./artifacts
export MARIO_UID="$(id -u)" MARIO_GID="$(id -g)"
docker compose build mario
```

Keep those build settings in your shell or update the corresponding entries in
your existing `.env` for future rebuilds. Alternatively, keep UID/GID 1000 and
deliberately grant that account write access to the output directory. Docker
Desktop bind permissions can differ; verify writability rather than assuming
numeric IDs alone are sufficient.

`entrypoint.sh` checks the final `--artifacts-dir PATH` or `--artifacts-dir=PATH`
before starting graphics or the policy. If creation/write access fails, startup
exits with the actual container UID/GID and a permissions hint; it never changes
ownership. `--help` bypasses the artifacts/graphics checks. Custom output mounts
need the same permission review. See [container maintenance](docs/container-maintenance.md)
for the image design, offline validation, and security scanning commands.

Compose also enables an init process, a read-only root filesystem, drops all
Linux capabilities, and sets `no-new-privileges`. Its writable `/tmp` tmpfs uses
`rw,nosuid,nodev,mode=1777`; `HOME=/tmp/mario` keeps VNC credentials and caches
ephemeral. Only the artifacts bind is persistent writable application storage.
TigerVNC stays on container loopback and X11 TCP listening is disabled. These
restrictions reduce exposure but are not a substitute for network security.

### Standalone `docker run`

Create the host artifacts directory and build a named image with matching IDs
(Linux, normal non-root host account). Existing directories still need the
[permissions migration](#artifact-permissions-and-upgrading). The following
examples keep the image's internal port at 6080 and publish host 6080 only on
loopback; the same browser URL/password applies. The image's non-root user is
automatic, but Compose's runtime restrictions are **not** image defaults.

```bash
mkdir -p artifacts
docker build --build-arg MARIO_UID="$(id -u)" --build-arg MARIO_GID="$(id -g)" \
  -t typesafe-mario:local .

# Offline dashboard; turn the guard off by replacing conservative with off.
docker run --rm --init -it -p 127.0.0.1:6080:6080 \
  -v "$PWD/artifacts:/app/artifacts" typesafe-mario:local \
  --policy heuristic --display dashboard --safety-mode conservative

# AI controller with tuning and a different SMB1 level.
export OPENROUTER_API_KEY="your-openrouter-key"
docker run --rm --init -it -p 127.0.0.1:6080:6080 -e OPENROUTER_API_KEY -e BACKEND=openrouter \
  -v "$PWD/artifacts:/app/artifacts" typesafe-mario:local \
  --policy typesafe --display dashboard --env SuperMarioBros-1-2-v0 \
  --safety-mode conservative --min-confidence 0.8 --danger-threshold 0.5 --safety-margin-frames 6

# Large plain game window via noVNC; guard disabled, no API calls.
docker run --rm --init -it -p 127.0.0.1:6080:6080 \
  -v "$PWD/artifacts:/app/artifacts" typesafe-mario:local \
  --policy heuristic --display game --safety-mode off

# Offline headless run with the same runtime restrictions as Compose.
docker run --rm --init --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,mode=1777 \
  -v "$PWD/artifacts:/app/artifacts" typesafe-mario:local \
  --policy heuristic --display none --safety-mode conservative --seed 123 --max-decisions 100
```

`--init` reaps graphical helper processes. Add the headless example's
`--read-only`, `--tmpfs`, `--cap-drop`, and `--security-opt` flags to any standalone
graphical command for Compose-equivalent restrictions; they are optional with
`docker run`. A read-only root needs writable `/tmp` and artifacts mounts.

For direct access use `-e TYPESAFE_API_KEY -e BACKEND=direct`; `--model` and
`--base-url` work as above. For a compatible host-local endpoint on Linux, add
`--add-host host.docker.internal:host-gateway -e BACKEND=ollama
-e OLLAMA_HOST=http://host.docker.internal:11434`. Do not blindly use the Compose
`.env` as a standalone `--env-file`: a `NOVNC_PORT` override denotes the **host**
port in Compose but changes the **internal** listener in `docker run`. Likewise,
`NOVNC_BIND_ADDRESS` does not replace an explicit standalone `-p` host binding.

## Levels and game files

The current `gym-super-mario-bros` **9.1.0** registry provides SMB1 IDs
`SuperMarioBros-W-S-v0` (worlds **1–8**, stages **1–4**) and
`SuperMarioBros-v0` for the non-stage-specific environment. For example:

```bash
typesafe-mario play --policy heuristic --env SuperMarioBros-8-4-v0 --display none
ENV_ID=SuperMarioBros-1-3-v0 POLICY=heuristic docker compose up
```

Only **`v0`** is registered in the currently tested package; do not assume the
older `v1`/`v2`/`v3` variants exist. Local dependency ranges are not a lockfile;
Docker uses `requirements-docker.txt` pins. Inspect the actual installed registry
when upgrading either:

```bash
python -c 'import gym_super_mario_bros, gymnasium as gym; print("\n".join(sorted(x for x in gym.registry if x.startswith("SuperMarioBros"))))'
# Without host Python, use the Compose-built image:
docker compose run --rm --no-deps --entrypoint python mario -c \
  'import gym_super_mario_bros, gymnasium as gym; print("\n".join(sorted(x for x in gym.registry if x.startswith("SuperMarioBros"))))'
```

The package also registers SMB2/Lost Levels, SMB2 USA, and SMB3 IDs. This harness's
RAM parser, action set, and guard are calibrated for **SMB1**, with smoke testing
focused on World 1-1. Other games/levels are not validated equivalents; selecting
an ID is not a claim of reliable play or correct parsing there.

No ROM is checked into this repository. The installed emulator package bundles
game files under `gym_super_mario_bros/_roms/`, so the current image does not need
a separate ROM mount. You remain responsible for lawful use. To substitute your
own legally obtained SMB1 dump, add this mount to a `docker run` command above:

```bash
-v "$PWD/my-roms/super-mario-bros.nes:/usr/local/lib/python3.13/site-packages/gym_super_mario_bros/_roms/super-mario-bros.nes:ro"
```

For Compose, add the same source/target to the service's existing `volumes` list,
**keeping the artifacts mount**. The site-packages path follows the image's
Python 3.13 version; check it again if changing the base image. Owning an official
re-release does not itself grant permission to download arbitrary ROM copies.

## State, judgments, and logs

The model-facing JSON groups `player`, `trajectory`, `hazard`, `terrain`,
`reaction_timing`, `recent_control`, and `episode`. It contains motion, jump phase,
upcoming enemy timing, terrain reliability, measured response age, recent-control
outcomes, and progress. The local tile grid/debug text remains in logs/UI rather
than being duplicated in model input. The trajectory overlay's display-only
`screen_x`/`screen_y` coordinates are in debug data, **not** model-facing JSON; the
existing model-state `trajectory` group is not a set of forecast paths.

The AI asks three judgments over the same state: **Choice** selects an action,
**Noul** estimates the usefulness of a forward jump, and **Score** estimates
immediate danger. Legal macros are `noop`, `right`, `right_jump`, `right_run`,
`right_run_jump`, `jump`, and `left`. Timing arithmetic stays in code; the optional
guard is an explicit scripted intervention, not a new model judgment. The
controller also manages jump-button release/repress edges for repeat takeoffs,
without releasing A on the first still-grounded takeoff frame. Console decision
lines include `guard=<reason>` when the guard intervenes at response/macro start;
per-frame interventions remain available through the override events below.

Runs write `artifacts/run-<UTC-timestamp-with-microseconds>.jsonl` by default:

- `decision`: request `state`, debug views, actuation `control_state`,
  guard-selected `action` versus original `proposed_action`, confidence,
  probabilities, jump/danger judgments, latency, reward, and termination flags.
- `safety_override`: frame, fresh state, original/guard-selected actions, and
  reason when an intervention starts or its action/reason changes. It is not a
  record of every individual guarded frame.
- `episode_summary`: `best_progress`, `dead`, `stage_clear`, termination flags,
  decision count, `safety_interventions` (the override transitions above, not
  guarded-frame count), and the complete `safety_config`.

A dashboard restart adds another episode to the same log. Older logs may have
only decision records with no `event` field or summary; consumers must handle
this schema change. Decision actions describe the guard's macro at response/
macro start, not every subsequent input or jump-button release frame. Use
override events to audit intervening guard changes. An interrupted/crashed run
may lack a final summary. There is no `run_start` event or complete CLI-configuration
record: keep the command, seed, environment, cadence, backend, and model alongside
logs when comparing runs. Logs contain game state, not API credentials, but review
files before sharing.

### Reproduce a small off/on comparison

Use the same policy, environment, seed, cadence, decision budget, and display
mode; change only safety configuration. This offline example makes no API calls:

```bash
for mode in off conservative; do
  typesafe-mario play --policy heuristic --display none --env SuperMarioBros-1-1-v0 \
    --seed 123 --frames-per-decision 8 --max-decisions 2000 --safety-mode "$mode" \
    --artifacts-dir "artifacts/compare-$mode"
done

python - <<'PY'
import json
from pathlib import Path

for mode in ("off", "conservative"):
    for path in sorted(Path(f"artifacts/compare-{mode}").glob("run-*.jsonl")):
        for line in path.read_text().splitlines():
            record = json.loads(line)
            if record.get("event") == "episode_summary":
                print(mode, path.name, {key: record[key] for key in
                      ("best_progress", "dead", "stage_clear", "decisions", "safety_interventions")})
PY
```

The synchronous upper frame budget is `max_decisions × frames_per_decision`
(2000 × 8 here), with earlier termination possible. Real-time API latency makes
dashboard budgets differ. Repeat across seeds/levels before drawing conclusions;
for `typesafe`, both comparison runs can incur API costs. A previous image's
headless sanity check with these settings produced:

| Safety | Best progress | Decisions | Interventions | Outcome |
|---|---|---|---|---|
| `off` | 315 px | 14 | 0 | Died; no stage clear |
| `conservative` | 1672 px | 84 | 28 | Died; no stage clear |

That single deterministic heuristic comparison is **not** statistical evidence
of improved AI play. No paid API calls or trained-model improvement were validated
for this change.

## Development and troubleshooting

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m pytest -q
ruff format --check src tests
ruff check src tests
bash -n entrypoint.sh
docker compose config --quiet
```

See [container maintenance](docs/container-maintenance.md) for isolated image
checks, dependency refreshes, SBOM generation, and vulnerability scanning. These
are local workflows, not an automatically configured CI pipeline.

| Symptom | Check |
|---|---|
| HTTP 401/403 | The credential for the explicitly selected backend; `auto` prefers the direct key when both exist. |
| HTTP 404 | Full System One endpoint and compatible model; this is not a chat-completions client. OpenRouter defaults to `typesafe/jev-1.13`. |
| Local-server connection refused | Server reachability and explicit `/v1/systemone` support. In Docker, `localhost` is the container, not the host. |
| `Artifacts directory is not writable` | Review the reported UID/GID, host bind ownership, and [one-time migration](#artifact-permissions-and-upgrading). Match build IDs and rebuild; do not use `chmod 777`. |
| Browser cannot connect | Correct host port (Compose default 6080; shell/`.env` can override it), loopback binding or protected remote tunnel, container still running, and `GAME_DISPLAY`/`--display` not `none`. |
| noVNC black screen | Allow startup time; inspect `docker compose logs mario` or attached run output for TigerVNC/application failures. |
| Plain game looks tiny | Rebuild after this viewer change. `--display game` now defaults to a resizable 1440×810 pygame window, not the native 256×240 viewer. Set `--game-width`/`--game-height`; in Docker, `DISPLAY_WIDTH`/`DISPLAY_HEIGHT` also set the desktop. |
| Bars around the game or unchanged dashboard size | Aspect-preserving scaling intentionally leaves bars. Game-size flags do not change the fixed dashboard layout or the VNC desktop. |
| No action trajectories | Use `--display dashboard` and press **F** or start with `--trajectories`. Missing/offscreen position, unknown geometry, or dead/cleared states can suppress paths; `game`/`none` never show them. |
| Trajectories seem short, overlapping, or stale | Coarse geometry/contact truncates paths; weights are from the latest completed decision, not necessarily the current frame. They are approximate illustrations, not rollouts or survival odds. |
| `tigervncpasswd: command not found` | Rebuild the current image; `tigervnc-tools` provides this utility. |
| Port already allocated | Stop your own conflicting container or choose another `NOVNC_PORT`; do not disrupt an unrelated service. |
| Fonts unavailable | pygame uses available fallback fonts; this does not require API credentials. |

TigerVNC supplies the virtual X display itself; the image does **not** run Xvfb.
Latency depends on provider/model/network and display mode; no historical
latency number is a current performance guarantee.
