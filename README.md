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
| 추출 | `gallery-dl`(인스타 이미지·캐러셀·스토리) + `yt-dlp`(동영상) 이중 엔진, 어댑터로 감쌈 |
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

## 쿠키 등록

인스타 **스토리·비공개 계정**과 X 로그인 필요 영상은 쿠키가 있어야 한다.

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

## 외부에서 접속하기

포트를 직접 열지 말고 **Cloudflare Tunnel**을 권한다 — 인바운드 포트 개방이 필요 없고
TLS가 자동이며, Cloudflare Access로 2차 인증을 덧댈 수 있다. HTTPS 뒤에 두면
`.env`에 `ARCHGRAB_COOKIE_SECURE=true`를 넣는다. 자세한 설정은 M4에서 다룬다.

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
make test           # 단위 테스트 (네트워크 제외)
cd backend && ../.venv/bin/python -m pytest -m network   # 실제 추출까지 (쿠키 필요)
```

## 상태

- [x] **M0** 스캐폴딩 · 로그인 · 쿠키 저장 · SPA 서빙
- [x] **M1** 인스타그램 — 구현 완료. 단 **실제 콘텐츠 검증은 쿠키 등록 후**에 가능하다.
      파이프라인(큐·진행률·zip·전달·TTL)은 가짜 추출기로 통합 테스트됨. 쿠키 없이
      게시글을 요청하면 `LOGIN_REQUIRED` 로 올바르게 분류되는 것까지 실제 엔진으로 확인.
- [ ] **M2** X
- [ ] **M3** 유튜브
- [ ] **M4** 외부 노출 · 히스토리
