"""Riot 이벤트 → 하이라이트 '순간(Moment)' 변환 및 점수화."""
from dataclasses import dataclass, field, asdict

CATEGORIES = ("fun", "cool", "funny")  # 재미 / 멋 / 웃김
CATEGORY_KO = {"fun": "재미", "cool": "멋", "funny": "웃김"}
STREAK_EN = {2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUADRA KILL", 5: "PENTAKILL"}
STREAK_KO = {2: "더블킬!", 3: "트리플킬!", 4: "쿼드라킬!", 5: "펜타킬!!"}
CLUSTER_GAP = 10.0   # 이 간격(초) 안의 이벤트는 한 장면으로 묶는다
PRE, POST = 6.0, 4.0  # 첫 이벤트 전/마지막 이벤트 후 여유
MAX_MOMENT = 20.0


def _base(name):
    return (name or "").split("#")[0].strip().lower()


def me_names(active):
    out = set()
    for k in ("summonerName", "riotIdGameName", "riotId"):
        if active.get(k):
            out.add(_base(active[k]))
    return out


def normalize(raw_events, me, offset):
    """Riot Live Client 이벤트를 {t, kind, n} 목록으로. offset = 영상시간 - 게임시간."""
    def is_me(n):
        return _base(n) in me

    out = []
    for e in raw_events:
        name, t = e.get("EventName"), float(e.get("EventTime", 0)) + offset
        if name == "ChampionKill":
            if is_me(e.get("KillerName")):
                out.append({"t": t, "kind": "kill", "n": 1})
            elif is_me(e.get("VictimName")):
                out.append({"t": t, "kind": "death", "n": 1})
            elif any(is_me(a) for a in e.get("Assisters", [])):
                out.append({"t": t, "kind": "assist", "n": 1})
        elif name == "Multikill" and is_me(e.get("KillerName")):
            out.append({"t": t, "kind": "multikill", "n": int(e.get("KillStreak", 2))})
        elif name == "Ace" and is_me(e.get("Acer")):
            out.append({"t": t, "kind": "ace", "n": 1})
        elif name in ("DragonKill", "BaronKill", "HeraldKill"):
            if is_me(e.get("KillerName")):
                stolen = str(e.get("Stolen", "")).lower() == "true"
                out.append({"t": t, "kind": "steal" if stolen else "objective", "n": 1})
            elif any(is_me(a) for a in e.get("Assisters", [])):
                out.append({"t": t, "kind": "objective", "n": 1})
    return out


@dataclass
class Moment:
    id: int
    start: float
    end: float
    peak: float
    kinds: list = field(default_factory=list)
    scores: dict = field(default_factory=dict)
    label_en: str = "HIGHLIGHT"
    label_ko: str = "하이라이트"
    best: str = "fun"

    def to_dict(self):
        d = asdict(self)
        d["duration"] = round(self.end - self.start, 2)
        return d


def _score(ev):
    c = lambda k: sum(1 for e in ev if e["kind"] == k)
    kills, deaths, assists = c("kill"), c("death"), c("assist")
    streak = max([e["n"] for e in ev if e["kind"] == "multikill"] or [1])
    ace, steal, obj = c("ace"), c("steal"), c("objective")
    cool = 3 * kills + 8 * (streak - 1) + 6 * ace + 10 * steal + 2 * obj
    fun = 2 * kills + 1.5 * assists + 3 * obj + 4 * ace + 6 * steal + 1.5 * (kills + assists + deaths > 3)
    funny = 6 * deaths + (4 * min(kills, deaths)) + (3 if deaths and not kills else 0) + 0.5 * kills * (deaths > 0)
    if not cool and not deaths:
        cool = 0.5 * assists
    return {"cool": round(cool, 1), "fun": round(fun, 1), "funny": round(funny, 1)}, streak


def _label(ev, streak):
    kinds = {e["kind"] for e in ev}
    if "steal" in kinds:
        return "STEAL!", "스틸!"
    if streak >= 2:
        return STREAK_EN.get(streak, "MULTI KILL"), STREAK_KO.get(streak, "멀티킬!")
    if "ace" in kinds:
        return "ACE!", "에이스!"
    if "death" in kinds and "kill" not in kinds:
        return "OOPS...", "이게 죽네..."
    if "death" in kinds:
        return "TRADE!", "맞교환!"
    if "kill" in kinds:
        return "KILL!", "킬!"
    if "objective" in kinds:
        return "OBJECTIVE", "오브젝트!"
    return "HIGHLIGHT", "하이라이트"


def build_moments(norm, video_duration):
    evs = sorted((e for e in norm if 0 <= e["t"] <= video_duration), key=lambda e: e["t"])
    clusters, cur = [], []
    for e in evs:
        if cur and e["t"] - cur[-1]["t"] > CLUSTER_GAP:
            clusters.append(cur)
            cur = []
        cur.append(e)
    if cur:
        clusters.append(cur)

    weight = {"multikill": 5, "steal": 5, "ace": 4, "kill": 3, "death": 3, "objective": 2, "assist": 1}
    moments = []
    for i, ev in enumerate(clusters):
        scores, streak = _score(ev)
        if max(scores.values()) <= 0:
            continue
        peak_ev = max(ev, key=lambda e: (weight[e["kind"]], e["n"]))
        start = max(0.0, ev[0]["t"] - PRE)
        end = min(video_duration, ev[-1]["t"] + POST)
        if end - start > MAX_MOMENT:  # 너무 길면 peak 중심으로 자른다
            start = max(0.0, min(start, peak_ev["t"] - 10))
            end = min(video_duration, start + MAX_MOMENT)
        en, ko = _label(ev, streak)
        m = Moment(id=i, start=round(start, 2), end=round(end, 2), peak=round(min(max(peak_ev["t"], start), end), 2),
                   kinds=sorted({e["kind"] for e in ev}), scores=scores, label_en=en, label_ko=ko)
        m.best = max(scores, key=scores.get)
        moments.append(m)
    return moments


def pick_samples(moments, n=3):
    """카테고리별 베스트를 하나씩 뽑고, 모자라면 총점순으로 채운다."""
    picked = []
    for cat in ("cool", "fun", "funny"):
        pool = [m for m in moments if m not in picked and m.scores[cat] > 0]
        if pool:
            best = max(pool, key=lambda m: m.scores[cat])
            best.best = cat
            picked.append(best)
    for m in sorted(moments, key=lambda m: -sum(m.scores.values())):
        if len(picked) >= n:
            break
        if m not in picked:
            picked.append(m)
    return sorted(picked[:n], key=lambda m: m.start)
