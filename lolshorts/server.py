import json
import mimetypes
import os
import re
import socket
import subprocess
import sys
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from urllib.parse import parse_qs, urlparse

from . import config, demo, youtube
from .session import Session

SESSION = Session()
PORT = {"v": 8765, "phone": None}


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

    def _local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _mobile_page(self):
        items = sorted(config.OUT_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
        cards = "".join(
            f"<div class=c><video src='/files/out/{html.escape(p.name)}' controls playsinline preload=metadata></video>"
            f"<a href='/files/out/{html.escape(p.name)}?download=1'>⬇ 저장</a> <small>{html.escape(p.name)}</small></div>"
            for p in items) or "<p>아직 만든 쇼츠가 없어요</p>"
        body = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>내 쇼츠</title><style>body{margin:0;padding:16px;background:#0b0e14;color:#e8ecf3;font-family:system-ui}"
                ".c{margin-bottom:24px}video{width:100%;max-height:75vh;background:#000;border-radius:10px}"
                "a{display:inline-block;margin-top:8px;padding:10px 16px;background:#c8aa6e;color:#1a1405;border-radius:8px;"
                "font-weight:700;text-decoration:none}small{color:#8b95a8;margin-left:8px}</style>"
                "<h2>내 쇼츠</h2><p style='color:#8b95a8'>저장한 뒤 유튜브 앱에서 업로드하세요. 영상을 길게 눌러도 저장할 수 있어요.</p>"
                + cards).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path, _, q = self.path.partition("?")
        if not self._local() and not (path == "/m" or path.startswith("/files/out/")):
            return self._json({"error": "forbidden"}, 403)  # 폰(외부)에는 완성본 보기/저장만 허용
        if path == "/m":
            return self._mobile_page()
        if path in ("/", "/index.html"):
            return self._file(STATIC / "index.html")
        if path == "/api/status":
            return self._json({**SESSION.status(), "phone_url": PORT["phone"]})
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
        if not self._local():
            return self._json({"error": "forbidden"}, 403)
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
            elif self.path == "/api/open_folder":
                _open_folder(config.OUT_DIR)
            elif self.path == "/api/demo":
                demo.load_demo(SESSION)
            else:
                return self._json({"error": "not found"}, 404)
            self._json({"ok": True})
        except (RuntimeError, ValueError, OSError) as e:  # YouTubeError 도 RuntimeError
            self._json({"error": str(e)}, 400)


def _open_folder(path):
    if sys.platform == "win32":
        os.startfile(path)  # noqa
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # 실제로 패킷을 보내지 않고 내 LAN 주소만 알아낸다
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def serve(host="127.0.0.1", port=8765, phone=False):
    PORT["v"] = port
    if phone:
        host = "0.0.0.0"
        ip = lan_ip()
        PORT["phone"] = f"http://{ip}:{port}/m" if ip else None
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"LoL 쇼츠 메이커: http://127.0.0.1:{port}")
    if PORT["phone"]:
        print(f"폰에서 받기(같은 와이파이): {PORT['phone']}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
