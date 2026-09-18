"""작업 파이프라인 통합 테스트.

인스타 쿠키 없이도 큐→워커→진행률→패키징→파일 전달→TTL 정리 전체를 검증하려고
가짜 추출기를 끼운다. 엔진 바깥의 모든 배선이 여기서 걸린다.
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.models import MediaInfo
from app.core.url import Kind, ParsedUrl, Platform
from app.extractors.base import ProgressCallback, ProgressEvent, Selection
from tests.conftest import TEST_PASSWORD

POST_URL = "https://www.instagram.com/p/CxYzAbC123/"


class FakeExtractor:
    """3개 항목을 만들어내는 추출기. 실제 네트워크를 쓰지 않는다."""

    name = "fake"

    def __init__(self, count: int = 3) -> None:
        self.count = count
        self.download_calls = 0

    def probe(self, parsed: ParsedUrl) -> MediaInfo:
        return MediaInfo(
            platform=parsed.platform, kind=parsed.kind, source_url=parsed.url,
            key=parsed.key, items=[], engine=self.name,
        )

    def download(
        self, parsed: ParsedUrl, selection: Selection, dest: Path, progress: ProgressCallback
    ) -> list[Path]:
        self.download_calls += 1
        paths: list[Path] = []
        for index in range(self.count):
            if not selection.wants(str(index)):
                continue
            target = dest / f"instagram_someone_{parsed.key}_{index + 1}.jpg"
            payload = bytes([index]) * 2048
            target.write_bytes(payload)
            paths.append(target)
            progress(
                ProgressEvent(
                    done_bytes=len(payload), total_bytes=len(payload),
                    current=target.name, index=len(paths), count=self.count,
                )
            )
            time.sleep(0.3)      # 진행률 스로틀(0.25s)을 넘겨 이벤트가 실제로 나가게 한다
        return paths


@pytest.fixture
def client(env, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001, ANN201, ARG001
    from app.extractors import registry
    from app.main import app

    fake = FakeExtractor()
    monkeypatch.setitem(registry._EXTRACTORS, Platform.INSTAGRAM, fake)

    with TestClient(app) as test_client:
        test_client.post("/api/auth/login", json={"password": TEST_PASSWORD})
        test_client.extractor = fake       # type: ignore[attr-defined]
        yield test_client


def _wait(client: TestClient, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "error", "canceled"}:
            return job
        time.sleep(0.1)
    raise AssertionError(f"작업이 {timeout}초 안에 끝나지 않았습니다: {job}")


def test_full_job_produces_files_and_zip(client: TestClient) -> None:
    created = client.post("/api/jobs", json={"url": POST_URL})
    assert created.status_code == 200
    job = _wait(client, created.json()["job_id"])

    assert job["status"] == "done", job
    assert job["progress"]["percent"] == 100.0

    names = [f["name"] for f in job["files"]]
    # 개별 파일 3개 + 여러 개일 때 추가되는 zip 1개
    assert len(names) == 4
    assert sum(1 for n in names if n.endswith(".zip")) == 1
    assert sum(1 for n in names if n.endswith(".jpg")) == 3
    assert job["expires_at"] is not None


def test_downloaded_bytes_match_and_zip_holds_every_file(client: TestClient) -> None:
    job = _wait(client, client.post("/api/jobs", json={"url": POST_URL}).json()["job_id"])

    images = [f for f in job["files"] if f["name"].endswith(".jpg")]
    for index, entry in enumerate(sorted(images, key=lambda f: f["name"])):
        response = client.get(f"/api/files/{entry['token']}")
        assert response.status_code == 200
        # 원본 그대로 — 바이트 단위로 같아야 한다
        assert response.content == bytes([index]) * 2048
        assert "attachment" in response.headers["content-disposition"]

    archive = next(f for f in job["files"] if f["name"].endswith(".zip"))
    zip_bytes = client.get(f"/api/files/{archive['token']}").content
    tmp = Path("/tmp") / "archgrab-test.zip"
    tmp.write_bytes(zip_bytes)
    try:
        with zipfile.ZipFile(tmp) as handle:
            assert len(handle.namelist()) == 3
    finally:
        tmp.unlink(missing_ok=True)


def test_selection_limits_which_items_are_fetched(client: TestClient) -> None:
    job = _wait(
        client,
        client.post("/api/jobs", json={"url": POST_URL, "item_ids": ["1"]}).json()["job_id"],
    )
    assert job["status"] == "done"
    # 한 개만 골랐으므로 zip 없이 파일 하나
    assert [f["name"].endswith(".jpg") for f in job["files"]] == [True]


def test_forged_token_is_rejected(client: TestClient) -> None:
    job = _wait(client, client.post("/api/jobs", json={"url": POST_URL}).json()["job_id"])
    token = job["files"][0]["token"]
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    assert client.get(f"/api/files/{tampered}").status_code == 404


def test_unsupported_url_never_creates_a_job(client: TestClient) -> None:
    response = client.post("/api/jobs", json={"url": "https://example.com/whatever"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNSUPPORTED"
    assert client.get("/api/jobs").json() == []


def test_sse_stream_reports_progress_then_terminal_state(client: TestClient) -> None:
    job_id = client.post("/api/jobs", json={"url": POST_URL}).json()["job_id"]

    events: list[str] = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        for line in stream.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if line.startswith("data:") and '"status": "done"' in line.replace('":"', '": "'):
                break
            if len(events) > 40:
                break

    assert "state" in events
    assert "progress" in events, f"진행률 이벤트가 오지 않았습니다: {events}"


def test_reaper_removes_expired_job_files(client: TestClient) -> None:
    import asyncio

    from app.config import get_settings
    from app.jobs import reaper, store

    job = _wait(client, client.post("/api/jobs", json={"url": POST_URL}).json()["job_id"])
    job_id = job["id"]
    job_dir = get_settings().data_dir / job_id
    assert job_dir.is_dir()

    async def expire_and_sweep() -> int:
        await store.update(job_id, expires_at=time.time() - 1)
        return await reaper.sweep_once()

    assert asyncio.run(expire_and_sweep()) >= 1
    assert not job_dir.exists()
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
