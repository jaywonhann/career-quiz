import argparse
import sys

from . import config


def main():
    ap = argparse.ArgumentParser(prog="lolshorts", description="LoL 하이라이트 쇼츠 메이커")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    if not config.have_ffmpeg():
        sys.exit("ffmpeg 를 찾을 수 없어요. https://ffmpeg.org 에서 설치 후 PATH 에 추가하세요.")
    from .server import serve
    serve(a.host, a.port)


main()
