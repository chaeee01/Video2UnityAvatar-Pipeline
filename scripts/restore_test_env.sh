#!/usr/bin/env bash
# 환경 아카이브 복원 시험 (RUNBOOK 8절). 아카이브가 실제로 되살아나는지 Pod 에서 확인한다.
#
#   bash scripts/restore_test_env.sh <wham|trellis|trellis2|all> [--probe-only]
#
# 하는 일 (환경 하나당):
#   원본 환경·레포를 **지우지 않고 이름만 바꿔** 옆에 둔다 (<이름>_orig)
#   → 아카이브를 /workspace 의 **정규 경로**에 푼다
#   → pip freeze 대조 · import 점검(restore_probe.py) · 기능 확인
#   → 복원본을 지우고 원본을 되돌린다 (도중에 죽어도 trap 으로 되돌린다)
#
# 다른 경로에 나란히 풀지 않는다. conda 환경은 절대 경로에 묶여 있어, 원본이 살아 있는 채로
# 다른 경로에 풀면 복원본이 원본을 참조하며 통과한다 — 2026-09-29 sam2 의 거짓 통과가 그 경우다.
#
# 필요한 여유: 환경 하나의 압축 전 크기 (wham 약 18GB · trellis 약 21GB · trellis2 약 15GB).
# 시작 전에 du 합계로 볼륨 사용량을 잰다 (RUNBOOK 1절 — df 로는 쿼터를 알 수 없다).
#
# --probe-only  기능 확인(S5·S3 재실행)을 건너뛰고 복원 + import 점검만 한다.
#
# 2026-10-09 에 3종을 이 절차로 시험해 전부 통과했다. 이 파일은 그때 쓴 스크립트 둘
# (본 시험 + wham 재점검)을 합치고 점검 결함을 고친 판이다 — **고친 판은 Pod 에서 아직
# 돌려 보지 않았다.** sam2 는 scripts/setup_sam2.sh --check 로 따로 본다 (9/29 완료).
set -uo pipefail
export PYTHONUNBUFFERED=1
VOL=/workspace
MM=$VOL/micromamba/bin/micromamba
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$VOL/logs/restore_$(date +%Y%m%d_%H%M%S)
export MAMBA_ROOT_PREFIX=$VOL/micromamba

TARGET="${1:?대상을 지정하세요: wham | trellis | trellis2 | all}"
PROBE_ONLY=0
[ "${2:-}" = "--probe-only" ] && PROBE_ONLY=1
mkdir -p "$OUT"

latest() { ls -t $VOL/archives/$1_env_*.tar.zst 2>/dev/null | head -1; }

restore_one() {   # 이름 환경 레포 "모듈들"
  local name=$1 env=$VOL/micromamba/envs/$2 repo=$VOL/repos/$3 mods=$4
  local arc; arc=$(latest "$name")
  echo; echo "################ $name  $(date +%T)"
  [ -n "$arc" ] || { echo "중단: 아카이브 없음 ($VOL/archives/${name}_env_*.tar.zst)"; return 1; }
  if [ -e "${env}_orig" ] || [ -e "${repo}_orig" ]; then echo "중단: _orig 가 이미 있다 — 지난 시험이 덜 끝났다"; return 1; fi
  echo "[0] 아카이브 $(basename "$arc") $(du -h "$arc" | cut -f1)"
  $MM run -n "$2" pip freeze 2>/dev/null | sort > "$OUT/${name}_freeze_before.txt"
  echo "[1] 원본 기록: pip $(wc -l < "$OUT/${name}_freeze_before.txt")줄, env $(du -sh "$env" | cut -f1), repo $(du -sh "$repo" | cut -f1)"
  mv "$env" "${env}_orig" && mv "$repo" "${repo}_orig" || { echo "이름 변경 실패"; return 1; }
  back() {   # 어떤 경우에도 원본을 되돌린다. 복원본은 _orig 가 있을 때만 지운다
    if [ -d "${env}_orig" ]; then [ -d "$env" ] && rm -rf "$env"; mv "${env}_orig" "$env"; fi
    if [ -d "${repo}_orig" ]; then [ -d "$repo" ] && rm -rf "$repo"; mv "${repo}_orig" "$repo"; fi
  }
  trap back EXIT
  echo "[2] 원본을 옆으로: $(basename "${env}_orig"), $(basename "${repo}_orig")"
  local verdict=PASS t0; t0=$(date +%s)
  # micromamba 바이너리는 풀지 않는다 — 지금 쓰고 있는 파일이다. 대신 해시를 대조한다.
  tar --use-compress-program="zstd -d -T0" -xf "$arc" -C $VOL --exclude="micromamba/bin/micromamba"
  local rc=$?
  echo "[3] 복원 rc=$rc $(( $(date +%s)-t0 ))초  env $(du -sh "$env" 2>/dev/null | cut -f1) repo $(du -sh "$repo" 2>/dev/null | cut -f1)"
  [ $rc -eq 0 ] || verdict=FAIL
  local a b
  a=$(tar --use-compress-program="zstd -d -T0" -xOf "$arc" micromamba/bin/micromamba | sha256sum | cut -c1-16)
  b=$(sha256sum $MM | cut -c1-16)
  echo "[4] micromamba 바이너리: 아카이브 $a / 현재 $b  $([ "$a" = "$b" ] && echo 일치 || echo 불일치)"
  [ "$a" = "$b" ] || verdict=FAIL
  $MM run -n "$2" pip freeze 2>/dev/null | sort > "$OUT/${name}_freeze_after.txt"
  if diff -q "$OUT/${name}_freeze_before.txt" "$OUT/${name}_freeze_after.txt" >/dev/null; then
    echo "[5] pip freeze: 원본과 동일 ($(wc -l < "$OUT/${name}_freeze_after.txt")줄)"
  else
    echo "[5] pip freeze: 다름"; diff "$OUT/${name}_freeze_before.txt" "$OUT/${name}_freeze_after.txt" | head -8; verdict=FAIL
  fi
  # 원본 **경로**가 박혀 있는지만 본다. "_orig" 만 찾으면 gitk 의 변수명 같은 것이 걸린다.
  local hard; hard=$(grep -rIlE "envs/$2_orig|repos/$3_orig" "$env/bin" "$env/conda-meta" 2>/dev/null | wc -l)
  echo "[6] 복원본에 원본 경로가 박힌 파일: ${hard}개"
  [ "$hard" -eq 0 ] || verdict=FAIL
  echo "[7] import · 버전 · 적재 경로 (복원본은 __pycache__ 가 없어 첫 import 가 느리다)"
  # shellcheck disable=SC2086
  ( cd "$repo" && $MM run -n "$2" python "$HERE/restore_probe.py" "$env" "$repo" $mods ) || verdict=FAIL
  if [ $PROBE_ONLY = 0 ]; then
    echo "[8] 기능 확인"
    case $name in
      wham)
        local clip=$VOL/data/02_sam2/zombie_walker/zombie_walker_masked.mp4 ref=$VOL/data/04_wham/zombie_walker_masked/wham_output.pkl
        if bash "$HERE/run_wham.sh" "$clip" --out "$OUT/wham_out" > "$OUT/wham_run.log" 2>&1; then
          $MM run -n wham python - "$OUT/wham_out/zombie_walker_masked/wham_output.pkl" "$ref" <<'PY' || verdict=FAIL
import joblib, numpy as np, sys
a = list(joblib.load(sys.argv[1]).values())[0]; b = list(joblib.load(sys.argv[2]).values())[0]
d = float(np.abs(a["pose"] - b["pose"]).max())
print(f"  S5 재실행(zombie_walker): pose {a['pose'].shape}, 기존 산출물과 최대 차 {d:.2e}  {'일치' if d < 1e-3 else '불일치'}")
sys.exit(0 if d < 1e-3 else 1)
PY
        else echo "  S5 실행 실패 — $OUT/wham_run.log"; tail -3 "$OUT/wham_run.log"; verdict=FAIL; fi ;;
      trellis)
        bash "$HERE/setup_trellis.sh" --check > "$OUT/trellis_check.log" 2>&1; local c=$?
        echo "  setup_trellis.sh --check rc=$c"; [ $c -eq 0 ] || verdict=FAIL ;;
      trellis2)
        bash "$HERE/setup_trellis2.sh" --check > "$OUT/trellis2_check.log" 2>&1; local c=$?
        echo "  setup_trellis2.sh --check rc=$c"; [ $c -eq 0 ] || verdict=FAIL
        local key=$VOL/data/02_sam2/char_shuffle/keyframes/key2_f00006.png ref=$VOL/data/03_trellis2/_probe_default_1008/params.json
        if timeout 900 $MM run -n trellis2 python "$HERE/run_trellis2.py" --image "$key" --out "$OUT/t2_out" --name restore_probe > "$OUT/t2_run.log" 2>&1; then
          # **내보내기 전 정점**으로 대조한다. 최종 정점은 리메싱·UV 전개가 실행마다 조금 달라
          # 같은 입력·seed 에서도 일치하지 않는다 (2026-10-09: 822,125 대 819,832).
          python3 - "$OUT/t2_out/params.json" "$ref" <<'PY' || verdict=FAIL
import json, sys
a = json.load(open(sys.argv[1])); b = json.load(open(sys.argv[2]))
same = a["vertices_pre_export"] == b["vertices_pre_export"] and a["pipeline_type"] == b["pipeline_type"]
print(f"  S3 재실행: {a['pipeline_type']} 내보내기 전 정점 {a['vertices_pre_export']:,} (기준 {b['vertices_pre_export']:,}) 총 {a['time_s']['total']}초  {'일치' if same else '불일치'}")
sys.exit(0 if same else 1)
PY
        else echo "  S3 실행 실패 — $OUT/t2_run.log"; tail -3 "$OUT/t2_run.log"; verdict=FAIL; fi ;;
    esac
  else
    echo "[8] 기능 확인 건너뜀 (--probe-only)"
  fi
  echo "[9] 원본 복귀"
  back; trap - EXIT
  $MM run -n "$2" pip freeze 2>/dev/null | sort > "$OUT/${name}_freeze_back.txt"
  local okb; okb=$(diff -q "$OUT/${name}_freeze_before.txt" "$OUT/${name}_freeze_back.txt" >/dev/null && echo 동일 || echo 다름)
  echo "    _orig 잔존: $(ls -d "${env}_orig" "${repo}_orig" 2>/dev/null | wc -l)개, 복귀 후 pip freeze $okb"
  [ "$okb" = 동일 ] || verdict=FAIL
  echo "==== $name 판정: $verdict  $(date +%T)"
  [ $verdict = PASS ]
}

run() {
  case $1 in
    wham)     restore_one wham     wham     WHAM      "torchvision numpy cv2 joblib smplx mmcv lib.models" ;;
    trellis)  restore_one trellis  trellis  TRELLIS   "torchvision numpy xformers kaolin spconv nvdiffrast trellis" ;;
    trellis2) restore_one trellis2 trellis2 TRELLIS.2 "torchvision numpy flash_attn trellis2" ;;
    *) echo "알 수 없는 대상: $1 (wham | trellis | trellis2 | all)"; return 2 ;;
  esac
}

echo "시작 $(date +%T)  로그 $OUT"
FAILED=0
if [ "$TARGET" = all ]; then
  for t in wham trellis trellis2; do run $t || FAILED=1; done
else
  run "$TARGET" || FAILED=1
fi
echo; echo "=== 복원 시험 종료 $(date +%T)  $([ $FAILED = 0 ] && echo '전부 PASS' || echo 'FAIL 있음')"
exit $FAILED
