#!/usr/bin/env bash
# TRELLIS(원조, microsoft/TRELLIS-image-large) 로컬 설치 — RunPod Network Volume 기준.
#
#   bash scripts/setup_trellis.sh            # 전체 설치 (멱등: 다시 돌리면 빠진 것만)
#   bash scripts/setup_trellis.sh --check    # 설치 상태만 점검
#
# 설계:
#   - setup_wham.sh 와 같은 방식. 도커 이미지가 아니라 볼륨(/workspace)의 micromamba 환경
#     `trellis` 에 설치한다. Pod 을 지워도 환경·모델·컴파일 결과가 남는다.
#   - CUDA 툴체인(nvcc, 헤더)과 C++ 컴파일러까지 환경 안에 넣는다(conda-forge). Pod 이미지의
#     nvcc/gcc 버전에 기대지 않으므로 어떤 템플릿으로 배포해도 같은 결과가 나온다.
#     TRELLIS 는 CUDA 확장 3개(nvdiffrast, diffoctreerast, diff-gaussian-rasterization)를
#     소스 빌드해야 하고, nvdiffrast 는 실행 시점에도 JIT 컴파일을 하므로 nvcc 가 런타임에
#     필요하다 — 이것이 wham/sam2 환경과 다른 점이다.
#   - 버전 조합은 upstream setup.sh 의 torch 2.4.0 경로를 cu121 로 고정한 것:
#       python 3.10 / torch 2.4.0+cu121 / xformers 0.0.27.post2 / kaolin 0.17.0 /
#       spconv-cu120 / CUDA 12.1.1 (conda-forge) / numpy<2
#   - attention 백엔드는 xformers. flash-attn 은 소스 빌드가 오래 걸리고 prebuilt 휠 매칭이
#     까다로워 제외했다(결과는 동일, 속도 차이만 약간). run_trellis.py 가 ATTN_BACKEND 를 맞춘다.
#   - 캐시(HF 모델, torch.hub DINOv2, torch_extensions JIT, rembg)는 전부 /workspace/.cache 로.
#     기본 위치(~/.cache)는 Pod 밖이라 Terminate 하면 사라져 매번 다시 받게 된다.
#
# 소요: 첫 설치 30~40분 (다운로드 ~6GB + 확장 빌드 10~15분). 4090 기준 ~$0.5.
# -u 는 쓰지 않는다: conda 컴파일러 활성화 스크립트가 미정의 변수를 참조해 -u 에서 죽는다.
set -eo pipefail

VOL=/workspace
MAMBA_DIR=$VOL/micromamba
REPO=$VOL/repos/TRELLIS
EXT_DIR=$VOL/build/trellis_ext          # 확장 소스. /tmp 는 Pod 과 함께 사라지므로 볼륨에
ENV_NAME=trellis
PY_VER=3.10
CUDA_VER=12.1
LOG_DIR=$VOL/logs
mkdir -p $VOL/repos $VOL/build $LOG_DIR $VOL/.cache/pip $VOL/.cache/huggingface \
         $VOL/.cache/torch $VOL/.cache/torch_extensions $VOL/.cache/u2net \
         $VOL/data/03_trellis

export PIP_CACHE_DIR=$VOL/.cache/pip
export HF_HOME=$VOL/.cache/huggingface
export TORCH_HOME=$VOL/.cache/torch
export TORCH_EXTENSIONS_DIR=$VOL/.cache/torch_extensions
export U2NET_HOME=$VOL/.cache/u2net
# 빌드 대상 아키텍처. 4090=8.9, A6000/3090=8.6, A100=8.0. 전부 빌드하면 시간이 3배라 셋만.
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.0;8.6;8.9}"
export MAX_JOBS="${MAX_JOBS:-$(nproc)}"

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

log() { echo -e "\n[$(date +%H:%M:%S)] $*"; }

# ---------------------------------------------------------------- 1. micromamba
if [ ! -f "$MAMBA_DIR/bin/micromamba" ]; then
    log "[1/8] micromamba 설치"
    mkdir -p $MAMBA_DIR/bin
    curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C $MAMBA_DIR bin/micromamba
else
    log "[1/8] micromamba 재사용"
fi
export MAMBA_ROOT_PREFIX=$MAMBA_DIR
eval "$($MAMBA_DIR/bin/micromamba shell hook -s bash)"

# ---------------------------------------------------------------- 2. env + CUDA 툴체인
if ! micromamba env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
    [ $CHECK_ONLY = 1 ] && { echo "환경 '$ENV_NAME' 없음"; exit 1; }
    log "[2/8] python $PY_VER + CUDA $CUDA_VER 툴체인 환경 생성 (conda-forge, ~2GB)"
    # cuda-compiler: nvcc 등 / cuda-libraries-dev: cudart·nvrtc·cccl·driver-dev 등 빌드용 헤더·라이브러리
    # gxx_linux-64=11: nvcc 12.1 이 지원하는 호스트 컴파일러 (Ubuntu 24.04 템플릿의 gcc 13 은 거부됨)
    micromamba create -y -n $ENV_NAME -c conda-forge \
        python=$PY_VER pip \
        cuda-version=$CUDA_VER cuda-compiler=$CUDA_VER cuda-libraries-dev=$CUDA_VER \
        gxx_linux-64=11 ninja git
else
    log "[2/8] 환경 '$ENV_NAME' 재사용"
fi
micromamba activate $ENV_NAME

# 확장 빌드가 환경 안의 CUDA 를 보도록. conda-forge 는 헤더·라이브러리를 targets/ 아래에 두고
# include/ 로 링크를 걸어 두는데, 링크가 없는 버전도 있어 경로를 직접 얹는다.
export CUDA_HOME=$CONDA_PREFIX
export CPATH=$CONDA_PREFIX/targets/x86_64-linux/include${CPATH:+:$CPATH}
export LIBRARY_PATH=$CONDA_PREFIX/targets/x86_64-linux/lib:$CONDA_PREFIX/targets/x86_64-linux/lib/stubs${LIBRARY_PATH:+:$LIBRARY_PATH}
export PATH=$CONDA_PREFIX/bin:$PATH

if ! command -v nvcc >/dev/null || ! nvcc --version | grep -q "release $CUDA_VER"; then
    echo "nvcc $CUDA_VER 를 찾지 못함 (PATH=$PATH)"; nvcc --version || true; exit 1
fi
log "nvcc: $(nvcc --version | grep release)  /  CXX: ${CXX:-c++}"

# ---------------------------------------------------------------- 3. torch
if ! python -c "import torch, sys; sys.exit(0 if torch.__version__.startswith('2.4.0') else 1)" 2>/dev/null; then
    [ $CHECK_ONLY = 1 ] && { echo "torch 2.4.0 없음"; exit 1; }
    log "[3/8] torch 2.4.0+cu121 설치 (~2.5GB)"
    pip install "numpy<2" torch==2.4.0 torchvision==0.19.0 --index-url https://download.pytorch.org/whl/cu121
else
    log "[3/8] torch 재사용: $(python -c 'import torch; print(torch.__version__)')"
fi

# ---------------------------------------------------------------- 4. 기본 의존성 (upstream --basic)
if [ $CHECK_ONLY = 0 ]; then
    log "[4/8] 기본 패키지"
    pip install "numpy<2" pillow imageio imageio-ffmpeg tqdm easydict opencv-python-headless scipy ninja \
        rembg onnxruntime trimesh open3d xatlas pyvista pymeshfix igraph transformers
    # utils3d 는 upstream 이 커밋을 고정해 둔 것. 최신을 받으면 API 가 달라 postprocessing 이 깨진다.
    python -c "import utils3d" 2>/dev/null || \
        pip install git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8
fi

# ---------------------------------------------------------------- 5. prebuilt 휠 (xformers, kaolin, spconv)
if [ $CHECK_ONLY = 0 ]; then
    log "[5/8] xformers / kaolin / spconv"
    python -c "import xformers" 2>/dev/null || \
        pip install xformers==0.0.27.post2 --index-url https://download.pytorch.org/whl/cu121
    python -c "import kaolin" 2>/dev/null || \
        pip install kaolin==0.17.0 -f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.4.0_cu121.html
    python -c "import spconv" 2>/dev/null || pip install spconv-cu120
    # 위 휠들이 numpy 2 를 끌어올 수 있어 한 번 더 고정
    pip install "numpy<2"
fi

# ---------------------------------------------------------------- 6. CUDA 확장 소스 빌드
build_ext() {  # <import명> <git url> <clone 옵션> <pip 대상 서브경로>
    local mod=$1 url=$2 opt=$3 sub=$4
    local dir=$EXT_DIR/$(basename $url .git)
    if python -c "import $mod" 2>/dev/null; then
        echo "  - $mod: 있음"; return
    fi
    [ $CHECK_ONLY = 1 ] && { echo "  - $mod: 없음"; return; }
    [ -d "$dir" ] || git clone $opt $url $dir
    echo "  - $mod: 빌드 ($dir/$sub)"
    pip install --no-build-isolation -v "$dir/$sub" 2>&1 | tee $LOG_DIR/build_${mod}.log | grep -E "error|Error|Successfully|warning: unsupported" || true
    python -c "import $mod" || { echo "  ! $mod 빌드 실패 — $LOG_DIR/build_${mod}.log 확인"; exit 1; }
}
log "[6/8] CUDA 확장 (nvdiffrast / diffoctreerast / diff-gaussian-rasterization)"
mkdir -p $EXT_DIR
# torch 확장 빌드는 환경의 torch 를 봐야 하므로 --no-build-isolation. 빌드 백엔드 의존성은 미리.
[ $CHECK_ONLY = 1 ] || pip install setuptools wheel ninja >/dev/null
build_ext nvdiffrast                   https://github.com/NVlabs/nvdiffrast.git              ""                    "."
build_ext diffoctreerast               https://github.com/JeffreyXiang/diffoctreerast.git    "--recurse-submodules" "."
build_ext diff_gaussian_rasterization  https://github.com/autonomousvision/mip-splatting.git "--recursive"          "submodules/diff-gaussian-rasterization"

# ---------------------------------------------------------------- 7. TRELLIS 레포
if [ ! -d "$REPO" ]; then
    [ $CHECK_ONLY = 1 ] && { echo "TRELLIS 레포 없음"; exit 1; }
    log "[7/8] TRELLIS 클론"
    git clone --recursive https://github.com/microsoft/TRELLIS.git $REPO
else
    log "[7/8] TRELLIS 레포 재사용 ($(git -C $REPO rev-parse --short HEAD))"
fi

# ---------------------------------------------------------------- 8. 검증
log "[8/8] import 검증"
cd $REPO
ATTN_BACKEND=xformers SPCONV_ALGO=native python - <<'EOF'
import importlib, torch
print(f"torch {torch.__version__}  cuda={torch.cuda.is_available()}  "
      f"gpu={torch.cuda.get_device_name(0) if torch.cuda.is_available() else '-'}")
import numpy; print("numpy", numpy.__version__)
for m in ["xformers", "kaolin", "spconv", "nvdiffrast", "diffoctreerast",
          "diff_gaussian_rasterization", "utils3d", "rembg", "open3d"]:
    mod = importlib.import_module(m)
    print(f"  {m:28s} {getattr(mod, '__version__', 'ok')}")
from trellis.pipelines import TrellisImageTo3DPipeline
from trellis.utils import postprocessing_utils
print("trellis import ok")
# nvdiffrast 는 첫 사용 시 CUDA 플러그인을 JIT 빌드한다. 여기서 미리 빌드해 컴파일 오류를
# 설치 단계에서 잡고, 결과를 TORCH_EXTENSIONS_DIR(볼륨)에 남긴다. 1~2분.
import nvdiffrast.torch as dr
dr.RasterizeCudaContext()
print("nvdiffrast CUDA plugin ok")
EOF

echo ""
echo "설치 완료. 스모크 테스트:"
echo "  micromamba activate trellis"
echo "  python /workspace/repos/Video2UnityAvatar-Pipeline/scripts/run_trellis.py \\"
echo "      --image /workspace/data/02_sam2/zombie_sample1/keyframes/key3_f00007.png \\"
echo "      --out   /workspace/data/03_trellis/zombie_sample1"
echo "첫 실행은 모델(~3GB)과 DINOv2 를 받고 nvdiffrast 를 JIT 컴파일하므로 5분 안팎 더 걸린다."
