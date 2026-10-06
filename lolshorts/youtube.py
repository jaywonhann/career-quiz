"""YouTube Data API v3 업로드 (외부 패키지 없음). OAuth 로컬 리디렉션 + resumable upload."""
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPE = "https://www.googleapis.com/auth/youtube.upload"
CHUNK = 8 * 1024 * 1024  # 256KB 의 배수여야 한다

YT_DIR = config.DATA / "youtube"
YT_DIR.mkdir(parents=True, exist_ok=True)
SECRET_FILE = YT_DIR / "client_secret.json"   # Google Cloud 에서 받은 OAuth 클라이언트(데스크톱 앱)
TOKEN_FILE = YT_DIR / "token.json"            # 로그인 후 자동 생성 (refresh token 포함)

_pending_states = set()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # 308 "Resume Incomplete" 를 리디렉션으로 오인하지 않게
        return None


_opener = urllib.request.build_opener(_NoRedirect)


class YouTubeError(RuntimeError):
    pass


def _client():
    if not SECRET_FILE.exists():
        raise YouTubeError(f"client_secret.json 이 없습니다. README 의 'YouTube 설정'을 따라 {SECRET_FILE} 에 넣어주세요.")
    j = json.loads(SECRET_FILE.read_text(encoding="utf-8"))
    c = j.get("installed") or j.get("web")
    if not c:
        raise YouTubeError("client_secret.json 형식이 올바르지 않습니다 (데스크톱 앱 유형이어야 합니다)")
    return c["client_id"], c["client_secret"]


def _post_form(url, data):
    req = urllib.request.Request(url, urllib.parse.urlencode(data).encode(),
                                 {"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise YouTubeError(f"Google 인증 오류: {e.read().decode(errors='replace')[:300]}")


def configured():
    return SECRET_FILE.exists()


def connected():
    return TOKEN_FILE.exists()


def auth_url(redirect_uri):
    cid, _ = _client()
    state = secrets.token_urlsafe(16)
    _pending_states.add(state)
    q = {"client_id": cid, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
         "access_type": "offline", "prompt": "consent", "state": state}
    return AUTH_URL + "?" + urllib.parse.urlencode(q)


def finish_auth(code, state, redirect_uri):
    if state not in _pending_states:
        raise YouTubeError("잘못된 인증 요청입니다 (state 불일치)")
    _pending_states.discard(state)
    cid, cs = _client()
    tok = _post_form(TOKEN_URL, {"code": code, "client_id": cid, "client_secret": cs,
                                 "redirect_uri": redirect_uri, "grant_type": "authorization_code"})
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    TOKEN_FILE.write_text(json.dumps(tok))
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass


def disconnect():
    TOKEN_FILE.unlink(missing_ok=True)


def _access_token():
    if not TOKEN_FILE.exists():
        raise YouTubeError("YouTube 계정이 연결되지 않았습니다")
    tok = json.loads(TOKEN_FILE.read_text())
    if time.time() >= tok.get("expires_at", 0):
        if not tok.get("refresh_token"):
            raise YouTubeError("로그인이 만료됐어요. 다시 연결해주세요")
        cid, cs = _client()
        new = _post_form(TOKEN_URL, {"refresh_token": tok["refresh_token"], "client_id": cid,
                                     "client_secret": cs, "grant_type": "refresh_token"})
        tok.update(new)
        tok["expires_at"] = time.time() + new.get("expires_in", 3600) - 60
        TOKEN_FILE.write_text(json.dumps(tok))
    return tok["access_token"]


def _shorts_text(title, description):
    """쇼츠로 분류되도록 #Shorts 를 보장하고 제목 100자 제한을 지킨다."""
    title = title.strip()
    if "#shorts" not in (title + description).lower():
        description = (description.strip() + "\n#Shorts").strip()
    return title[:100], description[:4900]


def upload(path, title, description, privacy="private", progress=lambda frac: None):
    """영상을 업로드하고 영상 URL 을 돌려준다."""
    if privacy not in ("private", "unlisted", "public"):
        raise YouTubeError("공개 범위가 올바르지 않습니다")
    title, description = _shorts_text(title or "LoL Shorts", description or "")
    size = os.path.getsize(path)
    meta = {"snippet": {"title": title, "description": description, "categoryId": "20"},  # 20 = Gaming
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    token = _access_token()
    init = urllib.request.Request(
        UPLOAD_URL + "?uploadType=resumable&part=snippet,status", json.dumps(meta).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
         "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    try:
        with urllib.request.urlopen(init, timeout=30) as r:
            session_url = r.headers["Location"]
    except urllib.error.HTTPError as e:
        raise YouTubeError(_api_error(e))

    sent = 0
    with open(path, "rb") as f:
        while sent < size:
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            req = urllib.request.Request(session_url, chunk, {
                "Content-Length": str(len(chunk)), "Content-Range": f"bytes {sent}-{end}/{size}"}, method="PUT")
            for attempt in range(4):  # 일시적 네트워크/5xx 는 재시도
                try:
                    with _opener.open(req, timeout=120) as r:
                        body = json.load(r)
                        progress(1.0)
                        return f"https://youtube.com/shorts/{body['id']}"
                except urllib.error.HTTPError as e:
                    if e.code == 308:  # 이어서 업로드
                        break
                    if e.code >= 500 and attempt < 3:
                        time.sleep(2 ** attempt)
                        continue
                    raise YouTubeError(_api_error(e))
                except (urllib.error.URLError, TimeoutError):
                    if attempt == 3:
                        raise YouTubeError("네트워크 오류로 업로드에 실패했습니다")
                    time.sleep(2 ** attempt)
            sent = end + 1
            progress(sent / size)
    raise YouTubeError("업로드 응답을 받지 못했습니다")


def _api_error(e):
    body = e.read().decode(errors="replace")
    try:
        err = json.loads(body)["error"]
        reasons = [x.get("reason") for x in err.get("errors", [])]
        if "quotaExceeded" in reasons:
            return "YouTube 일일 API 할당량을 초과했어요 (내일 다시 시도)"
        if "uploadLimitExceeded" in reasons:
            return "YouTube 일일 업로드 한도를 초과했어요"
        return f"YouTube 오류 {e.code}: {err.get('message', body)[:200]}"
    except Exception:
        return f"YouTube 오류 {e.code}: {body[:200]}"
