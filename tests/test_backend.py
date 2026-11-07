from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock, patch

from typesafe_mario.jev_backend import JevBackend
from typesafe_mario.policy import _Question


class BackendTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_auto_falls_back_to_local(self) -> None:
        backend = JevBackend()
        self.assertEqual(backend.backend, "ollama")
        self.assertEqual(backend.url, "http://localhost:11434/v1/systemone")

    @patch.dict(os.environ, {"TYPESAFE_API_KEY": "direct-test", "OPENROUTER_API_KEY": "or-test"})
    def test_auto_prefers_direct_and_explicit_backend_wins(self) -> None:
        self.assertEqual(JevBackend().backend, "direct")
        self.assertEqual(JevBackend("openrouter").api_key, "or-test")

    @patch.dict(os.environ, {"OLLAMA_HOST": "host.docker.internal:11434"})
    def test_ollama_host_is_used(self) -> None:
        backend = JevBackend("ollama")
        self.assertEqual(backend.url, "http://host.docker.internal:11434/v1/systemone")

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"})
    def test_endpoint_override_retains_selected_backend_model_and_credentials(self) -> None:
        backend = JevBackend("openrouter", base_url="http://proxy.test/v1/systemone/")
        self.assertEqual(backend.url, "http://proxy.test/v1/systemone")
        self.assertEqual(backend.model, "typesafe/jev-1.13")
        self.assertEqual(backend.api_key, "test-key")

    @patch("urllib.request.urlopen")
    def test_wire_format_and_response_normalization_without_network(self, urlopen) -> None:
        response = MagicMock()
        response.read.return_value = json.dumps(
            {
                "answers": {
                    "action": {
                        "type": "choice",
                        "choice": "right",
                        "confidence": 0.8,
                        "probabilities": {"right": 0.8},
                    },
                    "jump": {"type": "noul", "noul": 0.4},
                    "danger": {"type": "score", "score": 1},
                }
            }
        ).encode()
        urlopen.return_value.__enter__.return_value = response
        backend = JevBackend("direct", api_key="test-key")
        result = backend.system_one(
            state={"x": 40},
            questions={
                "action": _Question("choose", {"right": "walk"}),
                "jump": _Question("jump?", type="noul"),
                "danger": _Question("danger?", type="score"),
            },
        )
        self.assertEqual(result.choices["action"].choice, "right")
        self.assertEqual(result.nouls["jump"].noul, 0.4)
        self.assertEqual(result.scores["danger"].score, 1)
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["questions"]["jump"]["type"], "noul")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key")


if __name__ == "__main__":
    unittest.main()
