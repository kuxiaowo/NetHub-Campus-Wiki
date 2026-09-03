"""前端静态文件服务。

运行方式：
    python frontend_server.py

这个服务只负责把 public/ 目录下的 HTML、CSS、JS 提供给浏览器，不访问数据库，
也不包含任何后端业务逻辑。
"""

import os
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from http import HTTPStatus
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
PROTECTED_STATIC_EXTENSIONS = {
    ".pdf", ".zip", ".rar", ".7z",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
}
RANGE_COPY_CHUNK_SIZE = 64 * 1024

load_dotenv(BASE_DIR / ".env")


def frontend_api_base_url(request_host: str | None = None) -> str:
    """Return the browser-facing API URL, following the requested host by default."""
    explicit_url = os.getenv("FRONTEND_API_BASE_URL", "").strip()
    if explicit_url:
        return explicit_url.rstrip("/")
    api_port = os.getenv("API_PORT", os.getenv("PORT", "3100"))
    hostname = urlsplit(f"//{request_host or ''}").hostname or "127.0.0.1"
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return f"http://{hostname}:{api_port}/api"


def is_protected_static_path(path: str) -> bool:
    clean_path = unquote(urlsplit(path).path).replace("\\", "/").lstrip("/")
    suffix = Path(clean_path).suffix.lower()
    return suffix in PROTECTED_STATIC_EXTENSIONS


def parse_byte_range(value: str, file_size: int) -> tuple[int, int] | None:
    """Parse one RFC 7233 byte range and return inclusive offsets."""

    unit, separator, requested_range = value.strip().partition("=")
    if separator != "=" or unit.lower() != "bytes":
        return None
    if "," in requested_range:
        raise ValueError("multiple byte ranges are not supported")

    start_text, dash, end_text = requested_range.strip().partition("-")
    if dash != "-" or (not start_text and not end_text):
        raise ValueError("invalid byte range")
    try:
        if not start_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError("invalid suffix byte range")
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        else:
            start = int(start_text)
            end = int(end_text) if end_text else file_size - 1
    except ValueError as error:
        raise ValueError("invalid byte range") from error

    if start < 0 or start >= file_size or end < start:
        raise ValueError("unsatisfiable byte range")
    return start, min(end, file_size - 1)


class FrontendHandler(SimpleHTTPRequestHandler):
    """静态文件处理器。

    SimpleHTTPRequestHandler 默认会按目录返回文件。这里固定目录为 public/，
    并把根路径 / 映射到首页 index.html。
    """

    protocol_version = "HTTP/1.1"
    _response_range: tuple[int, int] | None = None
    _advertise_byte_ranges = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def do_GET(self):  # noqa: N802 - inherited method name from stdlib.
        # 访问服务根路径时直接打开首页。
        if self.path == "/":
            self.path = "/index.html"
        if self.path.split("?", 1)[0] == "/js/config.js":
            config = {
                "apiBaseUrl": frontend_api_base_url(self.headers.get("Host")),
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
        if is_protected_static_path(self.path):
            self.send_error(401, "Login required")
            return
        return super().do_GET()

    def do_HEAD(self):  # noqa: N802 - inherited method name from stdlib.
        if is_protected_static_path(self.path):
            self.send_error(401, "Login required")
            return
        return super().do_HEAD()

    def send_head(self):
        """Serve a single requested byte range so media can seek without a full download."""

        self._response_range = None
        self._advertise_byte_ranges = False
        path = Path(self.translate_path(self.path))
        if not path.is_file():
            return super().send_head()

        self._advertise_byte_ranges = True
        range_header = self.headers.get("Range")
        if not range_header:
            return super().send_head()

        try:
            source = path.open("rb")
        except OSError:
            return super().send_head()

        file_size = path.stat().st_size
        try:
            byte_range = parse_byte_range(range_header, file_size)
        except ValueError:
            source.close()
            self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
            self.send_header("Content-Range", f"bytes */{file_size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if byte_range is None:
            source.close()
            return super().send_head()

        start, end = byte_range
        self._response_range = byte_range
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(str(path)))
        self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Last-Modified", self.date_time_string(path.stat().st_mtime))
        self.end_headers()
        return source

    def copyfile(self, source, outputfile):
        if self._response_range is None:
            return super().copyfile(source, outputfile)

        start, end = self._response_range
        source.seek(start)
        remaining = end - start + 1
        while remaining:
            chunk = source.read(min(RANGE_COPY_CHUNK_SIZE, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)

    def end_headers(self):  # noqa: N802 - inherited method name from stdlib.
        # 开发阶段避免浏览器缓存旧 HTML/JS/CSS，方便前端改动立即生效。
        if self._advertise_byte_ranges:
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()


if __name__ == "__main__":
    port = int(os.getenv("FRONTEND_PORT", "3200"))
    host = os.getenv("FRONTEND_HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), FrontendHandler)
    print(f"Frontend service listening on http://{host}:{port}")
    server.serve_forever()
