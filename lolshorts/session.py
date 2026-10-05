"""녹화 → 분석 → 샘플 → 렌더 흐름을 관리하는 상태 머신."""
import json
import threading
import time
import traceback
from pathlib import Path

from . import config, events, recorder, render

CATEGORY_TAGS = {
    "fun": "#롤 #리그오브레전드 #재밌는순간 #shorts",
    "cool": "#롤 #리그오브레전드 #하이라이트 #매드무비 #shorts",
    "funny": "#롤 #리그오브레전드 #롤웃긴순간 #롤실수 #shorts",
}
TITLE = {
    "fun": "이거 실화? 롤 하이라이트 {l}",
    "cool": "롤 {l} 하이라이트 🔥",
    "funny": "롤하다 이런 일이 ㅋㅋㅋ {l}",
}


class Session:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "idle"   # idle recording analyzing ready rendering done error
        self.message = ""
        self.video = None
        self.samples = []
        self.result = None
        self.stop_event = threading.Event()
        self.rec = recorder.Recorder()
        self.moments = {}

    def _set(self, state, msg=""):
        self.state, self.message = state, msg

    def status(self):
        with self.lock:
            return {"state": self.state, "message": self.message, "samples": self.samples, "result": self.result,
                    "music": sorted(p.name for p in config.MUSIC_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg"))}

    # ---- 녹화 ----
    def start_recording(self):
        with self.lock:
            if self.state in ("recording", "analyzing", "rendering"):
                raise RuntimeError("이미 진행 중입니다")
            self.stop_event.clear()
            self.samples, self.result, self.moments = [], None, {}
            self.video = config.REC_DIR / time.strftime("game_%Y%m%d_%H%M%S.mkv")
            self.rec.start(self.video)
            self._set("recording", "녹화 중 — 게임이 끝나면 자동으로 멈춥니다")
        threading.Thread(target=self._record_loop, daemon=True).start()

    def stop_recording(self):
        self.stop_event.set()

    def _record_loop(self):
        try:
            res = recorder.watch_game(self.stop_event, on_tick=lambda r: self._tick(r))
            if res.ended_by in ("GameEnd", "api_gone"):
                time.sleep(2)  # 엔딩 화면까지 살짝 담는다
            stop_wall = self.rec.stop()
            with self.lock:
                self._set("analyzing", "하이라이트를 찾는 중...")
            self.analyze(self.video, res.raw_events, res.active, res.sync, stop_wall)
        except Exception as e:
            traceback.print_exc()
            with self.lock:
                self._set("error", str(e))

    def _tick(self, r):
        n = len(r.raw_events)
        with self.lock:
            if self.state == "recording":
                self.message = f"녹화 중 · 이벤트 {n}개 감지"

    # ---- 분석 ----
    def analyze(self, video, raw_events, active, sync, stop_wall=None, offset=None):
        duration, _ = render.probe(video)
        if offset is None:
            offset = recorder.video_offset(sync, stop_wall or time.time(), duration)
        norm = events.normalize(raw_events, events.me_names(active), offset)
        moments = events.build_moments(norm, duration)
        samples = events.pick_samples(moments, 3)
        out = []
        for m in samples:
            d = m.to_dict()
            pv = config.PREVIEW_DIR / f"{Path(video).stem}_{m.id}.mp4"
            render.render_preview(str(video), d, pv)
            d["preview"] = f"/files/previews/{pv.name}"
            out.append(d)
            self.moments[m.id] = d
        with self.lock:
            self.samples = out
            if out:
                self._set("ready", f"하이라이트 {len(out)}개를 찾았어요. 카테고리를 고르고 제출하세요")
            else:
                self._set("error", "하이라이트로 쓸 만한 장면을 찾지 못했어요 (킬/어시스트/오브젝트 이벤트 없음)")

    # ---- 제출 → 쇼츠 제작 ----
    def submit(self, category, sample_ids, music=None):
        if category not in events.CATEGORIES:
            raise ValueError("카테고리를 선택하세요")
        chosen = [self.moments[i] for i in sample_ids if i in self.moments]
        if not chosen:
            raise ValueError("샘플을 하나 이상 선택하세요")
        with self.lock:
            if self.state != "ready" and self.state != "done":
                raise RuntimeError("지금은 제출할 수 없습니다")
            self.result = None
            self._set("rendering", "쇼츠 제작 중...")
        threading.Thread(target=self._render, args=(category, chosen, music), daemon=True).start()

    def _render(self, category, chosen, music):
        try:
            out = config.OUT_DIR / f"short_{category}_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
            mp = config.MUSIC_DIR / music if music and (config.MUSIC_DIR / music).exists() else None
            dur = render.render_short(str(self.video), chosen, category, out, music=mp,
                                      log=lambda m: self._progress(m))
            label = chosen[0]["label_ko"].rstrip("!.")
            res = {"url": f"/files/out/{out.name}", "duration": round(dur, 1), "category": category,
                   "title": TITLE[category].format(l=label), "hashtags": CATEGORY_TAGS[category],
                   "filename": out.name}
            with self.lock:
                self.result = res
                self._set("done", "쇼츠가 완성됐어요!")
        except Exception as e:
            traceback.print_exc()
            with self.lock:
                self._set("error", str(e))

    def _progress(self, m):
        with self.lock:
            self.message = m

    # ---- 데모/수동 입력 ----
    def load_files(self, video, events_json):
        data = json.loads(Path(events_json).read_text(encoding="utf-8"))
        with self.lock:
            self.video, self.samples, self.result, self.moments = Path(video), [], None, {}
            self._set("analyzing", "하이라이트를 찾는 중...")
        threading.Thread(target=self._analyze_safe, args=(video, data), daemon=True).start()

    def _analyze_safe(self, video, data):
        try:
            self.analyze(video, data["events"], data.get("activePlayer", {}), [], offset=data.get("offset", 0.0))
        except Exception as e:
            traceback.print_exc()
            with self.lock:
                self._set("error", str(e))
