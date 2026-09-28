import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from nethub_moderation.providers import ProviderError, Providers
from nethub_moderation.service import (
    ConfigStore,
    DEFAULTS,
    Worker,
    create_app,
    quota_reset,
)
from unittest.mock import patch


class ServiceTest(unittest.TestCase):
    def test_loopback_auth_is_injected_and_public_clients_are_rejected(self):
        async def probe():
            with tempfile.TemporaryDirectory() as directory, patch.dict(
                "os.environ", {"MODERATION_TOKEN": "x" * 48}
            ):
                app = create_app(directory, sites=[])
                try:
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(app, client=("127.0.0.1", 1234)),
                        base_url="http://localhost",
                    ) as client:
                        self.assertEqual(
                            (await client.get("/settings")).status_code, 403
                        )
                        response = await client.get(
                            "/settings", headers={"Authorization": "Bearer " + "x" * 48}
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertNotIn("apiKey", response.json())
                        response = await client.post(
                            "/codex/login",
                            json={"type": "apiKey"},
                            headers={"Authorization": "Bearer " + "x" * 48},
                        )
                        self.assertEqual(response.status_code, 422)
                    async with httpx.AsyncClient(
                        transport=httpx.ASGITransport(
                            app, client=("203.0.113.1", 1234)
                        ),
                        base_url="http://localhost",
                    ) as client:
                        self.assertEqual(
                            (
                                await client.get(
                                    "/settings",
                                    headers={"Authorization": "Bearer " + "x" * 48},
                                )
                            ).status_code,
                            403,
                        )
                finally:
                    await app.state.worker.close()

        asyncio.run(probe())

    def test_key_is_encrypted_and_never_returned_and_limits_are_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(directory)
            public = store.save(
                {"provider": "openai", "apiKey": "secret-test-key", "model": "example"}
            )
            self.assertNotIn("apiKey", public)
            self.assertTrue(public["keyConfigured"])
            self.assertNotIn(b"secret-test-key", Path(store.path).read_bytes())
            self.assertEqual(store.read()["apiKey"], "secret-test-key")
            store.save({"apiKey": ""})
            self.assertEqual(store.read()["apiKey"], "secret-test-key")
            for patch in [
                {"concurrency": 33},
                {"concurrency": 0},
                {"timeout": 9},
                {"baseUrl": "file:///private"},
                {"provider": "unknown"},
            ]:
                with self.assertRaises(ValueError):
                    store.save(patch)

    def test_openai_fallback_is_narrow_and_output_is_validated(self):
        async def probe():
            providers = Providers(tempfile.gettempdir())
            calls = []
            job = {
                "jobId": "1",
                "currentComment": "正常评论",
                "pageTitle": "资料",
                "parentComment": "",
            }

            def handler(request):
                payload = json.loads(request.content)
                calls.append(payload)
                if payload.get("response_format", {}).get("type") == "json_schema":
                    return httpx.Response(
                        400,
                        json={
                            "error": {
                                "message": "response_format json_schema unsupported"
                            }
                        },
                    )
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "jobId": "1",
                                            "decision": "allow",
                                            "categories": [],
                                            "evidence": [],
                                            "explanation": "正常",
                                        }
                                    )
                                }
                            }
                        ]
                    },
                )

            await providers.http.aclose()
            providers.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            config = {
                **DEFAULTS,
                "provider": "openai",
                "apiKey": "secret",
                "model": "example",
            }
            self.assertEqual(
                (await providers.moderate(config, job))["decision"], "allow"
            )
            self.assertEqual(len(calls), 2)
            await providers.moderate(config, job)
            self.assertEqual(len(calls), 3)
            await providers.close()

        asyncio.run(probe())

    def test_http_auth_errors_do_not_expose_provider_response(self):
        async def probe():
            providers = Providers(tempfile.gettempdir())
            await providers.http.aclose()
            providers.http = httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _: httpx.Response(401, text="your secret is abc")
                )
            )
            with self.assertRaisesRegex(ProviderError, "provider_auth_failed"):
                await providers.models(
                    {**DEFAULTS, "provider": "openai", "apiKey": "abc"}
                )
            await providers.close()

        asyncio.run(probe())

    def test_global_pool_fairness_and_lower_limit_does_not_cancel_running_tasks(self):
        async def probe():
            with tempfile.TemporaryDirectory() as directory:
                store = ConfigStore(directory)
                store.save({"model": "mock"})
                gate = asyncio.Event()
                started = []
                claims = []
                completed = []

                class MockProvider:
                    async def moderate(self, config, job):
                        started.append(job["jobId"])
                        await gate.wait()
                        return {"jobId": job["jobId"]}

                    async def close(self):
                        pass

                worker = Worker(store, MockProvider(), ["wiki", "cas"], "token")

                async def preflight(_):
                    return True

                async def call(url, path, payload):
                    if path.endswith("claim"):
                        claims.append(url)
                        return (
                            {"job": {"jobId": url, "id": 1, "token": "token"}}
                            if url not in claims[:-1]
                            else {"job": None}
                        )
                    completed.append(url)
                    return {"applied": True}

                worker.preflight = preflight
                worker.call = call
                loop = asyncio.create_task(worker.loop())
                await asyncio.sleep(0.1)
                self.assertEqual(started, ["wiki", "cas"])
                self.assertEqual(len(worker.tasks), 2)
                store.save({"concurrency": 1})
                await asyncio.sleep(0.5)
                self.assertEqual(len(worker.tasks), 2)
                gate.set()
                await asyncio.sleep(0.1)
                self.assertCountEqual(completed, ["wiki", "cas"])
                loop.cancel()
                await asyncio.gather(loop, return_exceptions=True)
                await worker.close()

        asyncio.run(probe())

    def test_quota_reset_uses_exhausted_windows_only(self):
        self.assertEqual(
            quota_reset(
                {
                    "rateLimitsByLimitId": {
                        "x": {
                            "primary": {"usedPercent": 100, "resetsAt": 200},
                            "secondary": {"usedPercent": 50, "resetsAt": 900},
                        }
                    }
                }
            ),
            200,
        )
