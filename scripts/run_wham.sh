#!/usr/bin/env bash
set -e
VIDEO="${1:?입력 영상 경로를 지정하세요}"
VOL=/workspace
export MAMBA_ROOT_PREFIX=$VOL/micromamba
eval "$($VOL/micromamba/bin/micromamba shell hook -s bash)"
micromamba activate wham
cd $VOL/repos/WHAM
mkdir -p $VOL/data/05_wham
python demo.py --video "$VIDEO" --output_pth $VOL/data/05_wham \
    --visualize --save_pkl --estimate_local_only \
    2>&1 | tee $VOL/logs/wham_$(date +%Y%m%d_%H%M%S).log
echo "완료:"
find $VOL/data/05_wham -type f | tail -20
