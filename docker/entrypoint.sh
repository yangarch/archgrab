#!/bin/sh
# 바인드 마운트된 /data 와 /secrets 는 호스트의 소유권을 그대로 들고 온다.
# 리눅스에서는 호스트 디렉터리가 보통 uid 1000 소유라 컨테이너 사용자(uid 10001)가
# 쓰지 못하고, 작업이 "권한 없음"으로 실패한다. root 로 잠깐 맞춰준 뒤 내려간다.
set -e

if [ "$(id -u)" = "0" ]; then
  chown -R archgrab:archgrab /data /secrets 2>/dev/null || true
  chmod 700 /secrets 2>/dev/null || true
  exec gosu archgrab "$@"
fi

# compose 에서 user: 를 지정해 이미 비root 로 들어온 경우
exec "$@"
