import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from urllib.parse import parse_qs, urlparse

from . import config, demo, youtube
from .session import Session

SESSION = Session()
PORT = {"v": 8765}


def redirect_uri():
    return f"http://127.0.0.1:{PORT['v']}/oauth/callback"
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
        if path == "/oauth/callback":
            qs = parse_qs(urlparse(self.path).query)
            try:
                if "error" in qs:
                    raise youtube.YouTubeError(qs["error"][0])
                youtube.finish_auth(qs["code"][0], qs["state"][0], redirect_uri())
                msg = "YouTube 연결 완료! 이 창을 닫고 쇼츠 메이커로 돌아가세요."
            except Exception as e:
                msg = f"연결 실패: {e}"
            body = f"<meta charset=utf-8><body style='font-family:sans-serif;padding:40px'><h2>{msg}</h2>".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return self.wfile.write(body)
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
            elif self.path == "/api/youtube/connect":
                return self._json({"url": youtube.auth_url(redirect_uri())})
            elif self.path == "/api/youtube/disconnect":
                youtube.disconnect()
            elif self.path == "/api/youtube/upload":
                SESSION.upload(body.get("filename", ""), body.get("title", ""), body.get("description", ""),
                               body.get("privacy", "private"))
            elif self.path == "/api/demo":
                demo.load_demo(SESSION)
            else:
                return self._json({"error": "not found"}, 404)
            self._json({"ok": True})
        except (RuntimeError, ValueError) as e:  # YouTubeError 도 RuntimeError
            self._json({"error": str(e)}, 400)


def serve(host="127.0.0.1", port=8765):
    PORT["v"] = port
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"LoL 쇼츠 메이커: http://{host}:{port}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
