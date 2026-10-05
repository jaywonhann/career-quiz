"""Riot Live Client API 흉내 서버 (개발/테스트용). 사용: python -m lolshorts.tests.mock_lol_api [게임길이초]"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

GAME_LEN = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
T0 = time.time()
SCRIPT = [  # (게임시각, 이벤트)
    (5, {"EventName": "ChampionKill", "KillerName": "Hero", "VictimName": "A", "Assisters": []}),
    (8, {"EventName": "ChampionKill", "KillerName": "Hero", "VictimName": "B", "Assisters": []}),
    (8, {"EventName": "Multikill", "KillerName": "Hero", "KillStreak": 2}),
    (16, {"EventName": "ChampionKill", "KillerName": "C", "VictimName": "Hero", "Assisters": []}),
]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        gt = time.time() - T0
        if gt > GAME_LEN + 3 or not self.path.endswith("allgamedata"):
            self.send_response(404); self.end_headers(); return
        evs = [dict(e, EventID=i, EventTime=t) for i, (t, e) in enumerate(SCRIPT) if t <= gt]
        if gt >= GAME_LEN:
            evs.append({"EventID": 99, "EventName": "GameEnd", "EventTime": GAME_LEN, "Result": "Win"})
        body = json.dumps({"activePlayer": {"riotId": "Hero#KR1"}, "events": {"Events": evs},
                           "gameData": {"gameTime": gt}}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)


HTTPServer(("127.0.0.1", 2999), H).serve_forever()
