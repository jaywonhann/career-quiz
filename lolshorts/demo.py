"""LoL 없이 전체 흐름을 체험하는 데모: 가짜 영상 + Riot 형식의 가짜 이벤트."""
import json
import subprocess

from . import config

ME = "Hero#KR1"
RAW = [
    {"EventID": 1, "EventName": "GameStart", "EventTime": 0.0},
    {"EventID": 2, "EventName": "ChampionKill", "EventTime": 40.0, "KillerName": "Hero", "VictimName": "Foe1", "Assisters": []},
    {"EventID": 3, "EventName": "ChampionKill", "EventTime": 44.5, "KillerName": "Hero", "VictimName": "Foe2", "Assisters": ["Ally1"]},
    {"EventID": 4, "EventName": "Multikill", "EventTime": 44.5, "KillerName": "Hero", "KillStreak": 2},
    {"EventID": 5, "EventName": "ChampionKill", "EventTime": 49.0, "KillerName": "Hero", "VictimName": "Foe3", "Assisters": []},
    {"EventID": 6, "EventName": "Multikill", "EventTime": 49.0, "KillerName": "Hero", "KillStreak": 3},
    {"EventID": 7, "EventName": "ChampionKill", "EventTime": 120.0, "KillerName": "Foe4", "VictimName": "Hero", "Assisters": ["Foe5"]},
    {"EventID": 8, "EventName": "BaronKill", "EventTime": 200.0, "KillerName": "Hero", "Assisters": ["Ally1"], "Stolen": "True"},
]
DURATION = 230


def load_demo(session):
    video = config.REC_DIR / "demo.mp4"
    if not video.exists():
        subprocess.run([config.FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={DURATION}",
                        "-f", "lavfi", "-i", f"sine=frequency=220:duration={DURATION}",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", video],
                       check=True)
    ev = config.REC_DIR / "demo_events.json"
    ev.write_text(json.dumps({"activePlayer": {"riotId": ME, "summonerName": "Hero"}, "events": RAW, "offset": 0.0}))
    session.load_files(video, ev)
