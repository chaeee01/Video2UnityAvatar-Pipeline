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
# --visualize 는 pytorch3d 를 요구하는데, conda-forge 의 py39+cu118 pytorch3d 빌드는
# torch 2.1.2 이상만 있어 torchvision 0.15.1(torch 2.0.0 고정)과 공존할 수 없다.
# 재투영 육안 검증은 scripts/overlay_vis.py 로 대행한다 (cv2 기반, pytorch3d 불필요).
python demo.py --video "$VIDEO" --output_pth "$OUT" \
    --save_pkl --estimate_local_only \
    2>&1 | tee $VOL/logs/wham_$(date +%Y%m%d_%H%M%S).log
echo "완료:"
find "$OUT" -type f | tail -20
