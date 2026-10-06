"""ffmpeg 화면 녹화 + Riot Live Client API 감시(게임 종료 감지)."""
import json
import ssl
import statistics
import subprocess
import threading
import time
import urllib.request

from . import config

_ctx = ssl.create_default_context()
_ctx.check_hostname = False          # Live Client API 는 localhost 자체 서명 인증서를 쓴다
_ctx.verify_mode = ssl.CERT_NONE


def fetch_all_game_data(timeout=2):
    url = config.LOL_API + "/liveclientdata/allgamedata"
    with urllib.request.urlopen(url, timeout=timeout, context=_ctx) as r:
        return json.load(r)


class Recorder:
    def __init__(self):
        self.proc = None
        self.path = None
        self.log = None

    def start(self, path):
        self.path = path
        cmd = [config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *config.default_capture_args(path),
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "aac", "-b:a", "160k"] if config.capture_has_audio() else ["-an"]
        cmd += [str(path)]
        self.log = open(str(path) + ".log", "wb")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log)

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self):
        """'q' 를 보내 mkv/mp4 를 정상적으로 마무리하고, 정지 시각(wall)을 반환."""
        wall = time.time()
        if self.alive():
            try:
                self.proc.stdin.write(b"q")
                self.proc.stdin.flush()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=5)
        if self.log:
            self.log.close()
        return wall


class WatchResult:
    def __init__(self):
        self.raw_events = []
        self.active = {}
        self.sync = []        # (wall_time, game_time) 샘플
        self.saw_game = False
        self.ended_by = None  # "GameEnd" | "api_gone" | "manual"


def watch_game(stop_event, on_tick=None, poll=1.0):
    """게임이 끝날 때까지 이벤트를 수집한다. stop_event 가 켜지면 수동 종료."""
    res, fails = WatchResult(), 0
    while not stop_event.is_set():
        try:
            snap = fetch_all_game_data()
            res.saw_game, fails = True, 0
            res.active = snap.get("activePlayer", {}) or res.active
            res.raw_events = snap.get("events", {}).get("Events", res.raw_events)
            res.sync.append((time.time(), float(snap["gameData"]["gameTime"])))
            if on_tick:
                on_tick(res)
            if any(e.get("EventName") == "GameEnd" for e in res.raw_events):
                res.ended_by = "GameEnd"
                break
        except Exception:
            fails += 1
            if res.saw_game and fails >= 4:
                res.ended_by = "api_gone"
                break
        stop_event.wait(poll)
    res.ended_by = res.ended_by or "manual"
    return res


def video_offset(sync, stop_wall, video_duration):
    """영상시간 = 게임시간 + offset. 영상 시작 wall 시각은 (정지시각 - 영상길이)로 역산."""
    if not sync:
        return 0.0
    start_wall = stop_wall - video_duration
    return statistics.median(w - g for w, g in sync) - start_wall
