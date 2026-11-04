#!/bin/bash
# 환경 아카이브 3종 → 이미지 3개 빌드 (+ --push 면 GHCR 비공개 push). 맥(arm64)에서 linux/amd64 로 짓는다.
#   docker/build_env_images.sh [--push] [wham sam2v trellis2 ...]
# 전제: Docker Desktop 실행 중, 아카이브가 $ARCHIVES 에 있고 sha256 이 $ARCHIVES/sha256_pod_1102.txt 와 맞음,
#       push 하려면 GHCR_USER · GHCR_TOKEN(write:packages) 환경 변수 — 레포 .env 에 두지 않는다(출력에 안 찍음).
set -euo pipefail
ARCHIVES=${ARCHIVES:-$HOME/data/_env_archives}
NS=${GHCR_NS:?GHCR_NS=ghcr.io/<네임스페이스> 가 필요하다}
PUSH=0; ENVS=()
for a in "$@"; do [ "$a" = "--push" ] && PUSH=1 || ENVS+=("$a"); done
[ ${#ENVS[@]} -eq 0 ] && ENVS=(sam2v wham trellis2)
declare_tar() { case $1 in
  sam2v) echo sam2v_env_20260929_2b90b9f.tar.zst;; wham) echo wham_env_20261008_2b54f77.tar.zst;;
  trellis2) echo trellis2_env_20261008_75fbf01.tar.zst;; trellis) echo trellis_env_20261008_442aa1e.tar.zst;;
  *) echo "모르는 환경 $1" >&2; exit 1;; esac; }
cd "$(dirname "$0")/.."
( cd "$ARCHIVES" && grep -E "$(for e in "${ENVS[@]}"; do declare_tar $e; done | paste -sd'|' -)" sha256_pod_1102.txt | shasum -a 256 -c ) || { echo "아카이브 sha256 불일치 — 중단"; exit 1; }
# 재배포 금지 목록 (push 전 관례적 확인). 아카이브 목록(<아카이브>.filelist.txt, zstd -d | tar -t) 에서 찾아 빌드 때 제외한다.
#   wham: SMPL 본체 모델 — SMPL 라이선스(재배포 불가). 실행 시 볼륨에서 마운트.
#   그 밖의 체크포인트(WHAM · HMR2 · ViTPose · DPVO · YOLOv8 · SAM 2.1)는 연구/Apache/AGPL 등 제각각 — 비공개 레지스트리에만 둔다.
no_redist() { case $1 in wham) echo "repos/WHAM/dataset/body_models/smpl";; *) echo "";; esac; }
for e in "${ENVS[@]}"; do
  T=$(declare_tar $e); TAG=$(echo "$T" | sed -E 's/^[a-z0-9]+_env_([0-9]+)_([0-9a-f]+)\.tar\.zst$/\1-\2/')
  IMG="$NS/v2ua-$e:$TAG"; EX=$(no_redist $e)
  echo "== $e ← $T → $IMG  (제외: ${EX:-없음})"
  if [ -n "$EX" ]; then L="$ARCHIVES/${T%.tar.zst}.filelist.txt"; [ -f "$L" ] || { echo "아카이브 목록 $L 이 없다 — zstd -d -c | tar -t 로 먼저 만들 것"; exit 1; }
    echo "   제외 대상 항목 수: $(grep -c "^$EX" "$L")"; fi
  docker buildx build --platform linux/amd64 -f docker/Dockerfile.env --build-arg ENV_TAR="$T" --build-arg TAR_EXCLUDES="$EX" \
      --build-context archives="$ARCHIVES" -t "$IMG" --load .
  docker image inspect "$IMG" --format '{{.Size}}' | awk '{printf "   이미지 크기 %.1f GB\n", $1/1e9}'
  if [ $PUSH = 1 ]; then
    echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin >/dev/null
    docker push "$IMG"; docker logout ghcr.io >/dev/null
  fi
done
echo BUILD_DONE
