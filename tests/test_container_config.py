from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ContainerConfigTests(unittest.TestCase):
    def test_runtime_dependencies_are_pinned_without_changing_local_extras(self):
        lock = (ROOT / "requirements-docker.txt").read_text()
        pins = [line for line in lock.splitlines() if line and not line.startswith("#")]
        self.assertTrue(all(re.fullmatch(r"[\w-]+==[\w.]+", line) for line in pins))
        names = {line.split("==")[0].lower().replace("_", "-") for line in pins}
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
        for dependency in project["optional-dependencies"]["mario"]:
            name = re.split(r"[<>=!~\[]", dependency)[0].lower().replace("_", "-")
            self.assertIn(name, names)
        self.assertNotIn("typesafe-sdk", names)
        self.assertIn("typesafe-sdk", project["optional-dependencies"]["typesafe"])

    def test_runtime_image_has_no_build_tool_install_or_baked_password(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertRegex(dockerfile, r"PYTHON_IMAGE=python:3\.13-slim@sha256:[a-f0-9]{64}")
        runtime = dockerfile.split("AS runtime", 1)[1]
        self.assertNotIn("build-essential", runtime)
        self.assertNotIn("-dev", runtime)
        self.assertNotIn("VNC_PASSWORD=", runtime)
        self.assertIn("USER mario", runtime)
        self.assertIn('ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]', runtime)
        self.assertEqual([path.name for path in ROOT.glob("*entrypoint.sh")], ["entrypoint.sh"])

    def compose_config(self, **settings):
        if not shutil.which("docker"):
            self.skipTest("Docker Compose is optional for unit tests")
        # Never resolve the real .env or inherit provider credentials into config output.
        with tempfile.TemporaryDirectory() as directory:
            compose = Path(directory) / "compose.yml"
            shutil.copyfile(ROOT / "compose.yml", compose)
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    "/dev/null",
                    "-f",
                    str(compose),
                    "config",
                    "--format",
                    "json",
                ],
                env={
                    "PATH": os.environ["PATH"],
                    "HOME": os.environ.get("HOME", directory),
                    **settings,
                },
                capture_output=True,
                check=False,
                text=True,
                timeout=20,
            )
        if result.returncode and "is not a docker command" in result.stderr:
            self.skipTest("Docker Compose plugin is unavailable")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["services"]["mario"]

    def test_compose_defaults_are_local_nonprivileged_and_read_only(self):
        config = self.compose_config()
        self.assertTrue(config["init"])
        self.assertTrue(config["read_only"])
        self.assertEqual(config["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", config["security_opt"])
        self.assertEqual(config["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(config["ports"][0]["published"], "6080")
        self.assertEqual(config["ports"][0]["target"], 6080)
        self.assertEqual(config["environment"]["NOVNC_PORT"], "6080")
        self.assertEqual(config["environment"]["NOVNC_HOST_PORT"], "6080")
        self.assertTrue(any(value.startswith("/tmp:") for value in config["tmpfs"]))
        self.assertEqual(config["build"]["args"], {"MARIO_UID": "1000", "MARIO_GID": "1000"})
        self.assertEqual(config["environment"]["OPENROUTER_API_KEY"], "")

    def test_compose_supports_explicit_lan_binding_port_and_uid(self):
        config = self.compose_config(
            NOVNC_BIND_ADDRESS="0.0.0.0", NOVNC_PORT="6082", MARIO_UID="1001", MARIO_GID="1002"
        )
        self.assertEqual(config["ports"][0]["host_ip"], "0.0.0.0")
        self.assertEqual(config["ports"][0]["published"], "6082")
        self.assertEqual(config["ports"][0]["target"], 6080)
        self.assertEqual(config["environment"]["NOVNC_PORT"], "6080")
        self.assertEqual(config["environment"]["NOVNC_HOST_PORT"], "6082")
        self.assertEqual(config["build"]["args"], {"MARIO_UID": "1001", "MARIO_GID": "1002"})

    def test_compose_port_override_keeps_loopback_binding(self):
        config = self.compose_config(NOVNC_PORT="6082")
        self.assertEqual(config["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(config["ports"][0]["published"], "6082")
        self.assertEqual(config["ports"][0]["target"], 6080)
        self.assertEqual(config["environment"]["NOVNC_PORT"], "6080")
        self.assertEqual(config["environment"]["NOVNC_HOST_PORT"], "6082")

    def test_environment_template_uses_default_port_and_loopback_binding(self):
        settings = (ROOT / ".env.example").read_text().splitlines()
        self.assertIn("NOVNC_PORT=6080", settings)
        self.assertIn("NOVNC_BIND_ADDRESS=127.0.0.1", settings)


if __name__ == "__main__":
    unittest.main()
