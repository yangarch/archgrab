# archgrab

인스타그램 · X · 유튜브 URL을 넣으면 **원본 화질 그대로** 내려받는 개인용 웹 서비스.

- 붙여넣기 → 미리보기 → 항목·화질 선택 → 저장
- 캐러셀·다중 미디어는 항목별로 골라서, 여러 개면 zip으로
- **재인코딩 없음.** ffmpeg는 유튜브 DASH 무손실 mux(`-c copy`)에만 쓴다

> 본인 콘텐츠와 개인적 보관 용도를 전제로 만든 도구입니다. 각 플랫폼 이용약관과
> 저작권 범위 안에서 사용하세요. 내려받은 파일의 재배포는 별개 문제입니다.

## 구성

FastAPI 하나가 API와 React SPA를 함께 서빙한다. 컨테이너 1개, Redis 없음.

| 계층 | 내용 |
|---|---|
| 추출 | 플랫폼마다 다르다 — 인스타 `instagram-web`, X `gallery-dl`, 유튜브 `yt-dlp`. 어댑터로 감쌈 |
| 작업 | 인프로세스 asyncio 큐 + SQLite. 진행률은 SSE |
| 저장 | `data/{job_id}/`, TTL 경과 후 자동 삭제 |
| 인증 | 단일 비밀번호(scrypt) → 서명 세션 쿠키 |
| 쿠키 | 플랫폼별 `cookies.txt`를 `SECRET_KEY` 유도 키로 암호화해 `secrets/`에 0600 보관 |

## 시작하기

```bash
make install        # venv + 백엔드·프론트 의존성
make hashpw         # SECRET_KEY 와 비밀번호 해시 생성
```

출력된 두 줄을 `.env`에 넣는다 (`.env.example` 참고). 그다음:

```bash
make build-frontend
make dev            # http://127.0.0.1:8000
```

프론트를 고칠 때는 `make dev`와 `make dev-frontend`를 같이 띄운다
(Vite `:5173`이 `/api`를 `:8000`으로 프록시).

### 컨테이너

```bash
make up             # 127.0.0.1:8000 에만 바인딩된다
make logs
```

## 쿠키는 필수가 아니다

**공개 게시글·릴스·캐러셀은 쿠키 없이 원본 화질로 받을 수 있다.** 15장 캐러셀
(이미지 12 + 동영상 3)을 항목 하나도 빠뜨리지 않고 받는 것까지 실측 확인했다.

### 왜 엔진을 직접 만들었나

인스타그램에는 비로그인 전용 GraphQL 경로가 있다
(`PolarisLoggedOutDesktopWWWPostRootContentQuery`, 응답 필드
`if_not_gated_logged_out`). 세 엔진을 다 시험한 결과:

| 엔진 | 익명 접근 | 이미지 | 결론 |
|---|---|---|---|
| `yt-dlp` | ✅ | ❌ | 이미지 항목을 버린다 — 15장 캐러셀에서 동영상 3개만 남고 12개가 사라짐 (`No video formats found!`) |
| `gallery-dl` | ❌ | ✅ | 익명 접근 자체가 안 됨 — `browser=firefox`·`chrome`·`api=graphql` 모두 로그인 리다이렉트 |
| `instagram-web` | ✅ | ✅ | 같은 응답을 직접 읽는다. 이미지·동영상을 전부 열거 |

**X 는 사정이 다르다.** 같은 조사를 X 에 해보니 gallery-dl 이 익명으로 사진·동영상을
모두 처리했다(`type=photo` 로 종류까지 직접 준다). 그래서 X 는 커스텀 엔진 없이
gallery-dl 주력 + yt-dlp 동영상 폴백으로 끝난다. yt-dlp 는 X 에서도 사진 트윗에
"No video could be found" 로 실패하는 건 같다.

| 플랫폼 | 주력 | 폴백 | 쿠키 |
|---|---|---|---|
| 인스타그램 | `instagram-web` | gallery-dl(쿠키 시) → yt-dlp | 스토리·비공개만 |
| X | `gallery-dl` | yt-dlp | 비공개·민감 콘텐츠만 |
| 유튜브 | `yt-dlp` | — | 불필요 |

유튜브는 성격이 또 다르다. 한 영상에 포맷이 **44개**씩 오고 **완결(영상+음성)
포맷이 0개**다 — 전부 영상전용·음성전용이라 mux 가 선택이 아니라 필수다. 같은
해상도가 webm/mp4/HLS 로 중복되고, 4K 기준 webm 342MB vs mp4 229MB 라 고르지
않으면 더 크고 호환성 낮은 쪽이 기본이 된다. 그래서 해상도마다 하나씩만 남기고
(44 → 9), 같은 해상도면 직접 받을 수 있는 mp4 를 택한다.

합칠 음성도 컨테이너에 맞춘다. yt-dlp 의 `bestaudio` 는 품질만 보고 opus 를
고르는데 **opus-in-mp4 는 QuickTime·iOS 기본 재생기가 열지 못하는 경우가 많다.**
mp4 에는 m4a(AAC)를 붙인다.

그래서 `app/extractors/instagram_web.py` 를 두고 주력으로 쓴다. yt-dlp 는
동영상 폴백, gallery-dl 은 쿠키가 있을 때의 폴백이다.

### 전제 조건: TLS 지문 위장

**브라우저 TLS 지문 위장**이 되어야 한다. `curl_cffi` 가 그 역할을 하고, 그래서
선택 의존성이 아니라 정식 의존성으로 박아뒀다. 이게 없으면 익명 경로가 **조용히**
비활성되고 공개 게시글까지 "로그인 필요"처럼 실패한다.
`/api/engines` 의 `anonymous_instagram` 으로 현재 상태를 확인할 수 있다.

### 원본 화질을 고르는 규칙

이미지 후보(`image_versions2.candidates`)에는 url 만 있고 크기가 없다. 대신 CDN
URL 의 `stp` 파라미터가 서빙 크기를 정한다 — **크기 토큰이 없는 후보가 원본이다.**
실측: `stp=dst-jpegr_e35_tt6` → 3072×4096(보고된 `original_width/height` 와 일치),
`stp=...p1080x1080...` → 1080×1440.

동영상은 반대로 **해상도를 표시하지 않는다.** 노드의 `original_width/height` 는
업로더가 올린 크기이고 실제 서빙 렌디션은 더 작다(실측: 1080×1440 이라 보고한
항목의 실제 파일은 720×960). 모르는 값을 화면에 적으면 "보이는 것"과 "받는 것"이
어긋난다.

### 쿠키가 필요한 경우

**스토리·하이라이트·비공개 계정**뿐이다. 스토리는 설계상 로그인한 사용자에게만
보이므로 익명 경로가 존재하지 않는다.

1. 브라우저에서 Netscape 형식 `cookies.txt`를 내보낸다 (쿠키 내보내기 확장 사용)
2. 앱 설정 화면에서 플랫폼별로 업로드

쿠키는 암호화되어 저장되고 어떤 응답·로그에도 나오지 않는다(`mask_secrets`).
`SECRET_KEY`를 바꾸면 기존 쿠키는 복호화 불가라 재등록해야 한다.

세션 쿠키는 계정 활동으로 취급되므로 정지 위험이 아주 없지는 않다. 부담되면
부계정 쿠키를 쓰는 편이 안전하다.

## 추출이 깨졌을 때

인스타·X는 내부 API를 자주 바꾼다. 어제 되던 게 오늘 안 되는 일이 정상이다.

```bash
make update-engines    # 가장 먼저 할 일
```

`/api/engines`에서 현재 엔진 버전을 볼 수 있다. 그래도 안 되면 원인 코드를 확인한다:
`LOGIN_REQUIRED`(쿠키 필요·만료) · `PRIVATE` · `NOT_FOUND` · `RATE_LIMITED`(잠시 대기).
차단이 심하면 `.env`에 `ARCHGRAB_PROXY`를 지정한다.

## 개인 서버에 배포하기

`.env`, `data/`, `secrets/` 의 내용은 커밋되지 않으므로 **서버에서 새로 만든다.**

```bash
git clone https://github.com/yangarch/archgrab.git
cd archgrab
cp .env.example .env
```

### 1. 자격 증명 생성

Python venv가 있으면 `make install && make hashpw`, **Docker만 있으면**:

```bash
docker compose build
make hashpw-docker      # = docker compose run --rm --no-deps -it app python -m app.tools.hashpw
```

출력된 `ARCHGRAB_SECRET_KEY` 와 `ARCHGRAB_PASSWORD_HASH` 두 줄을 `.env` 에 넣는다.
`SECRET_KEY` 는 세션 서명과 쿠키 암호화 키 유도를 겸하므로 **서버마다 새로 만든다.**
(바꾸면 기존에 등록한 쿠키는 복호화 불가라 재등록해야 한다.)

### 2. HTTPS 뒤에 둘 것이므로

```bash
# .env
ARCHGRAB_COOKIE_SECURE=true
```

### 3. 기동

```bash
docker compose up -d
docker compose logs -f app
```

`docker-compose.yml` 은 포트를 **루프백에만** 묶는다(`127.0.0.1:8000:8000`).
인터넷에 직접 열지 않고 아래 터널을 통해 노출하는 것을 전제한 설정이다.

컨테이너는 root 로 시작해 바인드 마운트된 `/data`·`/secrets` 의 소유권을 맞춘 뒤
uid 10001 로 내려간다(`docker/entrypoint.sh`). 리눅스에서 호스트 디렉터리가
다른 uid 소유라 작업이 "권한 없음" 으로 실패하는 걸 막는다. 서버 프로세스 자체는
비root 다.

### 4-A. 외부 노출: 이미 nginx 가 있다면

앱은 루프백에만 묶여 있으니 nginx 가 앞에 서면 된다.

**인증서가 이미 있다면** `docker/nginx.conf.example` 을 복사해 도메인 2곳과
인증서 경로 2곳을 바꾼다.

```bash
sudo cp docker/nginx.conf.example /etc/nginx/sites-available/archgrab
sudo sed -i 's/archgrab\.example\.com/내도메인/g' /etc/nginx/sites-available/archgrab
sudo ln -s /etc/nginx/sites-available/archgrab /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**인증서를 새로 받아야 한다면** HTTP 전용 설정으로 먼저 띄운다. 인증서가 없는
상태로 SSL 블록을 올리면 `nginx -t` 부터 실패해서 certbot 을 돌릴 수 없다.

```bash
sudo cp docker/nginx-bootstrap.conf.example /etc/nginx/sites-available/archgrab
sudo sed -i 's/archgrab\.example\.com/내도메인/g' /etc/nginx/sites-available/archgrab
sudo ln -s /etc/nginx/sites-available/archgrab /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d 내도메인
```

이 동안에는 `.env` 의 `ARCHGRAB_COOKIE_SECURE` 를 **false** 로 두고, HTTPS 가
붙은 뒤 true 로 되돌린 다음 `docker compose up -d` 로 재기동한다.

이 앱에서 놓치기 쉬운 세 가지가 그 파일에 주석으로 적혀 있다:
**버퍼링 끄기**(진행률 SSE·큰 파일), **X-Forwarded-For**(로그인 레이트리밋이
이 헤더로 IP 를 본다), 그리고 **HTTPS 와 `COOKIE_SECURE=true` 는 한 쌍**이라는 점.

### 4-B. 외부 노출: Cloudflare Tunnel

포트를 직접 열지 않는다. 인바운드 개방이 필요 없고 TLS가 자동이며,
Cloudflare Access로 비밀번호 앞에 2차 인증을 덧댈 수 있다.

```bash
cloudflared tunnel login
cloudflared tunnel create archgrab
cloudflared tunnel route dns archgrab archgrab.example.com
cloudflared tunnel run --url http://127.0.0.1:8000 archgrab
```

대안: Tailscale(완전 사설망) / Caddy + 도메인 + Let's Encrypt.

### 배포 후 확인

```bash
curl -fsS http://127.0.0.1:8000/api/health              # {"status":"ok"}
curl -s  http://127.0.0.1:8000/api/engines              # anonymous_instagram 이 true 여야 한다
docker exec archgrab sh -c 'grep ^Uid /proc/1/status'   # 10001 (root 가 아님)
```

`anonymous_instagram` 이 false 면 `curl_cffi` 가 빠진 것이고, 그 상태로는
공개 게시글까지 "로그인 필요"로 실패한다.

## 개인정보·비밀값 유출 방어

두 층으로 막는다. 어느 한 층만으로는 새는 구멍이 있다.

**1층 — 깃 훅** (`.githooks/scan.py`, 커밋 주체가 사람이든 IDE든 무조건 통과)

경로 규칙과 내용 규칙을 함께 본다. 파일 이름을 바꿔 우회하면 내용 규칙이 잡고,
바이너리는 경로 규칙이 잡는다. 잡는 것: `.env`·쿠키·DB 경로, 실제 `SECRET_KEY`·
scrypt 해시·세션 토큰 값, 개인 키, **홈 디렉터리 경로(OS 사용자명 노출)**, 이메일 주소.

`.env.example` 의 빈 값과 `hashpw.py` 의 f-string 자리표시자는 오탐을 내지 않도록
값의 모양을 따로 검증한다 — 오탐을 내는 스캐너는 곧 아무도 신뢰하지 않게 된다.

```bash
make install-hooks   # core.hooksPath 는 커밋되지 않는다 — 클론마다 한 번 필요
make scan            # 스테이징된 내용 수동 검사
```

**2층 — Claude Code 하네스 훅** (`.claude/settings.json`)

깃 훅이 못 막는 세 가지를 덮는다: `--no-verify` 우회, 깃을 거치지 않는 전송
(`curl`·`scp`·`gh gist`·`rclone`…), 그리고 비밀 파일을 터미널에 출력해
대화 기록으로 흘리는 경우. `permissions.deny` 로 `.env`·`secrets/`·`data/` 에
대한 도구 읽기도 차단한다.

설정을 새로 받은 뒤에는 `/hooks` 를 한 번 열거나 Claude Code 를 재시작해야 활성화된다.

의도적으로 올려야 할 때만: `ARCHGRAB_ALLOW_SECRET=1 git commit ...`
(하네스 훅은 이 우회도 막으므로 터미널에서 직접 실행해야 한다.)

## 테스트

```bash
make test             # 백엔드 + 프론트엔드 전부
make test-backend     # pytest (네트워크 테스트 제외)
make test-frontend    # vitest
cd backend && ../.venv/bin/python -m pytest -m network   # 실제 추출까지
```

프론트엔드 테스트는 **jsdom** 에서 돈다. 레이아웃 엔진이 없으므로 가로 오버플로
같은 CSS 문제는 여기서 잡히지 않는다 — 그건 실제 브라우저로 확인해야 한다.
상태·피드백·렌더링 회귀를 고정하는 용도다. 실제로 겪은 버그들을 그대로 옮겼다:
새 URL 을 해석했을 때 이전 게시글의 선택이 남는 문제, 완료 시 무엇을 저장하는지
(zip 하나 vs 낱개 전부), 과거 작업이 새로고침마다 다시 저장되지 않는지,
한 항목을 받는 동안 다른 버튼이 잠기지 않는지.

## 상태

- [x] **M0** 스캐폴딩 · 로그인 · 쿠키 저장 · SPA 서빙
- [x] **M1** 인스타그램 — 쿠키 없이 종단 검증 완료. 15장 캐러셀(이미지 12 + 동영상 3)을
      전부 열거하고, 항목별로 골라 받고, 이미지가 원본 3072×4096 으로 내려오는 것까지
      `ffprobe` 실측. 항목마다 타입이 보이는 개별 다운로드 버튼 제공.
- [x] **M2** X — 사진·동영상 모두 쿠키 없이 동작. 실물 트윗 4건으로 종단 검증:
      사진 1장(1477×1108), 사진 2장(900×1200, 개별 선택·파일명 번호), 동영상
      2건(1280×720 / 1080×1080, h264+aac). `?s=` 추적 파라미터 제거 확인.
- [x] **M3** 유튜브 — 화질 선택(44개 포맷을 9개로 정리), 무손실 mux, 오디오만
      추출. 실물 검증: 360p 다운로드가 h264+aac 두 트랙, 오디오만은 m4a.
      표시 용량이 합쳐질 음성까지 포함해 실제 파일과 일치.
      **자막은 미구현.**
- [ ] **M4** 외부 노출 · 히스토리
