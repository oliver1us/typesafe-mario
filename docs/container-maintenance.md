# Container maintenance

[README](../README.md) covers normal use, artifact permissions, and standalone
Docker flags. Run these checks intentionally; no scanning CI is configured here.
Never stop or replace a running user service just to validate an image.
Committed Compose defaults publish noVNC at **127.0.0.1:6080**, forwarding to
container port **6080**. Machine-specific host ports and explicit LAN binding
belong in the ignored `.env`; they are not repository defaults. Prefer the
README's SSH tunnel workflow for remote access: the default password is `mario`,
noVNC has no TLS, and exposing the port does not secure it.

## Image design and update policy

- `Dockerfile` uses a digest-pinned, multi-platform Python 3.13 Debian slim base
  for both builder and runtime. BuildKit is required for the wheelhouse bind mount.
- Native compilers and development headers live only in the builder, providing
  a fallback when compatible emulator/pygame wheels are unavailable. Runtime
  installs normal wheels, not an editable `/app/src` tree. Rebuild to use changed
  source code.
- `requirements-docker.txt` pins Docker's Python runtime dependencies. Local
  `pyproject.toml` dependency ranges and optional SDK behavior are unchanged.
  Refresh the base-image digest and runtime pins with security updates, then run
  `pip check`, tests, registry inspection, and offline headless/graphical checks.
- This is **not a fully hermetic build**: Debian APT packages and isolated Python
  build dependencies are not fully pinned, and native wheel availability differs
  across architectures. A digest must be refreshed to receive base-image fixes.
- The runtime retains TigerVNC, noVNC/websockify, GLU, fonts, Debian's Node, and
  distro Python alongside `/usr/local` Python. This pass does not remove graphical
  features or switch to Alpine. The custom-ROM mount target remains
  `/usr/local/lib/python3.13/site-packages/gym_super_mario_bros/_roms/super-mario-bros.nes`.
- Non-root execution and Compose restrictions reduce exposure; they do not prove
  vulnerability freedom or that Docker itself is running rootless. Record that
  distinction when reporting validation.

## Isolated offline checks

Use your normal non-root host account and a separate image tag/output directory.
The commands below do not change `./artifacts`, `.env`, or the running Compose
service. They require Docker/BuildKit and writable host temporary storage.

```bash
mkdir -p /tmp/opencode
CHECK_DIR="$(mktemp -d /tmp/opencode/mario-container-check.XXXXXX)"
mkdir -p "$CHECK_DIR/artifacts"
docker build --build-arg MARIO_UID="$(id -u)" --build-arg MARIO_GID="$(id -g)" \
  -t typesafe-mario:check .

# Packaging and effective image user; no policy/provider request.
docker run --rm --entrypoint python typesafe-mario:check -m pip check
docker run --rm --entrypoint id typesafe-mario:check
docker run --rm typesafe-mario:check --help

# Free headless emulator check under Compose-equivalent restrictions.
docker run --rm --init --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,mode=1777 \
  -v "$CHECK_DIR/artifacts:/app/artifacts" typesafe-mario:check \
  --policy heuristic --display none --seed 123 --max-decisions 25

# Runtime tests without installing development dependencies into the image.
# Mount the checkout because some tests inspect root-level configuration files.
# Executable /tmp is test-only: entrypoint tests run temporary command stubs.
docker run --rm --init --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,exec,nosuid,nodev,mode=1777 -v "$PWD:/repo:ro" \
  --entrypoint python typesafe-mario:check -m unittest discover -s /repo/tests -p 'test_*.py' -v
```

Docker Compose configuration tests skip if the Docker CLI/plugin is unavailable
inside the image; entrypoint stub tests also skip if the test temporary directory
is non-executable. The test-only `exec` option above avoids the latter skip;
production Compose keeps its `/tmp:rw,nosuid,nodev,mode=1777` configuration unchanged.
Do not mount the Docker socket just to avoid a skip. Run the host suite and
`docker compose config --quiet` separately; the latter validates
without printing interpolated credentials. Report skips separately from passes;
unit tests are not live-provider tests.

For graphical validation, use an unused loopback port (6082 here) and the same
isolated output mount and runtime restrictions:

```bash
docker run --rm --init --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,mode=1777 -p 127.0.0.1:6082:6080 \
  -v "$CHECK_DIR/artifacts:/app/artifacts" typesafe-mario:check \
  --policy heuristic --display dashboard --trajectories \
  --screenshot /app/artifacts/dashboard.png
```

Open `http://localhost:6082/vnc.html` with the configured VNC password (default
`mario`). Check the image and telemetry, **F** visibility, and **R**/Restart; quit
with Esc/Q or Ctrl+C. Repeat with `--display game --game-width 1280 --game-height 720`
instead of the dashboard/path/screenshot options and check resizing. These are
manual acceptance steps, not claims of successful checks in every environment.

## Size, SBOM, and vulnerability checks

Record the size metric and daemon/storage backend, not just a number. On a
containerd-backed daemon, `docker image ls` local disk usage and
`docker image inspect .Size` can report different values. Neither an APT removal
simulation nor aggregate build-cache usage measures the final image. Compare
like metrics on the same architecture; a smaller image is not proof of physical
disk space reclaimed.

```bash
docker image ls typesafe-mario --format '{{.Repository}}:{{.Tag}} {{.Size}}'
docker image inspect typesafe-mario:check --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Size}}'
docker history typesafe-mario:check
```

With **Trivy installed separately**, generate an SBOM and scan the final runtime
image. These commands may download scanner databases but make no model calls:

```bash
trivy image --format cyclonedx --output "$CHECK_DIR/mario-sbom.cdx.json" typesafe-mario:check
trivy image --scanners vuln --format json --output "$CHECK_DIR/mario-vulnerabilities.json" \
  typesafe-mario:check
trivy image --scanners vuln --severity HIGH,CRITICAL --exit-code 1 typesafe-mario:check
```

Retain the image ID/architecture, scanner version/database date, and raw report
with any summary. The severity check can fail: review fixable and unfixed findings
rather than silently filtering them out or claiming all dependencies are safe.
An unavailable scanner or incomplete database download is an unresolved check,
not a clean result. No image-size reduction or scan result is guaranteed by the
Dockerfile structure alone.

## Validation snapshot: 2026-11-07

Scope: **linux/amd64**, isolated `typesafe-mario:lighter-test`, offline heuristic
only. This does not validate other architectures, rootless Docker, or live providers.
This historical snapshot predates the host-port default update; it is not a new
image build, emulator smoke test, or security scan of subsequent revisions.
The tested identities are distinct:

```text
OCI index / docker image inspect .Id:
sha256:7266cc2cc6ecc383f3f67d72ed1f5ae72ea04ce74e592dd202f763fbf6a1cd63
Image config / Trivy Metadata.ImageID:
sha256:42444332e0e0f34cc035f11333ed77258faaee505fa9b7d2275ec807fced06e5
```

### Measured size and functional checks

Both images were measured on the same containerd-backed daemon:

| Metric | Previous `typesafe-mario:trajectory-test` | Candidate `typesafe-mario:lighter-test` |
|---|---|---|
| `docker image ls` local disk usage (rounded) | 1.77 GB | 1.03 GB (about 42% lower) |
| `docker image inspect .Size` (bytes) | 438165194 | 247834200 |

These are different metrics, not interchangeable saving estimates. No physical
disk reclamation was measured.

- Host pytest: **69 passed, 2 skipped, 20 subtests**; graphical tests skipped
  because pygame was absent. Ruff format/check, `bash -n entrypoint.sh`,
  `docker compose config --quiet`, and `git diff --check` passed.
- Final-image unittest: **71 total, 69 passed, 2 skipped**. Only Docker/Compose
  configuration tests skipped; graphical unit tests passed. Entrypoint command
  stubs used the explicitly executable **test-only** tmpfs, with no Docker socket.
- Hardened headless and real-X game smoke checks passed without provider calls.
  Browser validation on isolated `127.0.0.1:6087` authenticated to VNC, rendered
  the dashboard/trajectories, and restarted an episode. Separate real-X checks
  verified the 1440×810 game default, resizing to 1280×720, matching offline
  game/headless records, dashboard **F** toggling and **R** visibility persistence,
  freeze snapshots, screenshots, and two episode summaries.
- Runtime probes confirmed UID/GID `1000:1000`, `CapEff=0`, `NoNewPrivs=1`, HTTP
  200, WebSocket 101, VNC authentication, password-file mode `0600`, absent build
  tools, and the bundled ROM. A separate `1001:1001` build wrote correctly owned
  logs to a temporary bind and rejected an unwritable bind before startup with
  UID/GID guidance, without changing permissions.

### Security scan: findings remain

**The image is not vulnerability-free.** Trivy **0.76.2** scanned the exact image
export `/tmp/opencode/mario-lighter-final.tar` without a Docker socket, using:

```text
aquasec/trivy:0.76.2@sha256:8f6bb947dbc528902e11f2f5be52f7b519f6a39d5d148f41166f2040499768fb
```

Report creation: `2026-11-07T12:10:30.881637474Z`; database updated:
`2026-11-07T06:54:25Z`. Findings were **6 CRITICAL, 127 HIGH, 186 MEDIUM,
144 LOW, 11 UNKNOWN**: 474 package/advisory occurrences across 259 unique
advisory IDs, not 474 unique CVEs. CRITICAL occurrences were `libxml2` (1) and
`node-undici` (5). Distro findings had no `FixedVersion` in this report; this
does not establish safety or reachability.

Eight occurrences with reported fixes concerned pip **26.2.2**'s vendored
`msgpack 1.1.2`, `setuptools 70.3.0`, and `urllib3 2.7.0`, verified against
`/usr/local/lib/python3.13/site-packages/pip/_vendor/vendor.txt`. These are not
standalone application dependencies; adding newer standalone pins does not
replace pip's vendored copies. Findings remain unresolved; no fix or
non-reachability claim is made, and the retained graphical stack was not removed.

The report-generation command returned 0 because it was **not a severity gate**.
CycloneDX SBOM generation also succeeded, but disables vulnerability scanning by
default; the separate vulnerability report supplies the findings above.
Session-local external evidence, **not checked into this repository**:

- `/tmp/opencode/lighter-audit/trivy-final.json`
- `/tmp/opencode/lighter-audit/mario-sbom.cdx.json`
- `/tmp/opencode/lighter-audit/display-smoke-output/`

During this snapshot's validation, no real `.env` was inspected or modified, no
paid calls or ownership migration were performed, and the existing user service
was left untouched. At that time, `./artifacts` was root-owned `0:0`, mode `755`.
For subsequent Compose runs, review current artifacts ownership, create the
directory as the normal non-root host user if absent, and set matching
`MARIO_UID`/`MARIO_GID`; rebuild if those build arguments change. The README
migration guidance applies to existing root-owned binds.
