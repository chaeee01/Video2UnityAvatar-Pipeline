#!/usr/bin/env bash
# WHAM 동작 복원 (S5): 마스킹 클립 → wham_output.pkl, overlay.mp4
#
#   bash scripts/run_wham.sh <영상경로> [--out <출력폴더>]
#
# 기본 출력은 규약 경로 /workspace/data/04_wham (docs/CONVENTIONS.md 1절).
# 산출물은 그 아래 <영상명>/ 에 떨어진다 (WHAM demo.py 동작).
set -e
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
python demo.py --video "$VIDEO" --output_pth "$OUT" \
    --visualize --save_pkl --estimate_local_only \
    2>&1 | tee $VOL/logs/wham_$(date +%Y%m%d_%H%M%S).log
echo "완료:"
find "$OUT" -type f | tail -20
