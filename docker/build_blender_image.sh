#!/bin/bash
# 통합 이미지 v3(Blender 포함) 빌드 · push — docker/Dockerfile.blender (2026-11-21).
#   docker/build_blender_image.sh            # 빌드만 (linux/amd64, 맥 arm64 에서 에뮬레이션)
#   docker/build_blender_image.sh --push     # 빌드 뒤 docker push
# 태그: ghcr.io/chaeee01/v2ua-all:v3-<빌드 날짜>-<레포 short sha>. 같은 태그가 레지스트리에 이미 있으면 멈춘다(덮어쓰지 않는다).
# 디스크: 베이스(압축 21.3 GB)를 containerd 스토어로 받으면 압축 blob + 풀린 스냅숏이 함께 남아 약 55 GB 가 든다(2026-11-21 추정).
#   65 GB 이상 비어 있을 때 돌린다.
# push: 베이스 18레이어는 이미 레지스트리에 있어 새 레이어만 올라간다 — docker push 를 먼저 쓴다(키체인 자격증명, 토큰 출력 없음).
#   긴 업로드가 VM 프록시에서 끊기면(2026-11-05, build_env_images.sh 머리말) skopeo 로 — 단 docker-daemon: 소스는 이미지 전체를
#   임시 파일로 풀 수 있어 그만큼(약 33 GB) 여유를 먼저 확인한다:
#     echo https://ghcr.io | docker-credential-desktop get | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["Username"]);print(d["Secret"])' \
#       | { read U; read P; printf %s "$P" | skopeo login ghcr.io --username "$U" --password-stdin; }
#     skopeo copy --retry-times 5 --dest-precompute-digests docker-daemon:<이미지> docker://<이미지>; skopeo logout ghcr.io
set -euo pipefail
cd "$(dirname "$0")/.."
NS=${GHCR_NS:-ghcr.io/chaeee01}
BASE=${BASE:-$NS/v2ua-all:v2-20261107-0aa8002}
SHA=$(git rev-parse --short HEAD)
[ -z "$(git status --porcelain -- docker/Dockerfile.blender docker/start.sh)" ] || { echo "Dockerfile.blender · start.sh 에 커밋 안 된 변경이 있다 — 커밋 뒤 빌드(라벨의 커밋과 내용이 맞아야 한다)"; exit 1; }
TAG=${TAG:-v3-$(date +%Y%m%d)-$SHA}
IMG=$NS/v2ua-all:$TAG
PUSH=0; [ "${1:-}" = "--push" ] && PUSH=1

echo "== $IMG  (베이스 $BASE, 레포 $SHA)"
if docker manifest inspect "$IMG" >/dev/null 2>&1; then echo "레지스트리에 같은 태그가 이미 있다 — 덮어쓰지 않는다: $IMG"; exit 1; fi
df -h /System/Volumes/Data | tail -1 | awk '{print "   디스크 여유 " $4}'

T0=$(date +%s)
docker build --platform linux/amd64 -f docker/Dockerfile.blender \
    --build-arg BASE="$BASE" --build-arg REPO_COMMIT="$(git rev-parse HEAD)" -t "$IMG" .
echo "   빌드 $(( $(date +%s) - T0 )) 초"
docker image inspect "$IMG" --format '{{.Size}}' | awk '{printf "   이미지 크기 %.2f GB\n", $1/1e9}'
docker image inspect "$IMG" --format '{{json .Config.Labels}}' | python3 -c 'import json,sys;d=json.load(sys.stdin);[print("   label",k,"=",v) for k,v in sorted(d.items()) if k.startswith("v2ua.") and k!="v2ua.note_vitpose_testdata"]'

if [ $PUSH = 1 ]; then
  T0=$(date +%s)
  docker push "$IMG"
  echo "   push $(( $(date +%s) - T0 )) 초"
fi
echo BUILD_DONE "$IMG"
