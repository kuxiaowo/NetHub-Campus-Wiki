"""前端静态文件服务。

运行方式：
    python frontend_server.py

这个服务负责提供 public/ 目录下的静态文件，并为项目库与资源中心注入公开 API
内容快照。快照只用于首屏和搜索引擎索引，不替代浏览器端的筛选与交互。
"""

import html
import os
import json
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
PROTECTED_STATIC_EXTENSIONS = {
    ".pdf", ".zip", ".rar", ".7z",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}
SEO_CACHE_SECONDS = 300
SEO_SNAPSHOT_LIMIT = 50
SEO_CACHE: dict[str, tuple[float, dict]] = {}

load_dotenv(BASE_DIR / ".env")


def frontend_api_base_url() -> str:
    """Return the browser-facing API base URL used by public/js/api.js."""
    explicit_url = os.getenv("FRONTEND_API_BASE_URL", "").strip()
    if explicit_url:
        return explicit_url.rstrip("/")
    api_port = os.getenv("API_PORT", os.getenv("PORT", "3100"))
    return f"http://127.0.0.1:{api_port}/api"


def is_protected_static_path(path: str) -> bool:
    clean_path = unquote(urlsplit(path).path).replace("\\", "/").lstrip("/")
    suffix = Path(clean_path).suffix.lower()
    return suffix in PROTECTED_STATIC_EXTENSIONS


def _escape(value: object) -> str:
    """Escape API content before inserting it into HTML."""

    return html.escape(str(value if value is not None else ""), quote=True)


def _fetch_public_api(path: str) -> dict | None:
    """Fetch and briefly cache one public API response for an SEO snapshot."""

    now = time.monotonic()
    cached = SEO_CACHE.get(path)
    if cached and cached[0] > now:
        return cached[1]

    request = Request(
        f"{frontend_api_base_url()}{path}",
        headers={"Accept": "application/json", "User-Agent": "NetHub-SEO-Snapshot/1.0"},
    )
    try:
        with urlopen(request, timeout=2) as response:  # noqa: S310 - URL comes from trusted environment config.
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(payload, dict):
        return None
    SEO_CACHE[path] = (now + SEO_CACHE_SECONDS, payload)
    return payload


def _project_snapshot(projects: list[dict]) -> str:
    cards = []
    for project in projects[:SEO_SNAPSHOT_LIMIT]:
        project_id = _escape(project.get("id"))
        cards.append(
            f"""<a class="project-row seo-snapshot-card" href="/detail.html?id={project_id}">
  <div>
    <h3>{_escape(project.get("name"))}</h3>
    <div class="meta">
      <span class="badge">{_escape(project.get("category"))}</span>
      <span>{_escape(project.get("year"))}</span>
      <span>负责人：{_escape(project.get("leader"))}</span>
    </div>
    <p>{_escape(project.get("description"))}</p>
  </div>
</a>"""
        )
    return "\n".join(cards)


def _resource_snapshot(resources: list[dict], activities: list[dict]) -> str:
    cards = []
    for resource in resources:
        label = "Yearbook 年鉴" if resource.get("category") == "yearbook" else resource.get("label")
        cards.append(
            f"""<article class="resource-card seo-snapshot-card">
  <div class="resource-body">
    <span class="badge">{_escape(label)}</span>
    <h3>{_escape(resource.get("title"))}</h3>
    <p>{_escape(resource.get("description"))}</p>
    <div class="meta"><span>{_escape(resource.get("year"))}</span></div>
  </div>
</article>"""
        )
    for activity in activities:
        cards.append(
            f"""<article class="resource-card seo-snapshot-card">
  <div class="resource-body">
    <span class="badge">活动照片</span>
    <h3>{_escape(activity.get("activity"))}</h3>
    <p>{_escape(activity.get("description"))}</p>
    <div class="meta"><span>{_escape(activity.get("year"))}</span></div>
  </div>
</article>"""
        )
    return "\n".join(cards[:SEO_SNAPSHOT_LIMIT])


def _replace_snapshot(source: str, name: str, content: str) -> str:
    start_marker = f"<!-- SEO_{name}_START -->"
    end_marker = f"<!-- SEO_{name}_END -->"
    start = source.find(start_marker)
    end = source.find(end_marker)
    if start == -1 or end == -1 or end < start:
        return source
    content_start = start + len(start_marker)
    return f"{source[:content_start]}\n{content}\n{source[end:]}"


def render_seo_html(filename: str) -> bytes:
    """Return an HTML page enhanced with current public content when the API is available."""

    source = (PUBLIC_DIR / filename).read_text(encoding="utf-8")
    if filename == "projects.html":
        payload = _fetch_public_api("/projects?sort=latest")
        projects = payload.get("data") if payload else None
        if isinstance(projects, list):
            snapshot = _project_snapshot([item for item in projects if isinstance(item, dict)])
            if snapshot:
                source = _replace_snapshot(source, "PROJECTS", snapshot)
    elif filename == "resources.html":
        with ThreadPoolExecutor(max_workers=2) as executor:
            resources_future = executor.submit(_fetch_public_api, "/resources?sort=hot")
            activities_future = executor.submit(_fetch_public_api, "/photo-activities?sort=hot")
            resources_payload = resources_future.result()
            activities_payload = activities_future.result()
        resources = resources_payload.get("data") if resources_payload else []
        activities = activities_payload.get("data") if activities_payload else []
        if isinstance(resources, list) and isinstance(activities, list):
            snapshot = _resource_snapshot(
                [item for item in resources if isinstance(item, dict)],
                [item for item in activities if isinstance(item, dict)],
            )
            if snapshot:
                source = _replace_snapshot(source, "RESOURCES", snapshot)
    return source.encode("utf-8")


class FrontendHandler(SimpleHTTPRequestHandler):
    """静态文件处理器。

    SimpleHTTPRequestHandler 默认会按目录返回文件。这里固定目录为 public/，
    并把根路径 / 映射到首页 index.html。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def do_GET(self):  # noqa: N802 - inherited method name from stdlib.
        # 访问 http://127.0.0.1:3200/ 时直接打开首页。
        if self.path == "/":
            self.path = "/index.html"
        if self.path.split("?", 1)[0] == "/js/config.js":
            config = {
                "apiBaseUrl": frontend_api_base_url(),
            }
            body = f"window.CAMPUS_WIKI_CONFIG = {json.dumps(config, ensure_ascii=False)};\n"
            encoded_body = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded_body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            self.wfile.write(encoded_body)
            return
        clean_path = urlsplit(self.path).path
        if clean_path in {"/projects.html", "/resources.html"}:
            encoded_body = render_seo_html(clean_path.lstrip("/"))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded_body)))
            self.end_headers()
            self.wfile.write(encoded_body)
            return
        if is_protected_static_path(self.path):
            self.send_error(401, "Login required")
            return
        return super().do_GET()

    def end_headers(self):  # noqa: N802 - inherited method name from stdlib.
        # 开发阶段避免浏览器缓存旧 HTML/JS/CSS，方便前端改动立即生效。
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()


if __name__ == "__main__":
    port = int(os.getenv("FRONTEND_PORT", "3200"))
    server = ThreadingHTTPServer(("0.0.0.0", port), FrontendHandler)
    print(f"Frontend service: http://127.0.0.1:{port}")
    server.serve_forever()
