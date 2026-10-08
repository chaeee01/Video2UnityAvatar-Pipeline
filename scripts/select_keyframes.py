"""
G1a 키프레임 선정: 마스크(와 WHAM pose)로 TRELLIS 입력 프레임을 고른다.

두 군데서 쓴다.
  1. run_sam2.py (S2) 가 import 해서 1차 후보를 낸다 — 마스크만 본다 (다리 항까지).
  2. 이 파일을 직접 실행하면 **재선정 단계**다 — S5(WHAM) 뒤에 돌아 pose 에서 뽑은
     지표를 더해 순위를 다시 매기고, S3 가 읽는 keyframes/ 를 갱신한다.

  python select_keyframes.py \
      --sam2-dir /workspace/data/02_sam2/<샘플> \
      --video    /workspace/data/00_raw/<샘플>.mp4 \
      --wham-pkl /workspace/data/04_wham/<샘플>_masked/wham_output.pkl

순서는 S2 → S5 → (이 단계) → S3 다 (2026-10-07 결정, 근거는 keyframe_score 독스트링).
2026-10-08 에 run_sam2.py 에서 떼어 냈다 — 그전에는 선정을 다시 하려면 SAM2 전체를
다시 돌려야 했다.

재선정이 하는 일:
  - 프레임별 점수는 keyframes/candidates.json 의 기록을 다시 쓴다 (leg_gap 이 없는
    옛 기록이면 masks/ 에서 다시 잰다).
  - WHAM pose 에서 **시선 이탈각**(얼굴이 카메라를 향하는가)을 재서 숙이거나 돌아선
    프레임을 깎는다.
  - 다리 항이 가드로 꺼진 클립은 **다리 움직임 범위**를 보고 진행하거나 사람에게
    넘긴다 (종료 코드 2).
  - S2 가 낸 원래 후보는 keyframes/_s2pick/ 에 **최초 1회만** 보존한다. 재선정을
    다시 돌려도 그 보존분은 덮지 않는다.
  - 키프레임 PNG 는 원본 영상에서 프레임을 다시 읽어 만든다 (S2 의 frames/ 는 중간
    산출물이라 지워져 있다).
"""
import argparse
import json
import os
import shutil
import sys

import cv2
import numpy as np


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

    **얼굴 항은 WHAM 시선각으로 구현했다 (2026-10-08) — `apply_gaze_term()`.** 아래는
    그 경위다. 10/7 시점에는 "신호는 실증됐고, 막는 것은 순서" 였다.
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

    당시 넣지 못한 이유는 **순서 하나뿐이었다.** 키프레임 선정이 S2 안에서 일어나는데
    WHAM(S5)은 S3 뒤에 있었다.

    **채택 방향 (2026-10-07 결정, 2026-10-08 구현 — 이 파일의 main() 이 재선정 단계다)** —

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
    "다리 움직임 유무" 는 `leg_motion_deg()` 로 재고 `judge_closed_legs()` 가 판정한다.
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


# ── 키프레임 내보내기 · 기록 (S2 와 재선정이 함께 쓴다) ──────────────────────
def export_keyframes(ranked, read_frame, masks_dir, keys_dir):
    """선정된 프레임을 알파 PNG 로 쓴다. read_frame(idx) 는 BGR 프레임을 돌려준다.

    쓰기 전에 **이전 key*.png 를 지운다.** 파일명에 순위와 프레임 번호가 들어 있어
    선정이 바뀌면 이름이 달라지는데, 옛 파일이 남으면 `key1_f*.png` 가 여러 장이
    된다. 실제로 그랬다 — char_shuffle 의 keyframes/ 에는 S2 재시도 4회의 key1 이
    f60·f67·f86·f168 로 쌓여 있었고(2026-10-08 확인), 오케스트레이터는 그중 이름순
    첫 장을 집었다. 9/30 E2E 에서 그것이 최종 1등(f60)과 같았던 것은 우연이다.
    """
    os.makedirs(keys_dir, exist_ok=True)
    for f in os.listdir(keys_dir):
        if f.startswith("key") and f.endswith(".png"):
            os.remove(os.path.join(keys_dir, f))
    paths = []
    for rank, s in enumerate(ranked, 1):
        idx = s["frame"]
        src = read_frame(idx)
        m = cv2.imread(os.path.join(masks_dir, f"{idx:05d}.png"), cv2.IMREAD_GRAYSCALE)
        if src is None or m is None:
            raise RuntimeError(f"프레임 {idx} 의 원본 또는 마스크를 읽지 못함")
        m = m > 127
        h, w = m.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)
        rgba[m, 0:3] = src[m]
        rgba[m, 3] = 255
        p = os.path.join(keys_dir, f"key{rank}_f{idx:05d}.png")
        cv2.imwrite(p, rgba)
        paths.append(p)
    return paths


def leg_thresholds():
    return {"bad": LEG_BAD, "ok": LEG_OK, "floor": LEG_FLOOR,
            "band": list(LEG_BAND), "signal_p": LEG_SIGNAL_P}


def write_candidates(keys_dir, ranked, scores, min_gap, leg_state, leg_signal, extra=None):
    doc = {"topk": ranked, "all": scores, "min_gap": min_gap,
           "leg_term": leg_state,
           "leg_signal": leg_signal,          # 가드가 본 p90 간격비
           "leg_thresholds": leg_thresholds()}
    doc.update(extra or {})
    with open(os.path.join(keys_dir, "candidates.json"), "w") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)


# ── WHAM pose 지표 ───────────────────────────────────────────────────────────
# SMPL 24본에서 골반 → 머리로 가는 사슬.
HEAD_CHAIN = (0, 3, 6, 9, 12, 15)
# 다리 4관절: L_Hip, R_Hip, L_Knee, R_Knee
LEG_JOINTS = (1, 2, 4, 5)


# 시선 항·다리 움직임 상수. 2026-10-08 에 6샘플(WHAM 5 + 추적 실패 1) 실측으로 확정했다.
#
#   샘플          시선 이탈각 최소/중앙/최대   다리 움직임   채택 프레임의 이탈각     에셋
#   char_shuffle   3.4 / 18.5 / 64.9          106.8° (춤)   f6 5.4° · f60 56.6°      f6 합격 · f60 불합격
#   zombie1       16.0 / 27.5 / 38.0           38.6° (걷기)  f228 25.2°              합격
#   walker         4.8 / 15.1 / 29.4           11.2° (제자리) f222 15.4°              메쉬 양호
#   stalker        1.3 /  7.3 / 20.2           10.4° (제자리) f162  6.3°              메쉬 양호
#   dog           25.7 / 31.0 / 55.3           39.3° (기기)  f0  33.9°               메쉬 양호
#   listener      WHAM 추적 실패 (마스크가 얼굴뿐) — 재선정은 멈춘다
#
#   GAZE_OK  30°   이 아래는 감점하지 않는다. 채택해서 결과가 좋았던 프레임이 전부
#                  5.4~33.9° 다. dog f0(33.9°)는 계수 0.90 으로 가볍게만 깎인다.
#   GAZE_BAD 50°   이 위는 최대 감점. 불합격 실물은 f60(56.6°) 하나이고, 같은 구간의
#                  후보 f47(51.3°)·f67(58.5°)·dog f23(54.7°)이 이 항으로 빠진다.
#   GAZE_FLOOR 0.5 다리 항과 같은 바닥. 5샘플 모두 1등이 유지된다 — 고쳐야 할 것은
#                  "1등 뒤에 숙인 프레임이 후보로 섞이는 것" 이었다.
#   LEG_MOTION_MIN 15°  이 위면 "다리가 움직이는 동작" 으로 본다. 제자리 영상 2건이
#                  10.4°·11.2°, 움직이는 3건이 38.6° 이상이다. 아래쪽 여유가 4° 뿐이지만
#                  틀려도 "사람에게 인계" 쪽으로 틀린다 (움직이는데 정지로 오판해
#                  다리 붙은 메쉬를 통과시키는 쪽이 더 나쁘다).
#
# 재보정할 때는 위 표가 기준이다. 30~50° 사이에 불합격 실물이 생기면 GAZE_OK 부터 본다.
GAZE_OK, GAZE_BAD, GAZE_FLOOR = 30.0, 50.0, 0.5
LEG_MOTION_MIN = 15.0

EXIT_OK, EXIT_FAIL, EXIT_HUMAN = 0, 1, 2      # orchestrate.py 와 같은 규약


def load_wham_track(pkl_path, track=None):
    """wham_output.pkl 에서 트랙 하나를 읽어 (frame_ids, pose[N,72]) 를 돌려준다.

    pose 는 **카메라 좌표**다 (pkl 의 `pose`. `pose_world` 가 아니다) — "얼굴이
    카메라를 향하는가" 를 재려면 카메라 기준이어야 한다.
    """
    import joblib
    data = joblib.load(pkl_path)
    keys = list(data.keys())
    if not keys:
        raise RuntimeError(f"WHAM 이 사람을 하나도 추적하지 못했다: {pkl_path}")
    key = keys[0] if track is None else (track if track in data else type(keys[0])(track))
    if key not in data:
        raise RuntimeError(f"트랙 {track} 없음. 있는 트랙: {keys}")
    if track is None and len(keys) > 1:
        print(f"  ⚠️  트랙이 {len(keys)}개다 — 첫 번째({key})를 쓴다. --track 으로 지정 가능")
    t = data[key]
    for k in ("pose", "frame_ids"):
        if k not in t:
            raise RuntimeError(f"pkl 에 '{k}' 가 없다. 있는 키: {list(t)}")
    pose = np.asarray(t["pose"], dtype=np.float64).reshape(len(t["pose"]), 24, 3)
    return [int(f) for f in t["frame_ids"]], pose


def _rot(aa):
    return cv2.Rodrigues(np.asarray(aa, dtype=np.float64))[0]


def gaze_offaxis_deg(pose_frame):
    """시선이 카메라 축에서 벗어난 각(도). 0 이면 카메라를 똑바로 본다.

    머리 사슬의 회전을 합성해 시선 벡터를 얻는다. WHAM 카메라 좌표는 Y-down 이고
    카메라가 +Z 를 보므로, 카메라를 마주 보는 시선은 -Z 다. 고개를 숙인 것(수직
    이탈)과 옆·뒤로 돌아선 것(수평 이탈)을 한 값으로 잡는다.

    2026-10-07 프로브: char_shuffle f6(정면, 에셋 합격) 5.4° / f60(숙임, 불합격) 56.6°.
    """
    R = np.eye(3)
    for j in HEAD_CHAIN:
        R = R @ _rot(pose_frame[j])
    gaze = R @ np.array([0.0, 0.0, 1.0])
    return float(np.degrees(np.arccos(np.clip(-gaze[2], -1.0, 1.0))))


def leg_motion_deg(pose):
    """클립에서 다리가 얼마나 움직이는가(도). 다리 4관절 회전 크기의 p95-p5 범위 중 최댓값.

    다리 항이 가드로 꺼진 클립(벌린 프레임이 없음)을 그대로 진행해도 되는지 가르는
    데 쓴다 — 다리가 움직이지 않는 동작이면 다리가 붙은 메쉬도 리깅에서 깨지지 않는다.

    2026-10-07 실측: char_shuffle(셔플 댄스) 106.8° / zombie1(걷기) 38.6°.
    """
    mag = np.degrees(np.linalg.norm(pose[:, LEG_JOINTS, :], axis=2))    # [N, 4]
    rng = np.percentile(mag, 95, axis=0) - np.percentile(mag, 5, axis=0)
    return float(rng.max())


def apply_gaze_term(scores, enabled=True):
    """얼굴이 카메라에서 벗어난 프레임을 깎는다. `score_adj` 에 곱한다 (다리 항 뒤에 부른다).

    다리 항과 같은 꼴이다 — 감점 전용·포화형.

        m = GAZE_FLOOR + (1 - GAZE_FLOOR) * clamp((GAZE_BAD - a) / (GAZE_BAD - GAZE_OK), 0, 1)

    클립 가드는 두지 않는다. 다리 항은 "벌린 프레임이 아예 없는 클립" 에서 순위를
    뒤흔들어 가드가 필요했지만, 시선 항은 GAZE_OK 아래가 전부 1.0 이라 정면 프레임이
    있는 클립에서는 그쪽이 그대로 남고, 전 프레임이 숙인 클립이면 전부 같은 바닥으로
    깎여 순위가 유지된다.
    """
    for s in scores:
        s.setdefault("score_adj", s["score"])
        a = s.get("gaze_offaxis")
        if not enabled or a is None:
            continue
        t = (GAZE_BAD - a) / (GAZE_BAD - GAZE_OK)
        m = GAZE_FLOOR + (1 - GAZE_FLOOR) * min(max(t, 0.0), 1.0)
        s["gaze_mult"] = round(m, 4)
        s["score_adj"] = round(s["score_adj"] * m, 4)
    return "on" if enabled else "off_user"


def judge_closed_legs(leg_state, motion_deg):
    """다리 항이 가드로 꺼진 클립을 그대로 진행해도 되는가.

    가드로 꺼졌다는 것은 이 클립에 다리 벌린 프레임이 없다는 뜻이다. 그 자체는 결함이
    아니다 — **동작이 다리를 움직일 때만** 문제다. 다리가 붙은 메쉬는 두 다리가 한
    덩어리라 웨이트가 좌우로 갈리지 않고, 다리가 움직이면 그 자리가 찢어진다
    (char_shuffle f60 의 좌우 교차 배정 38.3%).

    돌려주는 값은 (판정, 설명). 판정은 "ok" / "ok_static" / "human".
      ok         다리 항이 작동했다 — 판정할 것이 없다
      ok_static  가드로 꺼졌지만 다리가 움직이지 않는 동작이다 → 다리 붙은 메쉬 허용
      human      가드로 꺼졌고 다리가 움직인다 → 사람에게 넘긴다

    "human" 은 불합격이 아니라 인계다. 실증 표본이 f60 한 건이라 자동으로 막지 않는다.
    실물 사례 — stalker 는 가드로 꺼지고 다리 움직임 10.4° 라 ok_static 이다.
    """
    if leg_state != "off_no_signal":
        return "ok", ""
    if motion_deg < LEG_MOTION_MIN:
        return "ok_static", (f"다리 벌린 프레임이 없지만 동작에 다리 움직임이 없다 "
                             f"({motion_deg}° < {LEG_MOTION_MIN}°) — 다리 붙은 메쉬를 허용한다")
    return "human", (f"다리 벌린 프레임이 없는데 동작은 다리를 움직인다 "
                     f"({motion_deg}° ≥ {LEG_MOTION_MIN}°) — 다리가 붙은 메쉬는 리깅에서 깨진다")


# ── 재선정 단계 (CLI) ────────────────────────────────────────────────────────
def score_masks(masks_dir):
    """masks/ 의 전 프레임 점수를 다시 잰다 (candidates.json 에 leg_gap 이 없을 때)."""
    out = []
    for f in sorted(os.listdir(masks_dir)):
        if not f.endswith(".png"):
            continue
        m = cv2.imread(os.path.join(masks_dir, f), cv2.IMREAD_GRAYSCALE) > 127
        s, bbox = keyframe_score(m)
        out.append({"frame": int(f[:-4]), "score": round(float(s), 4), "bbox": bbox,
                    "leg_gap": round(leg_gap_ratio(m), 4)})
    return out


def video_frame_reader(video_path, wanted):
    """영상을 한 번 순차로 읽어 필요한 프레임만 쥔다.

    탐색(seek)을 쓰지 않는다 — h264 에서 CAP_PROP_POS_FRAMES 는 키프레임 근처로
    어긋날 수 있고, 한 프레임만 밀려도 마스크와 원본이 엇갈린다.
    """
    wanted = set(wanted)
    got = {}
    cam = cv2.VideoCapture(video_path)
    if not cam.isOpened():
        raise RuntimeError(f"영상을 열지 못함: {video_path}")
    n = 0
    while wanted - set(got):
        ok, frame = cam.read()
        if not ok:
            break
        if n in wanted:
            got[n] = frame
        n += 1
    cam.release()
    return got.get


def preserve_s2_pick(keys_dir):
    """S2 가 낸 원래 후보를 _s2pick/ 에 옮겨 둔다 — **최초 1회만.**

    _s2pick/ 가 이미 있으면 아무것도 옮기지 않는다. 재선정을 다시 돌릴 때 keyframes/
    에 있는 것은 이전 재선정의 결과이지 S2 원본이 아니므로, 그것으로 보존분을 덮으면
    S2 원본을 잃는다. 돌려주는 값은 이번에 보존했는지 여부.
    """
    keep = os.path.join(keys_dir, "_s2pick")
    first = not os.path.isdir(keep)
    if first:
        tmp = keep + ".partial"            # 중간에 죽어도 반쪽짜리 _s2pick 이 남지 않게
        if os.path.isdir(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp)
        for f in sorted(os.listdir(keys_dir)):
            p = os.path.join(keys_dir, f)
            if os.path.isfile(p) and (f.endswith(".png") or f == "candidates.json"):
                shutil.copy2(p, os.path.join(tmp, f))
        os.rename(tmp, keep)
    return first


def parse_args():
    ap = argparse.ArgumentParser(description="G1a 재선정 — S5 뒤에 키프레임 순위를 다시 매긴다")
    ap.add_argument("--sam2-dir", required=True, help="S2 출력 폴더 (masks/ · keyframes/ 가 있는 곳)")
    ap.add_argument("--video", required=True, help="원본 영상 (키프레임 PNG 를 다시 만들 때 읽는다)")
    ap.add_argument("--wham-pkl", required=True, help="S5 출력 wham_output.pkl")
    ap.add_argument("--track", default=None, help="WHAM 트랙 (기본: 첫 번째)")
    ap.add_argument("--topk", type=int, default=5)
    ap.add_argument("--keyframe-min-gap", type=int, default=20)
    ap.add_argument("--leg-term", choices=["on", "off"], default="on")
    ap.add_argument("--gaze-term", choices=["on", "off"], default="on",
                    help="시선 이탈각 감점 (기본 on)")
    ap.add_argument("--allow-closed-legs", action="store_true",
                    help="다리 벌린 프레임이 없고 동작이 다리를 움직이는 클립을 강행한다 "
                         "(기본은 종료 코드 2 로 사람에게 넘김)")
    return ap.parse_args()


def main():
    a = parse_args()
    sam2_dir = os.path.expanduser(a.sam2_dir)
    masks_dir = os.path.join(sam2_dir, "masks")
    keys_dir = os.path.join(sam2_dir, "keyframes")
    cand_path = os.path.join(keys_dir, "candidates.json")
    if not os.path.isdir(masks_dir):
        raise SystemExit(f"masks/ 가 없다: {masks_dir}")
    if not os.path.exists(cand_path):
        raise SystemExit(f"S2 의 candidates.json 이 없다: {cand_path}")

    # [1/4] 프레임별 점수 — S2 기록을 다시 쓰고, 옛 기록이면 마스크에서 다시 잰다
    scores = json.load(open(cand_path)).get("all", [])
    if not scores or any("leg_gap" not in s for s in scores if s.get("bbox")):
        print("[1/4] candidates.json 에 leg_gap 이 없다 — masks/ 에서 다시 잰다")
        scores = score_masks(masks_dir)
    else:
        scores = [{k: s[k] for k in ("frame", "score", "bbox", "leg_gap")} for s in scores]
        print(f"[1/4] S2 기록 재사용 ({len(scores)}프레임)")

    # [2/4] WHAM pose 지표. 프레임 대응은 frame_ids 로 한다.
    frame_ids, pose = load_wham_track(os.path.expanduser(a.wham_pkl), a.track)
    gaze = {f: round(gaze_offaxis_deg(p), 2) for f, p in zip(frame_ids, pose)}
    motion = round(leg_motion_deg(pose), 2)
    known = {s["frame"] for s in scores}
    if not set(frame_ids) <= known:
        raise SystemExit(f"WHAM frame_ids 가 마스크 범위를 벗어난다 "
                         f"(마스크 {len(known)}장, WHAM 최대 {max(frame_ids)}) — 다른 영상의 pkl 인가")
    untracked = sorted(known - set(frame_ids))
    for s in scores:
        s["gaze_offaxis"] = gaze.get(s["frame"])          # 추적 누락이면 None
    print(f"[2/4] WHAM {len(frame_ids)}프레임, 추적 누락 {len(untracked)}프레임, "
          f"다리 움직임 {motion}°")

    # [3/4] 순위. WHAM 이 추적하지 못한 프레임은 후보에서 뺀다 — 동작이 없는
    # 프레임은 5-1 이 SMPL 메쉬를 만들 수 없어 키프레임이 될 수 없다.
    usable = [s for s in scores if s["gaze_offaxis"] is not None]
    leg_state, leg_signal = apply_leg_term(usable, enabled=(a.leg_term == "on"))
    gaze_state = apply_gaze_term(usable, enabled=(a.gaze_term == "on"))
    ranked = pick_keyframes(usable, a.topk, a.keyframe_min_gap)
    if not ranked:
        raise SystemExit("후보가 하나도 남지 않았다")
    print(f"[3/4] 다리 항 {leg_state} (p{LEG_SIGNAL_P} 간격비 {leg_signal}), 시선 항 {gaze_state}")

    # 가드로 꺼진 클립은 조용히 넘기지 않는다. 멈출 때는 keyframes/ 를 건드리지 않는다
    # — 사람이 S2 후보를 보고 판단해야 하므로.
    legs, why = judge_closed_legs(leg_state, motion)
    forced = False
    if legs == "human":
        if not a.allow_closed_legs:
            print(f"\n[인계] {why}")
            print("  권고: 다리가 벌어진 프레임이 있는 영상으로 다시 만든다.")
            print("  강행: --allow-closed-legs (오케스트레이터에서는 --force-keyframe)")
            return EXIT_HUMAN
        forced = True
        print(f"      ⚠️  강행 — {why}")
    elif legs == "ok_static":
        print(f"      {why}")

    # [4/4] 보존 → 내보내기 → 기록
    first = preserve_s2_pick(keys_dir)
    read = video_frame_reader(os.path.expanduser(a.video), [s["frame"] for s in ranked])
    export_keyframes(ranked, read, masks_dir, keys_dir)
    write_candidates(keys_dir, ranked, scores, a.keyframe_min_gap, leg_state, leg_signal, extra={
        "stage": "g1a_reselect",
        "wham": {"pkl": a.wham_pkl, "frames": len(frame_ids), "untracked": untracked,
                 "leg_motion_deg": motion},
        "gaze_term": gaze_state,
        "gaze_thresholds": {"ok": GAZE_OK, "bad": GAZE_BAD, "floor": GAZE_FLOOR},
        "closed_legs": {"verdict": legs, "forced": forced,
                        "leg_motion_min": LEG_MOTION_MIN},
    })
    print(f"[4/4] 키프레임 {len(ranked)}장 → {keys_dir}"
          f"  (S2 원본 후보 {'보존함' if first else '보존분 유지'}: _s2pick/)")
    print("      " + ", ".join(
        f"f{s['frame']}({s.get('score_adj', s['score'])}, 다리 {s['leg_gap']}, "
        f"시선 {s['gaze_offaxis']}°)" for s in ranked))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
