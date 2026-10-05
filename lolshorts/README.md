# LoL 쇼츠 메이커

롤 플레이를 녹화하고, **잘한 장면(멀티킬·스틸·에이스 등)을 자동으로 찾아** 효과를 입힌 9:16 쇼츠(1080×1920)로 만들어 줍니다.

```
[녹화 시작] → 게임 플레이 → (게임 종료 감지 시 자동 정지) → 샘플 3개 미리보기
          → 카테고리 선택(재미/멋/웃김) → [제출] → 쇼츠 완성 + 제목/해시태그 + 다운로드
```

## 실행

필요한 것: Python 3.9+ 와 [ffmpeg](https://ffmpeg.org) (PATH 에 등록). 외부 패키지는 없습니다.

```
python -m lolshorts            # http://127.0.0.1:8765 접속
```

롤 없이 체험하려면 화면의 **데모로 체험** 버튼을 누르세요.

## 동작 방식

| 단계 | 방법 |
|---|---|
| 녹화 | ffmpeg 화면 캡처 (Windows `gdigrab`로 롤 클라이언트 창, macOS `avfoundation`, Linux `x11grab`) |
| 하이라이트 감지 | Riot 공식 **Live Client Data API** (`https://127.0.0.1:2999/liveclientdata/allgamedata`) 의 킬/멀티킬/에이스/오브젝트 스틸 이벤트. 화면을 추측하지 않으므로 정확합니다 |
| 게임 종료 감지 | `GameEnd` 이벤트 (또는 API 가 사라지면) → 녹화 자동 정지 |
| 샘플 3개 | 장면별로 멋/재미/웃김 점수를 매겨 카테고리별 베스트를 하나씩 추천 |
| 효과 | 카테고리별로 다름 (아래) |

### 카테고리별 효과

- **🎉 재미** — 접근 구간 1.6배속 → 핵심 장면 플래시 + 화면 흔들림 + 컬러 펌프, 효과음 *ding*
- **😎 멋** — 핵심 장면 0.4배 슬로모션 + 서서히 줌 + 비네팅 + 컬러 그레이딩, 효과음 *boom*
- **🤣 웃김** — 핵심 장면 강한 흔들림 후 세피아 0.5배 "다시 보기" 리플레이, 효과음 *bonk*

효과음은 ffmpeg 로 합성해서 외부 파일이 필요 없습니다. 배경음악을 쓰려면 `data/music/` 에 **직접 사용 권한이 있는** mp3/wav 를 넣으면 UI 에서 선택할 수 있습니다.

## 설정(환경변수)

| 변수 | 설명 |
|---|---|
| `LOLSHORTS_FONT` | 자막 폰트 경로 (한글 지원 폰트). 미지정 시 맑은 고딕/AppleSDGothic/Noto CJK 자동 탐색, 한글 폰트가 없으면 영문 자막 |
| `LOLSHORTS_WINDOW` | gdigrab 캡처 대상 (기본 `title=League of Legends (TM) Client`) |
| `LOLSHORTS_AUDIO_DEVICE` | 게임 소리 녹음 장치 (예: Windows `virtual-audio-capturer`). 없으면 무음 + 효과음/배경음악 |
| `LOLSHORTS_DATA` | 녹화/결과 저장 폴더 (기본 `./data`) |

## 개발/테스트

```
python -m lolshorts.tests.mock_lol_api 25     # 가짜 Live Client API (25초짜리 게임)
LOL_API=http://127.0.0.1:2999 LOLSHORTS_FAKE_CAPTURE=1 python -m lolshorts
```

## 한계 / 다음 단계

- Windows 실제 롤 환경에서의 캡처는 이 개발 환경(리눅스, 롤 없음)에서 직접 돌려보지 못했습니다. 창 캡처가 안 되면 `LOLSHORTS_WINDOW=desktop` 으로 전체 화면 캡처를 시도하세요.
- 롤 클라이언트는 "전체 화면"보다 **테두리 없는 창모드**일 때 gdigrab 캡처가 안정적입니다.
- 현재 감지는 내 킬/데스/어시/오브젝트 중심입니다. 다음 후보: 체력 낮은 상태 생존 킬(OCR), 오디오 환호성 보정, YouTube 업로드 API 연동.
