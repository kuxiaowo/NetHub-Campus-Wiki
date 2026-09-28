"""One loopback service and one Codex process for both sites."""

import asyncio
import json
import os
import sqlite3
import time
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import uvicorn
from cryptography.fernet import Fernet
from fastapi import Body, Depends, FastAPI, HTTPException

from .policy import CATEGORIES
from .providers import ProviderError, Providers
from .routes import internal_auth

DEFAULTS = {
    "provider": "codex",
    "baseUrl": "https://api.openai.com/v1",
    "apiKey": "",
    "model": "",
    "effort": "",
    "codexCommand": "codex",
    "timeout": 180,
    "concurrency": 2,
    "enabled": True,
    "version": 1,
}


class ConfigStore:
    def __init__(self, directory):
        self.lock = threading.RLock()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        key_path = self.directory / "key"
        if not key_path.exists():
            descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(Fernet.generate_key())
        self.cipher = Fernet(key_path.read_bytes())
        self.path = self.directory / "settings.sqlite3"
        with self.db() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL)"
            )
            if not conn.execute("SELECT 1 FROM settings").fetchone():
                conn.execute(
                    "INSERT INTO settings VALUES(1,?)", (json.dumps(DEFAULTS),)
                )
        os.chmod(self.path, 0o600)

    def read(self):
        with self.db() as conn:
            data = json.loads(
                conn.execute("SELECT payload FROM settings WHERE id=1").fetchone()[0]
            )
        if data.get("apiKey"):
            data["apiKey"] = self.cipher.decrypt(data["apiKey"].encode()).decode()
        return {**DEFAULTS, **data}

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def merged(self, patch):
        if not isinstance(patch, dict) or any(
            k not in {*DEFAULTS, "clearKey"} for k in patch
        ):
            raise ValueError("配置字段无效")
        current = self.read()
        result = {
            **current,
            **{
                k: v
                for k, v in patch.items()
                if k not in {"version", "apiKey", "clearKey"}
            },
        }
        if patch.get("apiKey"):
            result["apiKey"] = patch["apiKey"]
        if patch.get("clearKey") is True:
            result["apiKey"] = ""
        if result["provider"] not in {"openai", "codex"}:
            raise ValueError("接口格式无效")
        for key in ["model", "baseUrl", "apiKey", "effort", "codexCommand"]:
            if (
                not isinstance(result[key], str)
                or len(result[key]) > 4096
                or "\n" in result[key]
            ):
                raise ValueError("配置文本无效")
        url = urlsplit(result["baseUrl"])
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("Base URL 必须是有效的 HTTP(S) 地址")
        for key, low, high in [("concurrency", 1, 32), ("timeout", 10, 600)]:
            if type(result[key]) is not int or not low <= result[key] <= high:
                raise ValueError(f"{key} 必须在 {low}～{high} 之间")
        if type(result["enabled"]) is not bool:
            raise ValueError("启用状态无效")
        return result

    def save(self, patch):
        with self.lock:
            data = self.merged(patch)
            data["version"] += 1
            stored = dict(data)
            if stored["apiKey"]:
                stored["apiKey"] = self.cipher.encrypt(
                    stored["apiKey"].encode()
                ).decode()
            with self.db() as conn:
                conn.execute(
                    "UPDATE settings SET payload=? WHERE id=1", (json.dumps(stored),)
                )
            return self.public(data)

    @staticmethod
    def public(data):
        return {
            **{k: v for k, v in data.items() if k != "apiKey"},
            "keyConfigured": bool(data["apiKey"]),
        }


class Worker:
    def __init__(self, store, providers, sites, token):
        self.store, self.providers, self.sites, self.token = (
            store,
            providers,
            sites,
            token,
        )
        self.tasks = set()
        self.http = httpx.AsyncClient(trust_env=False, timeout=15)
        self.next_site = 0
        self.ready = False
        self.message = "待配置模型及登录"
        self.checked_version = None
        self.checked_at = 0
        self.stopping = False
        self.paused_until = 0

    async def call(self, url, path, payload):
        response = await self.http.post(
            url + path, json=payload, headers={"Authorization": "Bearer " + self.token}
        )
        response.raise_for_status()
        return response.json()

    async def preflight(self, config):
        if (
            not config["enabled"]
            or not config["model"]
            or (config["provider"] == "openai" and not config["apiKey"])
        ):
            self.ready, self.message = (
                False,
                "待配置接口、模型或登录；新评论已保存到队列",
            )
            return False
        if (
            self.checked_version == config["version"]
            and time.time() - self.checked_at < 60
        ):
            return self.ready
        try:
            models = await self.providers.models(config)
            selected = next(
                (
                    m
                    for m in models["data"]
                    if (m.get("model") or m.get("id")) == config["model"]
                ),
                None,
            )
            if selected is None:
                raise ProviderError("selected_model_unavailable")
            efforts = [
                r["reasoningEffort"]
                for r in selected.get("supportedReasoningEfforts", [])
            ]
            if (
                config["provider"] == "codex"
                and config["effort"]
                and config["effort"] not in efforts
            ):
                raise ProviderError("reasoning_effort_unavailable")
            if config["provider"] == "codex" and exhausted_windows(
                models.get("quota", {})
            ):
                self.ready, self.message = (
                    False,
                    "Codex 额度已耗尽，等待恢复，不启用额外计费",
                )
                self.paused_until = max(quota_reset(models["quota"]), time.time() + 60)
            else:
                self.ready, self.message = True, "审核服务运行中"
                if config["provider"] == "codex":
                    self.paused_until = 0
        except (ProviderError, ValueError, KeyError) as exc:
            self.ready, self.message = False, getattr(
                exc, "code", "model_discovery_failed"
            )
        self.checked_at, self.checked_version = time.time(), config["version"]
        return self.ready

    async def run_job(self, url, job, config):
        payload = {"job": job}
        try:
            payload["result"] = await asyncio.wait_for(
                self.providers.moderate(config, job), config["timeout"]
            )
        except ProviderError as exc:
            payload["error"] = exc.code
            if exc.code == "quota_exhausted":
                reset = (
                    quota_reset(self.providers.codex.quota)
                    if config["provider"] == "codex"
                    else 0
                )
                self.paused_until = max(reset, time.time() + 60)
                payload["retryAt"] = self.paused_until
        except TimeoutError:
            payload["error"] = "provider_timeout"
        except (ValueError, KeyError, TypeError):
            payload["error"] = "result_invalid"
        except asyncio.CancelledError:
            # The lease recovers this work after service exit.
            raise
        except Exception:
            payload["error"] = "provider_unavailable"
        try:
            await self.call(url, "/internal/moderation/result", payload)
        except httpx.HTTPError:
            # Lost confirmation is safe: conditional result application is idempotent.
            try:
                await self.call(url, "/internal/moderation/result", payload)
            except httpx.HTTPError:
                pass

    async def loop(self):
        while not self.stopping:
            try:
                config = self.store.read()
                if not await self.preflight(config) or time.time() < self.paused_until:
                    await asyncio.sleep(1)
                    continue
                while len(self.tasks) < self.store.read()["concurrency"]:
                    found = False
                    reservation = asyncio.get_running_loop().create_future()
                    self.tasks.add(reservation)
                    for _ in range(len(self.sites)):
                        url = self.sites[self.next_site]
                        self.next_site = (self.next_site + 1) % len(self.sites)
                        try:
                            data = await self.call(
                                url,
                                "/internal/moderation/claim",
                                {
                                    "version": config["version"],
                                    "timeout": config["timeout"],
                                },
                            )
                        except httpx.HTTPError:
                            continue
                        if data.get("job"):
                            task = asyncio.create_task(
                                self.run_job(url, data["job"], dict(config))
                            )
                            self.tasks.add(task)
                            task.add_done_callback(self.tasks.discard)
                            found = True
                            break
                    self.tasks.discard(reservation)
                    reservation.cancel()
                    if not found:
                        break
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.ready, self.message = False, "worker_error"
                await asyncio.sleep(2)

    async def close(self):
        self.stopping = True
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.providers.close()
        await self.http.aclose()


def exhausted_windows(quota):
    windows = []
    if isinstance(quota.get("rateLimits"), dict):
        windows.append(quota["rateLimits"])
    windows.extend((quota.get("rateLimitsByLimitId") or {}).values())
    return [
        window
        for bucket in windows
        for window in [bucket.get("primary"), bucket.get("secondary")]
        if isinstance(window, dict) and float(window.get("usedPercent") or 0) >= 100
    ]


def quota_reset(quota):
    return max(
        (float(window.get("resetsAt") or 0) for window in exhausted_windows(quota)),
        default=0,
    )


def create_app(directory=None, sites=None, token=None):
    store = ConfigStore(
        directory or os.environ.get("MODERATION_DATA_DIR", "data/moderation")
    )
    providers = Providers(store.directory / "codex")
    site_urls = (
        sites
        if sites is not None
        else os.environ.get(
            "MODERATION_SITES", "http://127.0.0.1:3100,http://127.0.0.1:3300"
        ).split(",")
    )
    for url in site_urls:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"}:
            raise ValueError("审核站点必须是本机地址")
    worker = Worker(
        store, providers, site_urls, token or os.environ.get("MODERATION_TOKEN", "")
    )

    @asynccontextmanager
    async def lifespan(_):
        task = asyncio.create_task(worker.loop())
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await worker.close()

    app = FastAPI(
        lifespan=lifespan,
        dependencies=[Depends(internal_auth)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.worker, app.state.store = worker, store

    @app.get("/settings")
    def settings():
        return store.public(store.read())

    @app.patch("/settings")
    async def save(patch: dict = Body(...)):
        try:
            candidate = store.merged(patch)
            if (
                candidate["codexCommand"] != store.read()["codexCommand"]
                and worker.tasks
            ):
                raise HTTPException(409, "请等待当前任务完成后修改 Codex 程序路径")
            if candidate["codexCommand"] != store.read()["codexCommand"]:
                await providers.codex.close()
                providers.codex.command = candidate["codexCommand"]
            return store.save(patch)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None

    @app.post("/models")
    async def models(patch: dict = Body(default={})):
        try:
            return await providers.models(store.merged(patch))
        except ProviderError as exc:
            raise HTTPException(503, exc.code) from None
        except ValueError:
            raise HTTPException(422, "接口配置或模型列表无效") from None

    @app.post("/test")
    async def test(patch: dict = Body(default={})):
        try:
            config = store.merged(patch)
            data = await providers.models(config)
            if config["provider"] == "codex" and exhausted_windows(
                data.get("quota", {})
            ):
                raise HTTPException(429, "Codex 额度耗尽，未启动生成测试，请等待恢复")
            if not any(
                (m.get("model") or m.get("id")) == config["model"] for m in data["data"]
            ):
                raise HTTPException(422, "请选择接口返回的可用模型")
            job = {
                "jobId": "connection-test",
                "currentComment": "谢谢分享这份学习资料。",
                "pageTitle": "连接测试",
                "parentComment": "",
            }
            # Check and reserve without an await so tests share the worker's pool.
            if len(worker.tasks) >= store.read()["concurrency"]:
                raise HTTPException(409, "并发池已满，请稍后测试")
            task = asyncio.create_task(
                asyncio.wait_for(providers.moderate(config, job), config["timeout"])
            )
            worker.tasks.add(task)
            try:
                result = await task
            finally:
                worker.tasks.discard(task)
            return {"ok": True, "decision": result["decision"]}
        except ProviderError as exc:
            raise HTTPException(503, exc.code) from None
        except TimeoutError:
            raise HTTPException(504, "provider_timeout") from None
        except (ValueError, KeyError):
            raise HTTPException(422, "审核接口配置或返回结果无效") from None

    @app.get("/status")
    async def status():
        login_state = "unavailable"
        if store.read()["provider"] == "codex":
            providers.codex.command = store.read()["codexCommand"]
            try:
                account = await providers.codex.rpc(
                    "account/read", {"refreshToken": False}, timeout=10
                )
                providers.codex.account = account.get("account")
                login_state = (
                    "logged_in"
                    if (providers.codex.account or {}).get("type") == "chatgpt"
                    else "logged_out"
                )
            except ProviderError:
                pass
        return {
            "ready": worker.ready,
            "message": worker.message,
            "active": len(worker.tasks),
            "concurrency": store.read()["concurrency"],
            "quota": providers.codex.quota,
            "codexLogin": login_state,
            "pausedUntil": worker.paused_until,
            "categories": CATEGORIES,
        }

    @app.post("/codex/login")
    async def login(payload: dict = Body(default={})):
        login_type = payload.get("type", "chatgptDeviceCode")
        if login_type not in {"chatgptDeviceCode", "chatgpt"}:
            raise HTTPException(422, "仅支持 ChatGPT 账号登录")
        providers.codex.command = store.read()["codexCommand"]
        try:
            data = await providers.codex.rpc(
                "account/login/start", {"type": login_type}
            )
            worker.checked_at = 0
            return {**data, "requiresSshTunnel": login_type == "chatgpt"}
        except ProviderError as exc:
            detail = (
                "设备登录申请失败，可使用浏览器登录（先转发服务器 1455 端口）"
                if login_type == "chatgptDeviceCode"
                else exc.code
            )
            raise HTTPException(503, detail) from None

    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=3500, proxy_headers=False)
