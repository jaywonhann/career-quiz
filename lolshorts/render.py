"""ffmpeg 로 세로(9:16) 쇼츠를 만든다. 카테고리(재미/멋/웃김)별로 다른 효과를 입힌다."""
import json
import subprocess
import tempfile
from pathlib import Path

from . import config
from .config import FFMPEG, FFPROBE, SHORT_FPS, SHORT_H, SHORT_W

FG_H = 608  # 1080 폭에서 16:9 의 높이


def run(cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("ffmpeg 실패:\n" + r.stderr[-1500:])


def probe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    return float(j["format"]["duration"]), any(s["codec_type"] == "audio" for s in j["streams"])


# ---------- 효과음 (외부 파일 없이 ffmpeg 로 합성) ----------
_SFX = {
    "boom": ["-f", "lavfi", "-i", "aevalsrc='sin(2*PI*(45+150*exp(-t*9))*t)*exp(-t*4.5)':d=1.1:s=44100"],
    "whoosh": ["-f", "lavfi", "-i", "anoisesrc=d=0.8:c=white:a=0.5", "-af",
               "bandpass=f=1800:w=1500,afade=t=in:d=0.55,afade=t=out:st=0.55:d=0.25"],
    "bonk": ["-f", "lavfi", "-i", "aevalsrc='sin(2*PI*(520*exp(-t*7)+90)*t)*exp(-t*6)':d=0.6:s=44100"],
    "ding": ["-f", "lavfi", "-i", "aevalsrc='(sin(2*PI*1568*t)+0.5*sin(2*PI*2352*t))*exp(-t*7)*0.5':d=0.8:s=44100"],
}


def sfx_path(name):
    p = config.SFX_DIR / f"{name}.wav"
    if not p.exists():
        run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *_SFX[name], "-ar", "44100", "-ac", "2", p])
    return p


# ---------- 카테고리별 효과 설계 ----------
def _atempo(s):
    if s >= 0.5:
        return f"atempo={s}"
    return f"atempo=0.5,atempo={round(s / 0.5, 4)}"


def plan_segments(m, category, ko):
    """한 장면을 여러 구간으로 나눈다. 구간: src 시작/길이, 속도, 효과 이름, 텍스트, 효과음."""
    s, e, p = m["start"], m["end"], m["peak"]
    label = m["label_ko"] if ko else m["label_en"]
    funny_txt = "ㅋㅋㅋㅋ" if ko else "LOL"
    replay_txt = "다시 보기" if ko else "REPLAY"

    def seg(a, b, speed, fx, text=None, sfx=None, sfx_at=0.0):
        a, b = max(s, a), min(e, b)
        return {"src": a, "dur": b - a, "speed": speed, "fx": fx, "text": text, "sfx": sfx, "sfx_at": sfx_at} \
            if b - a >= 0.25 else None

    if category == "cool":
        segs = [seg(s, p - 0.9, 1.0, "cool_in"),
                seg(p - 0.9, p + 1.0, 0.4, "cool_slow", label, "boom", 0.0),
                seg(p + 1.0, e, 1.0, "cool_out")]
    elif category == "fun":
        segs = [seg(s, p - 1.0, 1.6, "fun_fast", None, "whoosh", 0.0),
                seg(p - 1.0, p + 1.5, 1.0, "fun_peak", label, "ding", 0.0),
                seg(p + 1.5, e, 1.4, "fun_fast")]
    else:  # funny
        segs = [seg(s, p - 0.6, 1.0, "plain"),
                seg(p - 0.6, p + 1.0, 1.0, "funny_zoom", funny_txt, "bonk", 0.6),
                seg(p - 0.6, p + 1.0, 0.5, "funny_replay", replay_txt, "whoosh", 0.0),
                seg(p + 1.0, e, 1.0, "plain")]
    return [x for x in segs if x]


def fg_filter(fx, dur_out):
    """16:9 게임 화면(1080x608)에 입히는 효과. t 는 해당 구간 출력 시간(초)."""
    base = f"scale={SHORT_W}:-2"
    zoom_in = (f"scale=w='{SHORT_W}*(1+0.18*min(t/{max(dur_out, 0.1):.3f},1))':h=-2:eval=frame,"
               f"crop={SHORT_W}:{FG_H}")
    return {
        "plain": base,
        "cool_in": f"{base},eq=contrast=1.08:saturation=1.2,vignette=PI/6",
        "cool_slow": f"{zoom_in},eq=contrast=1.15:saturation=1.35:gamma=0.95,vignette=PI/4",
        "cool_out": f"{base},eq=contrast=1.08:saturation=1.2,vignette=PI/6",
        "fun_fast": f"{base},eq=saturation=1.4,hue=h='t*40'",
        "fun_peak": (f"scale={SHORT_W + 100}:-2,crop={SHORT_W}:{FG_H}:x='50+22*sin(t*55)':y='(ih-{FG_H})/2+12*cos(t*47)',"
                     "eq=saturation=1.5:brightness='if(lt(t,0.12),0.55,0)':eval=frame"),
        "funny_zoom": (f"scale={SHORT_W + 160}:-2,crop={SHORT_W}:{FG_H}:x='80+60*sin(t*70)':y='(ih-{FG_H})/2+30*cos(t*61)',"
                       "eq=contrast=1.2:brightness='if(lt(t,0.1),0.4,0)':eval=frame"),
        "funny_replay": (f"{base},colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131,vignette=PI/3.5"),
    }[fx]


def _escape_path(p):
    return str(p).replace("\\", "/").replace(":", "\\:")


def render_segment(video, has_audio, seg, out, tmp, ko_font):
    speed, src, dur_src = seg["speed"], seg["src"], seg["dur"]
    dur_out = dur_src / speed
    font, _ = ko_font
    text_filter = ""
    if seg["text"] and font:
        tf = Path(tmp) / f"t_{abs(hash((out.name, seg['text'])))}.txt"
        tf.write_text(seg["text"], encoding="utf-8")
        text_filter = (f",drawtext=fontfile='{_escape_path(font)}':textfile='{_escape_path(tf)}':fontsize=96:"
                       f"fontcolor=white:borderw=8:bordercolor=black@0.85:x=(w-text_w)/2:y='360-12*sin(t*9)':"
                       f"enable='between(t,0,{min(2.6, dur_out):.2f})'")
    vf = (f"[0:v]setpts=(PTS-STARTPTS)/{speed},fps={SHORT_FPS},split[a][b];"
          f"[a]scale={SHORT_W}:{SHORT_H}:force_original_aspect_ratio=increase,crop={SHORT_W}:{SHORT_H},"
          f"gblur=sigma=45,eq=brightness=-0.18:saturation=1.1[bg];"
          f"[b]{fg_filter(seg['fx'], dur_out)}[fg];"
          f"[bg][fg]overlay=(W-w)/2:(H-h)/2{text_filter},format=yuv420p[v]")
    cmd = [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{src:.3f}", "-t", f"{dur_src:.3f}", "-i", video]
    if has_audio:
        af = f"[0:a]{_atempo(speed)}," if speed != 1 else "[0:a]"
        af += "aresample=44100,aformat=channel_layouts=stereo"
        if speed < 0.8:
            af += ",lowpass=f=900,volume=0.7"
        af += "[aud]"
        fc = vf + ";" + af
    else:
        cmd += ["-f", "lavfi", "-t", f"{dur_out:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
        fc = vf + ";[1:a]anull[aud]"
    cmd += ["-filter_complex", fc, "-map", "[v]", "-map", "[aud]", "-t", f"{dur_out:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
            "-ar", "44100", "-ac", "2", "-r", str(SHORT_FPS), out]
    run(cmd)
    return dur_out


def render_preview(video, moment, out):
    """샘플 미리보기: 효과 없는 가벼운 세로 영상."""
    dur = moment["end"] - moment["start"]
    fc = (f"[0:v]split[a][b];[a]scale=540:960:force_original_aspect_ratio=increase,crop=540:960,gblur=sigma=25,"
          f"eq=brightness=-0.18[bg];[b]scale=540:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
    run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{moment['start']:.3f}", "-t", f"{dur:.3f}",
         "-i", video, "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "ultrafast",
         "-crf", "30", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", out])


def render_short(video, moments, category, out, music=None, log=lambda *_: None):
    """moments(dict 목록) 를 카테고리 효과로 이어붙여 쇼츠 한 편을 만든다."""
    duration, has_audio = probe(video)
    font = config.find_font()
    ko = font[1]
    if not font[0]:
        log("자막용 폰트를 찾지 못해 텍스트를 생략합니다 (LOLSHORTS_FONT 로 지정 가능)")
    out = Path(out)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        parts, sfx_events, t_cursor, total = [], [], 0.0, 0.0
        for mi, m in enumerate(moments):
            segs = plan_segments(m, category, ko)
            est = sum(s["dur"] / s["speed"] for s in segs)
            if total + est > config.MAX_SHORT_SEC and parts:
                log("길이 제한(59초)으로 일부 장면은 제외했습니다")
                break
            for si, seg in enumerate(segs):
                f = tmp / f"s{mi}_{si}.mp4"
                log(f"렌더링 {mi + 1}/{len(moments)} · {seg['fx']}")
                d = render_segment(str(video), has_audio, seg, f, tmp, font)
                if seg["sfx"]:
                    sfx_events.append((seg["sfx"], t_cursor + seg["sfx_at"]))
                parts.append(f)
                t_cursor += d
                total += d
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
        joined = tmp / "joined.mp4"
        run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
             "-c", "copy", joined])

        # 최종 오디오 믹스: 게임 소리 + 효과음 (+ 배경음악)
        inputs, chains, labels = ["-i", joined], ["[0:a]volume=0.85[g]"], ["[g]"]
        idx = 1
        if music:
            inputs += ["-stream_loop", "-1", "-i", music]
            chains.append(f"[{idx}:a]volume=0.28,atrim=0:{t_cursor:.2f},afade=t=in:d=0.5,afade=t=out:st={max(t_cursor - 1.2, 0):.2f}:d=1.2[mus]")
            labels.append("[mus]")
            idx += 1
        for name, at in sfx_events:
            inputs += ["-i", sfx_path(name)]
            ms = int(max(at, 0) * 1000)
            chains.append(f"[{idx}:a]volume=0.9,adelay={ms}|{ms}[x{idx}]")
            labels.append(f"[x{idx}]")
            idx += 1
        chains.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0,alimiter=limit=0.95[aout]")
        run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *inputs, "-filter_complex", ";".join(chains),
             "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", "-t", f"{t_cursor:.2f}", out])
    return t_cursor
