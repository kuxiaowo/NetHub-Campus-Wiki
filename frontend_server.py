"""前端静态文件服务。

运行方式：
    python frontend_server.py

这个服务只负责把 public/ 目录下的 HTML、CSS、JS 提供给浏览器，不访问数据库，
也不包含任何后端业务逻辑。
"""

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"


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
