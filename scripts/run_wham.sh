#!/usr/bin/env bash
# WHAM 동작 복원 (S5): 마스킹 클립 → wham_output.pkl, overlay.mp4
#
#   bash scripts/run_wham.sh <영상경로> [--out <출력폴더>]
#
# 기본 출력은 규약 경로 /workspace/data/04_wham (docs/CONVENTIONS.md 1절).
# 산출물은 그 아래 <영상명>/ 에 떨어진다 (WHAM demo.py 동작).
# pipefail 없이는 `python ... | tee` 의 종료 코드가 tee(0)의 것이 되어
# demo.py 가 죽어도 스크립트가 계속 진행한다 (2026-09-04 리허설에서 실패를
# "완료" 로 오보한 사고).
set -eo pipefail
VIDEO="${1:?입력 영상 경로를 지정하세요}"
shift
VOL=/workspace
OUT=$VOL/data/04_wham
while [ $# -gt 0 ]; do
    case "$1" in
        --out) OUT="${2:?--out 뒤에 출력 폴더가 필요합니다}"; shift 2 ;;
        *) echo "알 수 없는 인자: $1"; exit 1 ;;
    esac
done
export MAMBA_ROOT_PREFIX=$VOL/micromamba
eval "$($VOL/micromamba/bin/micromamba shell hook -s bash)"
micromamba activate wham
cd $VOL/repos/WHAM
mkdir -p "$OUT"
# --visualize 는 pytorch3d 를 요구하는데, conda-forge 의 py39+cu118 pytorch3d 빌드는
# torch 2.1.2 이상만 있어 torchvision 0.15.1(torch 2.0.0 고정)과 공존할 수 없다.
# 재투영 육안 검증은 scripts/overlay_vis.py 로 대행한다 (cv2 기반, pytorch3d 불필요).
python demo.py --video "$VIDEO" --output_pth "$OUT" \
    --save_pkl --estimate_local_only \
    2>&1 | tee $VOL/logs/wham_$(date +%Y%m%d_%H%M%S).log
# 현재 샘플 폴더만 검사한다. $OUT 전체를 나열하면 이전 샘플 산출물까지 섞여
# 실패한 실행이 성공처럼 보인다.
NAME=$(basename "${VIDEO%.*}")
RESULT="$OUT/$NAME"
if [ -f "$RESULT/wham_output.pkl" ]; then
    # 파일이 있다고 성공이 아니다. WHAM 은 사람을 하나도 추적하지 못해도 빈 dict 를
    # 담은 pkl(66바이트)을 쓰고 종료 코드 0 으로 끝난다 — 2026-10-08 에 zombie_listener
    # (마스크가 얼굴뿐)가 그렇게 "완료" 로 보고됐다. Blender 가 스크립트 예외에도
    # 종료 코드 0 을 내는 것과 같은 계열이다: 종료 코드도 파일 존재도 믿지 않고
    # **산출물의 내용**을 본다.
    TRACKS=$(python -c "import joblib,sys; print(len(joblib.load(sys.argv[1])))" "$RESULT/wham_output.pkl")
    if [ "${TRACKS:-0}" -lt 1 ]; then
        echo "실패: WHAM 이 사람을 하나도 추적하지 못했습니다 (트랙 0개) — $RESULT/wham_output.pkl" >&2
        echo "      마스크가 몸 전체를 담고 있는지 확인하세요 (S2 부분 선택이면 얼굴·옷 조각만 남는다)." >&2
        exit 1
    fi
    echo "완료: $RESULT (트랙 ${TRACKS}개)"
    find "$RESULT" -type f -printf "  %10s  %p\n" | sort -k2
else
    echo "실패: $RESULT/wham_output.pkl 이 생성되지 않았습니다" >&2
    exit 1
fi
