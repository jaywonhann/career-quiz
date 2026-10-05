import os
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("LOLSHORTS_DATA", BASE.parent / "data"))
REC_DIR = DATA / "recordings"
OUT_DIR = DATA / "out"
PREVIEW_DIR = DATA / "previews"
SFX_DIR = DATA / "sfx"
MUSIC_DIR = DATA / "music"  # 직접 쓸 수 있는 음원(저작권 free)을 여기에 넣으면 UI에서 고를 수 있다

for _d in (REC_DIR, OUT_DIR, PREVIEW_DIR, SFX_DIR, MUSIC_DIR):
    _d.mkdir(parents=True, exist_ok=True)

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
LOL_API = os.environ.get("LOL_API", "https://127.0.0.1:2999")

# 개발/테스트용: 실제 화면 대신 테스트 화면을 녹화한다
FAKE_CAPTURE = os.environ.get("LOLSHORTS_FAKE_CAPTURE") == "1"

SHORT_W, SHORT_H, SHORT_FPS = 1080, 1920, 30
MAX_SHORT_SEC = 58.0

# (경로, 한글 지원 여부)
_FONT_CANDIDATES = [
    ("C:/Windows/Fonts/malgunbd.ttf", True),
    ("C:/Windows/Fonts/malgun.ttf", True),
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", True),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", True),
    ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", True),
    ("C:/Windows/Fonts/arialbd.ttf", False),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", False),
]


def find_font():
    """(font_path, supports_korean). 환경변수 LOLSHORTS_FONT 로 직접 지정 가능(한글 폰트로 간주)."""
    env = os.environ.get("LOLSHORTS_FONT")
    if env and Path(env).exists():
        return env, True
    for path, ko in _FONT_CANDIDATES:
        if Path(path).exists():
            return path, ko
    return None, False


def default_capture_args(out_path):
    """플랫폼별 화면 캡처 입력 인자(ffmpeg)."""
    if FAKE_CAPTURE:
        return ["-re", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
                "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100"]
    audio = os.environ.get("LOLSHORTS_AUDIO_DEVICE")  # 예: "virtual-audio-capturer" (Windows dshow)
    if sys.platform == "win32":
        args = ["-f", "gdigrab", "-framerate", "60",
                "-i", os.environ.get("LOLSHORTS_WINDOW", "title=League of Legends (TM) Client")]
        if audio:
            args += ["-f", "dshow", "-i", f"audio={audio}"]
        return args
    if sys.platform == "darwin":
        return ["-f", "avfoundation", "-framerate", "60", "-i", f"1:{audio or 'none'}"]
    args = ["-f", "x11grab", "-framerate", "60", "-i", os.environ.get("DISPLAY", ":0")]
    if audio:
        args += ["-f", "pulse", "-i", audio]
    return args


def have_ffmpeg():
    return shutil.which(FFMPEG) is not None


def capture_has_audio():
    return FAKE_CAPTURE or bool(os.environ.get("LOLSHORTS_AUDIO_DEVICE"))
