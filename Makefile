.PHONY: help venv install install-hooks hashpw hashpw-docker test test-backend test-frontend dev dev-frontend test build-frontend up down logs update-engines clean

BACKEND := backend
VENV    := .venv
PY      := $(CURDIR)/$(VENV)/bin/python
PIP     := $(CURDIR)/$(VENV)/bin/pip

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | column -t -s "$$(printf '\t')"

$(VENV)/bin/python:
	python3 -m venv $(VENV)

install: $(VENV)/bin/python install-hooks ## 백엔드·프론트 의존성 설치 + 깃 훅 활성화
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e "./$(BACKEND)[dev]"
	cd frontend && npm install

install-hooks: ## 비밀값 검사 깃 훅 활성화 (core.hooksPath 는 커밋되지 않으므로 클론마다 필요)
	@git config core.hooksPath .githooks
	@chmod +x .githooks/pre-commit .githooks/pre-push .githooks/scan.py
	@echo "깃 훅 활성화: $$(git config core.hooksPath)"

scan: ## 스테이징된 내용을 수동으로 검사
	@python3 .githooks/scan.py commit && echo "통과 — 올려도 되는 내용입니다"

hashpw: ## SECRET_KEY 와 비밀번호 해시 생성 (.env 에 붙여넣기)
	cd $(BACKEND) && $(PY) -m app.tools.hashpw

hashpw-docker: ## 해시 생성 (Docker 만 있는 서버용 — venv 불필요)
	docker compose run --rm --no-deps -it app python -m app.tools.hashpw

dev: ## 백엔드 개발 서버 (:8000)
	cd $(BACKEND) && $(CURDIR)/$(VENV)/bin/uvicorn app.main:app --reload --port 8000

dev-frontend: ## 프론트 개발 서버 (:5173, /api → :8000 프록시)
	cd frontend && npm run dev

test: test-backend test-frontend ## 전체 테스트

test-backend: ## 백엔드 단위 테스트 (네트워크 테스트 제외)
	cd $(BACKEND) && $(PY) -m pytest

test-frontend: ## 프론트엔드 테스트 (jsdom — 레이아웃은 검증하지 못한다)
	cd frontend && npm test

build-frontend: ## 프론트 빌드 → backend/static
	cd frontend && npm run build

up: ## 컨테이너 기동
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f app

update-engines: ## 인스타/X 추출이 깨졌을 때 가장 먼저 할 일
	$(PIP) install -q --upgrade yt-dlp gallery-dl
	@cd $(BACKEND) && $(PY) -c "import yt_dlp; print('yt-dlp', yt_dlp.version.__version__)"

clean: ## 받은 파일 정리 (쿠키는 건드리지 않음)
	rm -rf data/*/ 
