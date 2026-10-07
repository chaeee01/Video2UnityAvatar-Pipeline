"""
SAM2 좀비 분리: 영상 한 편에서 마스크·마스킹 클립·키프레임 후보를 뽑는다.

notebooks/sam2/SAM2_try6_260711.ipynb 를 Pod 실행용으로 정제한 것.
첫 프레임의 좀비 위치를 점 하나로 지정하면 SAM2가 전 프레임을 추적한다.

  python run_sam2.py --video /workspace/data/00_raw/zombie_sample1.mp4 \
      --out /workspace/data/02_sam2/zombie_sample1 \
      --point 640,360

출력 (--out 아래):
  frames/            SAM2 입력용 원본 프레임 (jpg, 중간 산출물)
  masks/             프레임별 마스크 PNG (흑백 8bit)
  keyframes/         알파 키프레임 후보 RGBA PNG (TRELLIS 입력용)
  <영상명>_masked.mp4  배경을 검게 지운 클립 (WHAM 입력용)
  keyframes/candidates.json  후보 선정 근거 (프레임 번호·점수)

노트북과 달라진 점:
  - Colab/드라이브 경로 하드코딩 제거 → 전부 인자, 기본값은 /workspace 기준
  - 좌표 [640, 360] 하드코딩 제거 → --point, 미지정 시 실제 해상도의 중앙
  - fps 30 하드코딩 제거 → 원본 영상의 fps 를 읽어 사용
  - 전 프레임 RGBA PNG 저장은 기본 끔 (--save-rgba). 디스크 대부분을 먹는데
    후속 단계가 쓰는 건 마스크·클립·키프레임뿐이라서.
  - 클립은 PNG 시퀀스를 다시 읽지 않고 추적 루프에서 ffmpeg 로 바로 기록
    (1-pass, h264/yuv420p). 노트북의 mp4v 출력은 브라우저에서 재생 불가
  - 시각화 셀([추가1~3], 코랩 재생용 셀)은 제외
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np
from tqdm import tqdm


def parse_args():
    ap = argparse.ArgumentParser()
    # 샘플명을 기본값에 박지 않는다 (docs/CONVENTIONS.md 2절). 규약 경로는
    # /workspace/data/00_raw/<샘플>.mp4 -> /workspace/data/02_sam2/<샘플>/ 이다.
    ap.add_argument("--video", required=True,
                    help="입력 영상 (예: /workspace/data/00_raw/zombie_sample1.mp4)")
    ap.add_argument("--out", required=True,
                    help="출력 폴더 (예: /workspace/data/02_sam2/zombie_sample1)")
    ap.add_argument("--point", default=None,
                    help="첫 프레임의 좀비 좌표 'x,y'. 생략 시 프레임 중앙")
    ap.add_argument("--sam2-root", default="/workspace/repos/sam2",
                    help="SAM2 소스 루트 (pip install -e . 한 경로)")
    ap.add_argument("--checkpoint", default=None,
                    help="가중치. 기본값: <sam2-root>/checkpoints/sam2.1_hiera_large.pt")
    ap.add_argument("--model-cfg", default="configs/sam2.1/sam2.1_hiera_l.yaml")
    ap.add_argument("--obj-id", type=int, default=1)
    ap.add_argument("--topk", type=int, default=5,
                    help="저장할 키프레임 후보 개수")
    ap.add_argument("--keyframe-min-gap", type=int, default=20,
                    help="후보 사이 최소 프레임 간격 (기본 20). 0 이면 제약 없음 — "
                         "옛 동작이다. 근거는 pick_keyframes() 독스트링")
    ap.add_argument("--leg-term", choices=["on", "off"], default="on",
                    help="다리 벌어짐 감점항 (기본 on). off 는 2026-10-07 이전 동작 "
                         "재현용 — 근거는 leg_gap_ratio() 독스트링")
    ap.add_argument("--save-rgba", action="store_true",
                    help="전 프레임 RGBA PNG 도 저장 (노트북 동작)")
    ap.add_argument("--keep-frames", action="store_true",
                    help="중간 산출물 frames/ 를 지우지 않고 남김")
    return ap.parse_args()


def extract_frames(video_path, frames_dir):
    """영상을 SAM2 가 읽는 jpg 시퀀스로 쪼갠다. fps 도 함께 돌려준다."""
    os.makedirs(frames_dir, exist_ok=True)
    cam = cv2.VideoCapture(video_path)
    if not cam.isOpened():
        raise RuntimeError(f"영상을 열지 못함: {video_path}")
    fps = cam.get(cv2.CAP_PROP_FPS) or 30.0        # 노트북은 30 고정이었음
    n = 0
    h = w = None
    while True:
        ok, frame = cam.read()
        if not ok:
            break
        if h is None:                              # 첫 프레임에서 해상도 확보.
            h, w = frame.shape[:2]                 # 마지막 read 실패 시 frame 은 None
        cv2.imwrite(os.path.join(frames_dir, f"{n:05d}.jpg"), frame)
        n += 1
    cam.release()
    if n == 0:
        raise RuntimeError(f"프레임을 하나도 읽지 못함: {video_path}")
    print(f"[1/4] 프레임 {n}장 추출 ({w}x{h}, {fps:.2f}fps) → {frames_dir}")
    return n, fps, (w, h)


def load_predictor(args):
    """SAM2 예측기 탑재. 노트북의 sys.path 하드코딩을 --sam2-root 로 대체."""
    root = os.path.expanduser(args.sam2_root)
    for p in (root, os.path.join(root, "sam2")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import torch
    from sam2.build_sam import build_sam2_video_predictor

    ckpt = args.checkpoint or os.path.join(root, "checkpoints", "sam2.1_hiera_large.pt")
    if not os.path.exists(ckpt):
        raise RuntimeError(f"가중치가 없음: {ckpt}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[2/4] 예측기 탑재 (device={device}, cfg={args.model_cfg})")
    return build_sam2_video_predictor(args.model_cfg, ckpt, device=device), torch, device


def keyframe_score(mask):
    """키프레임 후보 점수.

    TRELLIS 입력은 팔을 벌린 자세가 유리하므로(G1a 기준) 마스크 폭/높이 비를
    주 지표로 삼고, 피사체가 너무 작거나 잘린 프레임은 면적으로 걸러낸다.

    ── 자세 항 미구현 (2026-09-14 판단) ─────────────────────────────────────
    이 점수는 폭을 보상하는데, 폭은 "옆으로 벌린 팔" 과 "카메라 쪽으로 뻗은 팔" 을
    구분하지 못한다. 후자는 단축·자기가림으로 단일 뷰 재구성에 불리할 것으로
    보이므로 자세 항을 넣자는 제안이 있었다. 지금은 넣지 않는다.

    이유는 검증 대상이 없기 때문이다. walker 에서 top1(f80)과 채택안(f222)의
    성분을 실측하면 이렇다:

        frame  bw/bh   fill   score  solidity
        f80    0.504  0.425  0.2144  0.514   ← 제약 없을 때의 1등
        f164   0.607  0.348  0.2112  0.468   ← 팔을 옆으로 가장 많이 벌림
        f222   0.373  0.517  0.1929  0.644   ← 실제 채택, 결과물 양호

    solidity(면적/볼록껍질)가 셋을 가장 잘 가르지만, 어느 방향이 좋은지는 모른다.
    팔을 몸에 붙이면 solidity 가 높아지는데 그것도 팔-몸통 분리를 어렵게 해
    나쁠 수 있다. 즉 곡선의 모양을 모르는 채 단조 함수를 넣는 셈이다.
    f222 결과가 좋았다는 것은 알지만 f80 으로 생성해 본 적이 없어 비교가 없다.

    필요한 실험: walker 를 f80 · f164 · f222 세 키프레임으로 각각 생성해 3자
    비교한다(약 12분). 그 결과가 나오면 자세 항의 방향과 세기를 근거 있게 정할 수
    있다. 그 전에 넣으면 시험할 수 없는 게이트가 되고, 이는 "게이트 자체의 오탐
    시험을 설계에 포함한다" 는 원칙에 어긋난다.

    ── 다리 항 구현 / 얼굴 항 미구현 (2026-10-07) ────────────────────────
    char_shuffle 에서 이 점수가 고른 f60 이 **최악에 가까운 선택**이었다(2026-10-01
    측정) — f60 은 다리가 붙었고 고개를 숙여 얼굴이 머리카락에 가렸다. 같은 영상
    f6 은 T포즈·다리 벌어짐·얼굴 정면인데 점수는 2위(0.2227 vs 0.2321)였다. 팔을
    완전히 벌리면 bbox 가 커져 채움률이 떨어지는 탓에 **좋은 프레임이 오히려
    감점된다.** f60 으로 뽑은 에셋은 10/1 에 불합격, f6 은 10/6 에 합격했다.

    **다리 항은 구현했다** — `leg_gap_ratio()` 와 `apply_leg_term()` 에 있다.
    이 함수(`keyframe_score`)는 프레임당 순수 함수로 남겨 두고, 감점은 전 프레임을
    보는 쪽에서 건다. 클립 단위 가드가 필요하기 때문이다.

    **얼굴 항은 WHAM 경로로 재설계 대기다 — 신호는 실증됐고, 막는 것은 순서다.**
    마스크 실루엣만으로는 숙인 머리와 든 머리를 가를 수 없고, RGB 에 얼굴 검출을
    걸려면 새 모델이 든다(cv2 5.0.0 은 haarcascade 를 더 이상 동봉하지 않는다 —
    `cv2.data` 가 `__init__.py` 뿐). 그런데 **WHAM pose 에는 이미 그 신호가 있다.**

    2026-10-07 프로브 — char_shuffle 의 기존 WHAM 산출물에서 머리 사슬
    (0→3→6→9→12→15)을 합성해 시선 벡터를 뽑고 수직 성분을 각으로 환산했다
    (WHAM 세계는 Y-down 이다: 머리-골반 벡터가 -Y).

        시선 하향각   f6 3.9°   f60 56.6°   차 52.7°   (192프레임 분포 2.2~64.0°)

    **분리력이 확실하다.** 목+머리의 몸통 상대 회전만 보면 7.9° vs 20.4° 로 2.6배에
    그치는데, 상체가 함께 기울기 때문이다. 전역 시선의 수직 성분이 더 나은 지표다.

    **그리고 다리 항만으로는 부족하다는 것이 같은 프로브에서 드러났다.** 다리 항
    적용 후 top5 `[6, 47, 67, 87, 26]` 의 하향각은 `[3.9, 51.0, 57.9, 12.0, 8.4]` 로,
    1등은 정면이지만 **2·3등이 고개를 숙인 프레임**이다. 사람이 후보에서 고르는
    현 운용에서는 1등이 좋으면 되지만, 자동 선정으로 가려면 얼굴 항이 필요하다.

    넣지 못하는 이유는 **순서 하나뿐이다.** 키프레임 선정이 S2 안에서 일어나는데
    WHAM(S5)은 S3 뒤에 있다.

    **채택 방향 (2026-10-07 결정, 구현 보류)** —

        S2 → S5 → [G3 구현 시 여기서 동작 확정 →] 재선정 → S3

    S2 는 지금처럼 다리 항만으로 후보를 낸다(산출물이 그 자체로 완결이라 수동
    실행·`--keyframe` 지정 경로가 WHAM 없이 돈다). S5 뒤의 **재선정 단계**가
    마스크와 WHAM 시선각으로 순위를 다시 매겨 S3 에 넘긴다. 근거 셋:
      ① 최종 에셋은 외형·동작 두 경로가 모두 필요하므로 "WHAM 실패 시 외형 생존"
         의 가치는 제한적이다 — 경로 독립보다 **나쁜 입력 차단**이 우선이다.
      ② 동작을 먼저 확정하고 외형을 만들면 장래 G3 재시도가 S3(430.7초)를
         무효화하지 않는다.
      ③ 얼굴 판정은 S3 **이전**에 WHAM 시선각으로 내린다.
    기각 — "S3 선행 + 얼굴 불합격 시 S3 재시도" 안은 불합격 때 430초를 다시 쓰고
    판정이 하류로 밀린다. "G1a 를 통째로 S5 뒤로 옮기는" 안은 순서는 같으나 S2
    산출물의 완결성과 수동 경로를 잃는다.
    **공통 선행 작업: G1a(키프레임 선정)를 run_sam2 에서 분리한다.** 지금은 선정을
    다시 하려면 SAM2 전체를 다시 돌려야 한다.

    **가드로 다리 항이 꺼진 클립의 처리도 재선정 단계의 몫이다.** 조용히 구점수로
    진행하지 않는다. 판정은 동작 조건부다 —
      - WHAM 동작에 **다리 움직임이 있으면** 두 다리 분리가 필수다. 벌린 프레임이
        없는 클립은 경고 + 종료 코드 2 로 사람에게 넘긴다("영상 재생성 권고 /
        강행 선택").
      - **다리 움직임이 없으면** 다리 붙은 메쉬를 허용하고 진행한다.
    그래서 S2 는 가드 상태만 기록한다(candidates.json 의 `leg_term`·`leg_signal`).
    "다리 움직임 유무" 의 지표(관절 각 변화량 등)는 재선정 단계 설계 때 정한다.
    실증 표본이 f60 한 건이므로 FAIL 이 아니라 경고+인계로 시작하고, 표본이 쌓이면
    격상을 검토한다.

    **그 사이 얼굴 결함을 받치는 그물이 두 겹 있다.** ① E2E 입력 조건의 **얼굴 정면**
    조항(2026-10-01 추가, docs/RUNBOOK.md 키프레임 조건) — 사람이 영상을 고를 때
    거른다. ② **외형 체크포인트** — S3 산출물을 사람이 보고 기각하며, 기각 처방은
    seed 변경 재생성이다(docs/CONVENTIONS.md 8절). 즉 얼굴 항이 없어도 숙인 머리가
    그대로 FBX 까지 가는 경로는 막혀 있고, 자동화 수준만 낮은 상태다.

    재설계 방향은 **WHAM 의 머리/목 회전각**이다 — 새 의존성이 없고 이미 파이프라인
    안에 있다. 다만 S5 가 S3 보다 뒤에 있어 순서 조정이 필요하다. 프로브 결과는
    PROJECT_STATUS 2026-10-07 항목에 있다.

    한편 2026-09-10 에 관측된 문제("후보 5장이 사실상 같은 장면")는 점수 방향이
    아니라 뭉침이 원인이었고, pick_keyframes() 의 간격 제약으로 해소된다 —
    제약을 걸면 walker 후보가 [80, 164, 117, 139, 222] 로 벌어져 f222 가
    후보 안에 들어온다.
    """
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return 0.0, None
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bw, bh = x1 - x0 + 1, y1 - y0 + 1
    if bh == 0:
        return 0.0, None
    fill = len(xs) / float(bw * bh)      # 마스크가 bbox 를 채운 정도
    return (bw / bh) * fill, (int(x0), int(y0), int(bw), int(bh))


# 다리 항 상수. 전부 char_shuffle(1920x1080, 192프레임) 마스크 192장 실측에서
# 나왔고, 대조는 walker · stalker · dog · listener 4종이다 (2026-10-07).
#
#   LEG_BAND        정강이 밴드. bbox 높이의 아래에서 12~35% 구간.
#                   바닥(0~12%)을 쓰지 않은 이유 — 걷는 동작에서 한 발이 들리면
#                   바닥 밴드에 다리가 하나만 들어와 간격이 0 으로 나온다.
#                   char_shuffle f96 이 그 사례다(하단 0px / 정강이 84px).
#   LEG_BAD 0.02    "붙었다" 로 보는 상한. f60(불합격) 실측 0.0125.
#   LEG_OK  0.06    "벌어졌다" 로 보는 하한. f6(합격) 실측 0.1162, f48 0.0838,
#                   f144 0.0798. 192프레임 분포는 0.0 ~ 0.136, 중앙값 0.0765.
#                   stalker 최대 0.0572 가 이 아래라 가드에 걸려 항이 꺼진다.
#   LEG_FLOOR 0.5   감점 바닥. 최대 2배까지만 깎는다. 바닥이 없으면 기존 점수가
#                   무의미해진다 — 가드 없는 단순 곱셈 시험에서 stalker top5 가
#                   0/5 겹침, listener 는 전 프레임 0 이 돼 순위가 무작위였다.
#   LEG_SIGNAL_P 90 가드 분위수. 아래 apply_leg_term() 참조.
#
# 새 영상에서 재보정할 때는 위 실측값이 기준이다. 임계를 움직이면
# tests/test_keyframe_leg.py 의 5샘플 회귀가 먼저 깨지게 해 두었다.
LEG_BAND = (0.12, 0.35)
LEG_BAD, LEG_OK, LEG_FLOOR = 0.02, 0.06, 0.5
LEG_SIGNAL_P = 90


def leg_gap_ratio(mask, band=LEG_BAND):
    """다리가 얼마나 벌어졌는지 — 마스크만으로 잰다. 추가 모델이 필요 없다.

    정강이 밴드의 행마다 **전경 양끝 사이의 최대 배경 런**을 재고, 그 중앙값을
    bbox 높이로 나눈다.

    bbox **폭이 아니라 높이**로 나누는 것이 중요하다. 팔을 벌리면 폭이 커지므로
    폭으로 나누면 T포즈가 손해를 본다 — char_shuffle f6 은 폭 932px, f60 은
    402px 로 2.3배 차이가 난다. 높이는 선 자세에서 안정적이다(880~970px).
    """
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return 0.0
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    bh = y1 - y0 + 1
    if bh <= 0:
        return 0.0
    lo, hi = band
    top = int(y0 + bh * (1 - hi))
    bot = int(y0 + bh * (1 - lo))
    rows = mask[top:bot, x0:x1 + 1]
    if rows.shape[0] == 0:
        return 0.0
    gaps = []
    for row in rows:
        on = np.nonzero(row)[0]
        if len(on) < 2:
            gaps.append(0)
            continue
        seg = row[on[0]:on[-1] + 1]
        best = run = 0
        for v in seg:
            run = 0 if v else run + 1
            if run > best:
                best = run
        gaps.append(best)
    return float(np.median(gaps)) / float(bh)


def apply_leg_term(scores, enabled=True):
    """다리가 붙은 프레임을 깎아 `score_adj` 에 넣는다.

    돌려주는 값은 `(상태, 신호)` 다. 상태는 `on` / `off_no_signal`(가드) /
    `off_user`(--leg-term off) 셋이고, 신호는 가드가 본 p90 간격비다(자료가
    없으면 None). **가드로 꺼진 것과 사용자가 끈 것을 구분해 남긴다** — 가드로
    꺼진 클립은 하류(재선정 단계)에서 따로 판정해야 하기 때문이다.

    **감점 전용·포화형이다.** 계수는

        m = LEG_FLOOR + (1 - LEG_FLOOR) * clamp((g - LEG_BAD) / (LEG_OK - LEG_BAD), 0, 1)

    로, LEG_OK 위로는 전부 1.0 이다. "더 벌릴수록 좋다" 는 모르는 주장이라 하지
    않는다. 실측으로 아는 것은 **"붙으면 나쁘다"** 하나뿐이고(f60 불합격 / f6 합격),
    계수는 딱 그만큼만 말한다. 2026-09-14 메모의 "곡선 모양을 모르는 채 단조 함수를
    넣는" 문제를 포화로 피한 것이다.

    **클립 단위 가드** — 전 프레임 간격비의 p90 이 LEG_OK 에 못 미치면 항을 끈다.
    이 클립에 애초에 다리 벌린 프레임이 **없다**는 뜻이므로, 없는 선택지를 두고
    순위를 흔들 이유가 없다. 가드는 실측으로 필요성이 드러났다 — 없이 돌리면
    기존 점수가 거의 동점인 샘플(stalker 상위 5개가 0.1988~0.1992)에서 작은 곱셈
    변동이 순위를 통째로 뒤집는다.

    2026-10-07 5샘플 대조 (topk 5, 간격 20):

        샘플          항    기존 top5                 신규 top5
        char_shuffle  작동  [60, 6, 36, 86, 144]      [6, 47, 67, 87, 26]   ← 의도한 전환
        walker        작동  [80, 164, 117, 139, 222]  동일
        stalker       꺼짐  [225, 201, 163, 119, 91]  동일
        dog           작동  [2, 23, 234, 197, 46]     동일
        listener      꺼짐  [155, 112, 52, 24, 134]   동일

    char_shuffle 전체 순위에서 f6 1/192, f60 187/192 다. 고쳐야 할 샘플만 뒤집히고
    검증된 4종은 한 프레임도 흔들리지 않는다. walker·dog 는 항이 작동하는데도
    결과가 같다 — 원래 다리가 벌어진 프레임을 고르고 있었다는 뜻이다.
    """
    valid = [s for s in scores if s.get("bbox") and "leg_gap" in s]
    p = (round(float(np.percentile([s["leg_gap"] for s in valid], LEG_SIGNAL_P)), 4)
         if valid else None)
    if not enabled or p is None or p < LEG_OK:
        for s in scores:
            s["score_adj"] = s["score"]
        return ("off_user" if not enabled else "off_no_signal"), p
    span = LEG_OK - LEG_BAD
    for s in scores:
        t = (s.get("leg_gap", 0.0) - LEG_BAD) / span
        m = LEG_FLOOR + (1 - LEG_FLOOR) * min(max(t, 0.0), 1.0)
        s["score_adj"] = round(s["score"] * m, 4)
    return "on", p


def pick_keyframes(scores, topk, min_gap):
    """점수 상위 topk 를 고르되 후보 사이를 min_gap 프레임 이상 띄운다.

    점수만으로 뽑으면 인접 프레임이 뭉쳐 사실상 같은 장면 K장이 나온다. 2026-09-10
    기준 6샘플 전수에서 재현됐다 — zombie1 은 227·228·229·230·231 로 연속 5장,
    walker 는 77~81, dog 는 0~4 였다. 다중 뷰 입력을 쓰려 해도 고를 것이 없고,
    단일 뷰로 쓸 때도 "5개 후보 중 선택" 이 아니라 사실상 선택지가 하나였다.

    간격 제약의 비용은 거의 없다. 1등과 분산 5등의 점수차가 stalker 0.0011,
    walker 0.0209, listener 0.0259, dog 0.0881 로, 점수를 거의 잃지 않으면서
    진짜 다른 장면을 얻는다.

    greedy: 최고점을 고르고 그 주변 +-min_gap 을 후보에서 빼고 반복한다.
    후보가 모자라면 남는 만큼만 돌려준다(무리해서 채우지 않는다).
    """
    # 정렬 기준은 score_adj 가 있으면 그것 — 다리 항이 꺼졌거나 호출자가 항을
    # 쓰지 않으면 score 와 같으므로 옛 동작이 그대로 보존된다.
    ranked = sorted((s for s in scores if s["bbox"]),
                    key=lambda s: s.get("score_adj", s["score"]), reverse=True)
    if min_gap <= 0:
        return ranked[:topk]
    picked = []
    for cand in ranked:
        if len(picked) >= topk:
            break
        if all(abs(cand["frame"] - p["frame"]) >= min_gap for p in picked):
            picked.append(cand)
    return picked


def main():
    args = parse_args()
    out = os.path.expanduser(args.out)
    frames_dir = os.path.join(out, "frames")
    masks_dir = os.path.join(out, "masks")
    keys_dir = os.path.join(out, "keyframes")
    rgba_dir = os.path.join(out, "rgba")
    for d in (masks_dir, keys_dir):
        os.makedirs(d, exist_ok=True)
    if args.save_rgba:
        os.makedirs(rgba_dir, exist_ok=True)

    n_frames, fps, (w, h) = extract_frames(os.path.expanduser(args.video), frames_dir)

    if args.point:
        px, py = (int(v) for v in args.point.split(","))
    else:
        px, py = w // 2, h // 2          # 노트북은 [640, 360] 고정이었음
    print(f"      타겟 좌표 ({px}, {py})")

    predictor, torch, device = load_predictor(args)
    state = predictor.init_state(video_path=frames_dir)
    predictor.add_new_points_or_box(
        inference_state=state,
        frame_idx=0,
        obj_id=args.obj_id,
        points=np.array([[px, py]], dtype=np.float32),
        labels=np.array([1], dtype=np.int32),   # 1 = 전경
    )

    # 클립은 프레임을 ffmpeg 에 그대로 흘려보내 h264 로 굽는다. OpenCV 의 mp4v
    # 출력물은 브라우저·Jupyter 에서 재생되지 않아 Pod 검증 때 교체했다.
    name = os.path.splitext(os.path.basename(args.video))[0]
    final_mp4 = os.path.join(out, f"{name}_masked.mp4")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 이 필요하다 (마스킹 클립 h264 인코딩)")
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}",
         "-i", "-", "-an",
         "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",   # yuv420p 는 짝수 해상도만 됨
         "-vcodec", "libx264", "-pix_fmt", "yuv420p", final_mp4],
        stdin=subprocess.PIPE)

    print(f"[3/4] 추적 + 마스크/클립 기록 ({n_frames}프레임)")
    scores = []
    autocast = (torch.autocast("cuda", dtype=torch.bfloat16)
                if device == "cuda" else torch.autocast("cpu", enabled=False))
    with torch.inference_mode(), autocast:
        for idx, obj_ids, logits in tqdm(
                predictor.propagate_in_video(state), total=n_frames):
            src = cv2.imread(os.path.join(frames_dir, f"{idx:05d}.jpg"))
            mask = np.zeros((h, w), dtype=bool)
            for i, _ in enumerate(obj_ids):
                mask |= (logits[i] > 0.0).cpu().numpy().squeeze()

            cv2.imwrite(os.path.join(masks_dir, f"{idx:05d}.png"),
                        mask.astype(np.uint8) * 255)

            masked = np.zeros_like(src)          # 배경 검정 3채널 (WHAM 입력 규약)
            masked[mask] = src[mask]
            enc.stdin.write(masked.tobytes())

            if args.save_rgba:
                rgba = np.zeros((h, w, 4), dtype=np.uint8)
                rgba[mask, 0:3] = src[mask]
                rgba[mask, 3] = 255
                cv2.imwrite(os.path.join(rgba_dir, f"{idx:05d}.png"), rgba)

            s, bbox = keyframe_score(mask)
            scores.append({"frame": int(idx), "score": round(float(s), 4), "bbox": bbox,
                           "leg_gap": round(leg_gap_ratio(mask), 4)})
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError(f"ffmpeg 인코딩 실패: {final_mp4}")

    # 키프레임 후보: 점수 상위 K개를 알파 PNG 로 저장
    leg_state, leg_signal = apply_leg_term(scores, enabled=(args.leg_term == "on"))
    ranked = pick_keyframes(scores, args.topk, args.keyframe_min_gap)
    for rank, s in enumerate(ranked, 1):
        idx = s["frame"]
        src = cv2.imread(os.path.join(frames_dir, f"{idx:05d}.jpg"))
        m = cv2.imread(os.path.join(masks_dir, f"{idx:05d}.png"),
                       cv2.IMREAD_GRAYSCALE) > 127
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[m, 0:3] = src[m]
        rgba[m, 3] = 255
        cv2.imwrite(os.path.join(keys_dir, f"key{rank}_f{idx:05d}.png"), rgba)
    with open(os.path.join(keys_dir, "candidates.json"), "w") as f:
        json.dump({"topk": ranked, "all": scores,
                   "min_gap": args.keyframe_min_gap,
                   "leg_term": leg_state,
                   "leg_signal": leg_signal,      # 가드가 본 p90 간격비
                   "leg_thresholds": {"bad": LEG_BAD, "ok": LEG_OK,
                                      "floor": LEG_FLOOR, "band": list(LEG_BAND),
                                      "signal_p": LEG_SIGNAL_P}}, f, indent=2)
    why = {"on": "작동", "off_user": "꺼짐(사용자 지정)",
           "off_no_signal": "꺼짐(가드)"}[leg_state]
    print(f"[4/4] 키프레임 후보 {len(ranked)}장 (최소 간격 {args.keyframe_min_gap}, "
          f"다리 항 {why}) → {keys_dir}")
    if leg_state == "off_no_signal":
        # 조용히 넘기지 않는다. 판정은 WHAM 결과가 있는 재선정 단계의 몫이지만
        # (독스트링 참조) 그 단계가 생기기 전까지는 여기서 사람에게 알린다.
        print(f"      ⚠️  이 클립에는 다리가 벌어진 프레임이 없다 "
              f"(p{LEG_SIGNAL_P} 간격비 {leg_signal} < {LEG_OK}). 다리 항 없이 "
              f"구점수로 뽑았다. 동작에 다리 움직임이 있으면 다리가 붙은 메쉬는 "
              f"리깅에서 깨진다 — 후보를 눈으로 확인할 것.")
    print("      " + ", ".join(
        f"f{s['frame']}({s.get('score_adj', s['score'])}, 다리 {s['leg_gap']})"
        for s in ranked))

    if not args.keep_frames:
        shutil.rmtree(frames_dir)

    print(f"\n완료: {out}")
    print(f"  마스크 {n_frames}장 | 클립 {final_mp4}")


if __name__ == "__main__":
    main()
