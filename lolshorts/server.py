import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import config, demo
from .session import Session

SESSION = Session()
STATIC = config.BASE / "static"
ROUTES = {"/files/out/": config.OUT_DIR, "/files/previews/": config.PREVIEW_DIR}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, download=False):
        if not path.is_file():
            return self._json({"error": "not found"}, 404)
        size = path.stat().st_size
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if m and (m.group(1) or m.group(2)):  # 영상 탐색을 위한 Range 지원
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else end
            else:
                start = max(size - int(m.group(2)), 0)
            code = 206
        end = min(end, size - 1)
        self.send_response(code)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                left -= len(chunk)

    def do_GET(self):
        path, _, q = self.path.partition("?")
        if path in ("/", "/index.html"):
            return self._file(STATIC / "index.html")
        if path == "/api/status":
            return self._json(SESSION.status())
        for prefix, root in ROUTES.items():
            if path.startswith(prefix):
                name = Path(path[len(prefix):]).name  # 경로 탈출 방지
                return self._file(root / name, download="download=1" in q)
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            if self.path == "/api/record/start":
                SESSION.start_recording()
            elif self.path == "/api/record/stop":
                SESSION.stop_recording()
            elif self.path == "/api/submit":
                SESSION.submit(body.get("category"), body.get("samples", []), body.get("music") or None)
            elif self.path == "/api/demo":
                demo.load_demo(SESSION)
            else:
                return self._json({"error": "not found"}, 404)
            self._json({"ok": True})
        except (RuntimeError, ValueError) as e:
            self._json({"error": str(e)}, 400)


def serve(host="127.0.0.1", port=8765):
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"LoL 쇼츠 메이커: http://{host}:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
