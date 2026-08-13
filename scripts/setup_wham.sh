#!/usr/bin/env bash
set -e
VOL=/workspace
MAMBA_DIR=$VOL/micromamba
REPO=$VOL/repos/WHAM
mkdir -p $VOL/repos $VOL/scripts $VOL/logs

export PIP_CACHE_DIR=$VOL/.cache/pip
mkdir -p "$PIP_CACHE_DIR"

if [ ! -f "$MAMBA_DIR/bin/micromamba" ]; then
    echo "[1/4] micromamba 설치"
    mkdir -p $MAMBA_DIR/bin
    curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj -C $MAMBA_DIR bin/micromamba
else
    echo "[1/4] micromamba 재사용"
fi

export MAMBA_ROOT_PREFIX=$MAMBA_DIR
eval "$($MAMBA_DIR/bin/micromamba shell hook -s bash)"

if ! micromamba env list | grep -q "wham"; then
    echo "[2/4] python 3.9 환경 생성"
    micromamba create -y -n wham -c conda-forge python=3.9 pip
fi
micromamba activate wham

if ! python -c "import torch" 2>/dev/null; then
    echo "[3/4] torch 2.0.0+cu118 설치 (오래 걸립니다)"
    pip install torch==2.0.0 torchvision==0.15.1 --index-url https://download.pytorch.org/whl/cu118
fi

if [ ! -d "$REPO" ]; then
    echo "[4/4] WHAM 클론"
    git clone --recursive https://github.com/yohanshin/WHAM.git $REPO
fi
cd $REPO
pip install -r requirements.txt
pip install -v -e third-party/ViTPose
pip install pyrender trimesh || true

echo ""
echo "설치 완료. 다음 명령을 실행하세요:"
echo "  cd /workspace/repos/WHAM && bash fetch_demo_data.sh"
