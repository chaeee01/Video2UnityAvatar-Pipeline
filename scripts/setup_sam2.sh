#!/usr/bin/env bash
# SAM2 로컬 설치 — RunPod Network Volume 기준.
#
#   bash scripts/setup_sam2.sh              # 전체 설치 (멱등: 다시 돌리면 빠진 것만)
#   bash scripts/setup_sam2.sh --check      # 설치 상태만 점검 (검증 블록만 실행)
#   bash scripts/setup_sam2.sh --env sam2x  # 다른 이름으로 설치 (기존 환경 보존)
#
# 설계:
#   - 이 스크립트는 **역추적으로 복원한 것**이다. sam2 환경은 수동 설치라 원본 setup
#     스크립트가 없었다. 2026-09-29 에 Pod 의 기존 `sam2` 환경을 `micromamba env export`
#     + `pip freeze` 로 떠서 버전을 고정했다. 원자료는 EH-226 작업 기록에 보존돼 있다.
#   - setup_trellis2.sh 와 같은 방식. 볼륨(/workspace)의 micromamba 환경에 설치하고
#     기존 환경은 건드리지 않는다. --env 로 이름을 바꾸면 나란히 만들 수 있다.
#   - CUDA 툴체인(nvcc)은 넣지 않는다. SAM2 는 prebuilt 휠만 쓰고 컴파일이 없다
#     (기존 환경에도 nvcc 가 없음을 확인했다). trellis2 와 다른 점이다.
#
# 버전 핀 (전부 2026-09-29 기존 환경 실측값 — 추측 없음):
#   python 3.10.21 / torch 2.5.1+cu121 / torchvision 0.20.1+cu121
#   hydra-core 1.3.5 / iopath 0.1.10 / numpy 2.2.6 /
#   opencv-python-headless 5.0.0.93 / pillow 12.3.0 / tqdm 4.70.0
#   sam2 레포 커밋 2b90b9f (태그 없음 — 커밋으로 고정한다)
#
#   핀을 박는 이유는 환경 표류 때문이다. torch 계열은 조합이 어긋나면 로드 단계에서
#   죽거나 더 나쁘게는 조용히 다른 결과를 낸다. 올릴 때는 셋(torch/torchvision/cu 버전)을
#   함께 올리고 [8/8] 을 다시 통과시킨다.
#
# 기존 환경과 일부러 다르게 한 것:
#   * **ffmpeg 를 환경 안에 넣는다.** 원본 Pod 은 시스템 ffmpeg(`/usr/bin/ffmpeg`, 컨테이너
#     이미지 제공)를 쓰지만, 본 스크립트는 복원 완전성을 위해 환경에 내장한다. 볼륨만 tar 로
#     떠서 옮기면 시스템 ffmpeg 는 따라오지 않고, run_sam2.py 는 ffmpeg 가 없으면 에러로
#     멈추므로(의도된 fail-fast) 복원한 환경이 그 자리에서 깨진다.
#   * **sam2 를 editable 이 아니라 일반 설치한다** (`pip install <repo>`). 원본 환경은
#     `pip install -e` 였다. 우리는 sam2 소스를 수정하지 않으므로 editable 일 이유가 없고,
#     editable 은 `__editable___sam_2_1_0_finder.py` 에 레포 절대 경로를 박아 넣어 환경을
#     그 경로에 묶는다 — 2026-09-29 복원 시험에서 실제로 드러났다(복원본이 원본 레포를
#     참조). 일반 설치하면 sam2 가 site-packages 로 복사돼 환경이 자립한다. 경로 자립은
#     의도한 목적이고 editable 해제는 그 부산물이다. 레포는 체크포인트 때문에 여전히 필요하다.
#
# -u 는 쓰지 않는다: micromamba shell hook 이 미정의 변수를 참조한다.
set -eo pipefail

VOL=/workspace
MAMBA_DIR=$VOL/micromamba
REPO=$VOL/repos/sam2
ENV_NAME=sam2
PY_VER=3.10
SAM2_COMMIT=2b90b9f
LOG_DIR=$VOL/logs
mkdir -p $VOL/repos $LOG_DIR $VOL/.cache/pip $VOL/.cache/torch

export PIP_CACHE_DIR=$VOL/.cache/pip
export TORCH_HOME=$VOL/.cache/torch

CHECK_ONLY=0
CKPT_SET=all             # all = 4종 전부(1.5GB), large = 파이프라인 기본값만(0.9GB)
while [ $# -gt 0 ]; do
    case "$1" in
        --check) CHECK_ONLY=1; shift ;;
        --env)   ENV_NAME="${2:?--env 뒤에 환경 이름}"; shift 2 ;;
        --ckpt)  CKPT_SET="${2:?--ckpt 뒤에 all 또는 large}"; shift 2 ;;
        *) echo "알 수 없는 인자: $1"; exit 1 ;;
    esac
done
case "$CKPT_SET" in all|large) ;; *) echo "--ckpt 은 all 또는 large"; exit 1 ;; esac

log() { echo ""; echo "[$(date +%H:%M:%S)] $*"; }

# ---------------------------------------------------------------- 1. micromamba
if [ ! -f "$MAMBA_DIR/bin/micromamba" ]; then
    log "[1/8] micromamba 설치"
    mkdir -p $MAMBA_DIR/bin
    curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
        | tar -xvj -C $MAMBA_DIR bin/micromamba
else
    log "[1/8] micromamba 재사용"
fi

export MAMBA_ROOT_PREFIX=$MAMBA_DIR
eval "$($MAMBA_DIR/bin/micromamba shell hook -s bash)"

# ---------------------------------------------------------------- 2. 환경
if [ $CHECK_ONLY -eq 0 ]; then
    if ! micromamba env list | grep -qE "^\s+$ENV_NAME\s"; then
        log "[2/8] python $PY_VER 환경 '$ENV_NAME' 생성"
        micromamba create -y -n "$ENV_NAME" -c conda-forge "python=$PY_VER" pip
    else
        log "[2/8] 환경 '$ENV_NAME' 재사용"
    fi
fi
micromamba activate "$ENV_NAME"

if [ $CHECK_ONLY -eq 1 ]; then
    log "[--check] 설치 단계를 건너뛰고 검증만 실행한다"
else

# ---------------------------------------------------------------- 3. torch
if ! python -c "import torch" 2>/dev/null; then
    log "[3/8] torch 2.5.1 + torchvision 0.20.1 (cu121) 설치 (약 2.5GB)"
    pip install torch==2.5.1 torchvision==0.20.1 \
        --index-url https://download.pytorch.org/whl/cu121
else
    log "[3/8] torch 재사용: $(python -c 'import torch; print(torch.__version__)')"
fi

# ---------------------------------------------------------------- 4. 직접 의존
# SAM2 의 setup.py 가 알아서 끌어오지만, 버전을 박아 두면 표류하지 않는다.
# 여기 없는 것(nvidia-*, triton, sympy, networkx, omegaconf, antlr4, portalocker 등)은
# 전부 위 패키지들의 전이 의존이라 따로 적지 않는다.
log "[4/8] 직접 의존 설치"
pip install \
    hydra-core==1.3.5 \
    iopath==0.1.10 \
    numpy==2.2.6 \
    opencv-python-headless==5.0.0.93 \
    pillow==12.3.0 \
    tqdm==4.70.0

# ---------------------------------------------------------------- 5. ffmpeg
# 위 헤더 참조 — 컨테이너의 /usr/bin/ffmpeg 에 기대지 않는다.
if ! "$CONDA_PREFIX/bin/ffmpeg" -version >/dev/null 2>&1; then
    log "[5/8] ffmpeg 설치 (환경 내부, conda-forge)"
    micromamba install -y -n "$ENV_NAME" -c conda-forge ffmpeg
else
    log "[5/8] ffmpeg 재사용: $("$CONDA_PREFIX/bin/ffmpeg" -version 2>&1 | head -1)"
fi

# ---------------------------------------------------------------- 6. sam2 레포
if [ ! -d "$REPO/.git" ]; then
    log "[6/8] sam2 레포 클론"
    git clone https://github.com/facebookresearch/sam2.git "$REPO"
else
    log "[6/8] sam2 레포 재사용 ($(git -C "$REPO" rev-parse --short HEAD))"
fi
# 커밋 고정. upstream 이 움직여도 검증한 지점으로 되돌린다.
if [ "$(git -C "$REPO" rev-parse --short HEAD)" != "$SAM2_COMMIT" ]; then
    log "     커밋 고정: $SAM2_COMMIT 으로 체크아웃"
    git -C "$REPO" fetch --all --quiet
    git -C "$REPO" checkout --quiet "$SAM2_COMMIT"
fi
# editable 로 깔려 있으면 먼저 걷어낸다 (경로가 박힌 finder 가 남는다).
if ls "$CONDA_PREFIX"/lib/python*/site-packages/__editable__*sam_2* >/dev/null 2>&1; then
    log "     기존 editable 설치 제거"
    pip uninstall -y SAM-2
fi
pip install "$REPO"

# ---------------------------------------------------------------- 7. 체크포인트
log "[7/8] 체크포인트 ($CKPT_SET)"
mkdir -p "$REPO/checkpoints"
BASE=https://dl.fbaipublicfiles.com/segment_anything_2/092824
if [ "$CKPT_SET" = "all" ]; then
    CKPTS="sam2.1_hiera_tiny.pt sam2.1_hiera_small.pt sam2.1_hiera_base_plus.pt sam2.1_hiera_large.pt"
else
    CKPTS="sam2.1_hiera_large.pt"
fi
for c in $CKPTS; do
    if [ -s "$REPO/checkpoints/$c" ]; then
        echo "  재사용 $c"
    else
        echo "  받는 중 $c"
        curl -L --fail -o "$REPO/checkpoints/$c" "$BASE/$c"
    fi
done

fi   # CHECK_ONLY

# ---------------------------------------------------------------- 8. 검증
log "[8/8] 검증 — 버전 핀 · import · 모델 로드 · 마스크 생성"
SAM2_REPO="$REPO" python - <<'EOF'
import importlib, os, sys, tempfile, subprocess
import numpy as np

fail = []

def check(label, got, want=None):
    ok = (want is None) or (str(got) == str(want))
    print(f"  {'OK ' if ok else 'X  '} {label:34s} {got}" + (f"   (기대 {want})" if not ok else ""))
    if not ok:
        fail.append(label)

# --- 버전 핀 ---
print("버전 핀")
check("python", ".".join(map(str, sys.version_info[:2])), "3.10")
import torch, torchvision
check("torch", torch.__version__, "2.5.1+cu121")
check("torchvision", torchvision.__version__, "0.20.1+cu121")
# 배포명(pip)과 import 명이 다르고, cv2 는 __version__ 이 배포 버전과도 다르다
# (cv2.__version__ == "5.0.0" 인데 배포는 "5.0.0.93"). 핀은 배포 버전 기준이므로
# importlib.metadata 로 본다 — __version__ 으로 보면 멀쩡한 환경이 FAIL 로 잡힌다.
from importlib.metadata import version as dist_version, PackageNotFoundError
for mod, dist, want in [("hydra", "hydra-core", "1.3.5"),
                        ("iopath", "iopath", "0.1.10"),
                        ("numpy", "numpy", "2.2.6"),
                        ("cv2", "opencv-python-headless", "5.0.0.93"),
                        ("PIL", "pillow", "12.3.0"),
                        ("tqdm", "tqdm", "4.70.0")]:
    importlib.import_module(mod)          # import 가능한지도 함께 본다
    try:
        got = dist_version(dist)
    except PackageNotFoundError:
        got = "배포 정보 없음"
    check(f"{mod} ({dist})", got, want)

# --- 런타임 ---
print("\n런타임")
check("cuda available", torch.cuda.is_available(), "True")
if torch.cuda.is_available():
    p = torch.cuda.get_device_properties(0)
    check("gpu", f"{torch.cuda.get_device_name(0)} {p.total_memory/2**30:.1f}GB")

# ffmpeg 는 환경 안의 것이어야 한다 (컨테이너 /usr/bin 이면 tar 복원 때 사라진다).
import shutil
ff = shutil.which("ffmpeg") or ""
check("ffmpeg 위치", ff or "없음")
if not ff.startswith(os.environ.get("CONDA_PREFIX", "\0")):
    print("     ! 환경 밖 ffmpeg 다 — tar 로 옮기면 따라오지 않는다")
    fail.append("ffmpeg 위치")

# --- import ---
print("\nimport")
import sam2
sam2_dir = os.path.dirname(sam2.__file__)
check("sam2 경로", sam2_dir)
# 자립성: sam2 가 환경 안(site-packages)에 있어야 아카이브를 옮겨도 깨지지 않는다.
# editable 설치면 여기가 /workspace/repos/sam2/sam2 로 나오고, 그 경로가 없는 기계에서는
# import 부터 실패한다 (2026-09-29 복원 시험에서 확인).
prefix = os.environ.get("CONDA_PREFIX", "\0")
check("sam2 가 환경 안에 있는가", sam2_dir.startswith(prefix), "True")
from sam2.build_sam import build_sam2_video_predictor
print("   OK  build_sam2_video_predictor")
# _C 는 선택적 CUDA 확장이다. 환경에 nvcc 가 없어 빌드되지 않으며 **원본 sam2 환경도
# 동일하게 없다**(2026-09-29 대조). propagate 중 경고가 뜨지만 결과에는 영향이 없다 —
# 없다고 해서 쫓아가지 말 것.
try:
    from sam2 import _C            # noqa: F401
    print("   OK  sam2._C (선택적 CUDA 확장) 있음")
except ImportError:
    print("   --  sam2._C 없음 — 정상 (원본 환경과 동일, nvcc 미설치)")

# --- 모델 로드 + 마스크 생성 ---
print("\n모델 로드 + 마스크 1프레임")
repo = os.environ["SAM2_REPO"]
ckpt = os.path.join(repo, "checkpoints", "sam2.1_hiera_large.pt")
cfg = "configs/sam2.1/sam2.1_hiera_l.yaml"
check("체크포인트", os.path.basename(ckpt) if os.path.exists(ckpt) else "없음",
      "sam2.1_hiera_large.pt")

if os.path.exists(ckpt) and torch.cuda.is_available():
    dev = "cuda"
    predictor = build_sam2_video_predictor(cfg, ckpt, device=dev)
    print("   OK  모델 로드")
    # 합성 프레임 2장으로 실제 추적을 돌린다. 데이터가 없어도 검증이 성립한다.
    with tempfile.TemporaryDirectory() as d:
        from PIL import Image
        H = W = 256
        for i in range(2):
            a = np.full((H, W, 3), 30, dtype=np.uint8)
            a[80:180, 90 + i * 4:170 + i * 4] = 220        # 밝은 사각형이 움직인다
            Image.fromarray(a).save(os.path.join(d, f"{i:05d}.jpg"), quality=95)
        st = predictor.init_state(video_path=d)
        predictor.add_new_points_or_box(
            inference_state=st, frame_idx=0, obj_id=1,
            points=np.array([[128, 128]], dtype=np.float32),
            labels=np.array([1], dtype=np.int32))
        n, area = 0, 0
        for idx, obj_ids, logits in predictor.propagate_in_video(st):
            m = (logits[0] > 0.0).cpu().numpy().squeeze()
            n += 1
            area += int(m.sum())
        check("추적 프레임 수", n, 2)
        check("마스크 면적 > 0", area > 0, "True")
        print(f"      (합계 {area}px — 사각형을 잡았으면 수천 px 이 나온다)")
else:
    print("   건너뜀 — 체크포인트나 GPU 가 없다")
    fail.append("모델 로드")

print()
if fail:
    print(f"[FAIL] {len(fail)}건: {', '.join(fail)}")
    sys.exit(1)
print("[8/8] 전부 통과")
EOF

echo ""
echo "설치 완료. 스모크 테스트:"
echo "  micromamba activate $ENV_NAME"
echo "  python /workspace/repos/Video2UnityAvatar-Pipeline/scripts/run_sam2.py \\"
echo "      --video /workspace/data/00_raw/<샘플>.mp4 \\"
echo "      --out   /workspace/data/02_sam2/<샘플> --point <x,y>"
