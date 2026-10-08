"""G2r 게이트: SMPL 정렬·리깅 결과를 판정한다.

align_smpl_to_trellis.py 의 aligned_params.json 과 transfer_weights.py 의 로그를
읽어 리깅 사슬이 제대로 붙었는지 본다. 세 지표 모두 기존 RUNBOOK 5-2·5-3·5-4 의
확인 포인트를 그대로 옮긴 것이다 — 사람이 눈으로 보던 수치를 게이트로 만든다.

  python gate_g2r.py --params ~/data/06_rig/<샘플>/aligned_params.json --out <폴더>
  python gate_g2r.py --params ... --joint-dist 0.0293 --fallback-pct 3.67 --out <폴더>
  python gate_g2r.py --params ... --transferred <transferred_params.json> --out <폴더>

--transferred 를 주면 폴백 분포(fallback_detail)를 읽어 **폴백 총량과 무관하게**
분포를 판정한다. 위험 분류면 총량이 경고선 아래여도 경고한다. 같은 파일의 rig_check
(본→메쉬 거리 · 지배 정점 · 좌우 교차 배정)로 ①②③ 도 판정한다.

관절거리와 폴백률은 별도 파일로 남지 않아 인자로 받는다 (create_smpl_armature.py·
transfer_weights.py 가 로그로만 찍는다 — 구조화 출력이 필요하다는 것이 이 게이트를
쓰면서 드러난 숙제다).

출력: <out>/gate_g2r.json (gate_s2 와 같은 스키마).
"""
import argparse
import json
import os
import sys

# ── 임계값과 근거 ────────────────────────────────────────────────────────────
# SCALE_MIN/MAX = 0.55 / 0.65
#   SMPL 표준 신장과 TRELLIS 정규화 크기의 비에서 나오는 구조 상수다. 캐릭터가
#   달라도 이 범위를 벗어나지 않는다 — 5회 측정에서 0.588(zombie_sample1),
#   0.5906(zombie1 1세대), 0.5892(zombie1 2세대 512), 0.5914(zombie1 1024),
#   그리고 zombie_sample1 재측정이 모두 0.588~0.5914 에 들어왔다. 범위를 벗어나면
#   상류 단계(SMPL 생성 또는 TRELLIS 스케일)의 오류 신호다.
# IOU_MIN = 0.5
#   실측 0.717 / 0.743 / 0.760 / 0.797. 0.5 는 RUNBOOK 이 쓰던 값 그대로다.
#   2세대는 열린 자락 탓 1세대보다 낮게 나오는 것이 정상이다.
# JOINT_DIST_MAX = 0.2
#   실측 0.028 / 0.0292 / 0.0293 로 임계값과 7배 차이가 난다. 이 값은 좌표계
#   판정이 틀렸을 때를 잡기 위한 것이다 — 틀린 후보는 2.6~4.1 로 두 자릿수
#   차이가 나므로 0.2 면 충분하다.
# FALLBACK_WARN_PCT = 8.0
#   직선거리 폴백은 천으로 떨어진 부위에 웨이트가 건너뛸 수 있어 낮을수록 좋다.
#
# ── 확장 후보 3지표 (2026-10-01 실측, W5 게이트 작업일에 임계 확정) ──────────
#   char_shuffle 이 **현 게이트를 전부 통과하고도 품질 불합격**이었다 (폴백 3.708%,
#   무배정 0%, IoU 0.9762 로 PASS). 아래 셋은 그 결함을 전부 잡아낸다.
#
#   ① 본→메쉬 최근접 거리의 좌우 비대칭
#      L_Hand 0.0852 vs R_Hand 0.0123 (7배). 왼손 본이 메쉬 밖에 있었다.
#      9/22 에 등록한 "관절-TRELLIS 표면 거리" 후보의 실측이 이것이다.
#      토르소 본은 몸 안쪽이라 거리가 먼 게 정상이므로 **좌우 대칭 쌍으로** 본다.
#   ② 좌우 교차 배정률
#      L_Ankle 정점의 38.3% 가 오른쪽 몸에 있었다 (R_Ankle 은 0.2%). 다리가 융합된
#      메쉬에서 Data Transfer 가 다리 사이를 건너뛴 결과다.
#   ③ 지배 정점이 0 인 본
#      L_Hand·L_Wrist 가 0 이었다. 그 본이 회전해도 따라올 지오메트리가 없다.
#
#   셋 다 계산이 싸고 판별력이 분명하다. 임계는 표본을 더 모아 정한다.
#
# ── ①②③ 게이트 코드화 (2026-10-09 구현) ────────────────────────────────────
#   원자료는 transfer_weights.py 의 rig_check 가 재서 transferred_params.json 에 남긴다.
#   5샘플 실측 (tests/fixtures/g2r_rig_check.json 에 전수 보관):
#
#                        ① 말단 본 최대 거리     ② 최대 교차        ③ 지배 0 본        육안
#     char_shuffle f60   0.0852 L_Hand · 0.0642 L_Wrist   28.3% R_Knee · 13.1% L_Ankle   L_Wrist · L_Hand   불합격
#     char_shuffle f6    0.0096                 1.4%               없음 (최소 0.262%)   합격
#     zombie1 1024       0.0239                 4.2%               없음 (최소 0.386%)   합격
#     zombie1 512        0.0172                 6.7%               없음 (최소 0.269%)   합격
#     zombie1 1세대      0.0632 R_Hand          26.1% R_Knee       R_Hand             합격(아래 참조)
#
#   **지표 정의가 10/1 첫 측정과 두 군데 다르다.**
#   ① 은 **말단 8본(손목·손·발목·발)의 절댓값**만 본다. 10/1 에는 "좌우 비대칭 배수"
#      로 적었는데 배수는 못 쓴다 — 합격한 f6 도 배수는 6~8배이고 절댓값이 전부 0.01
#      이하일 뿐이다. 말단으로 한정하는 이유는 몸통·엉덩이·무릎 본이 원래 몸 안쪽에
#      있어서다. 합격 샘플에서도 Hip 0.05~0.07, Spine2 0.07~0.09 가 나온다.
#   ② 는 **좌우 본 쌍의 이등분면** 기준이다. 10/1 의 "L_Ankle 38.3%" 는 몸 정중선을
#      수직면(x=0)으로 잡은 값인데, 그 정의는 기울어 선 자세에서 틀린다 — zombie1 은
#      상체가 기울어 R_Collar 가 70% 로 나왔다(결함이 아니다). 이등분면으로는 f60 이
#      L_Ankle 13.1% · R_Knee 28.3% 다.
#
#   임계 (잠정 — 표본 5건, 불합격 실물은 f60 하나. 표본이 쌓이면 재보정한다):
#     DISTAL_DIST_MAX = 0.03   합격 최대 0.0239 / f60 0.0642·0.0852. 여유 넉넉.
#     CROSS_MAX_PCT   = 10.0   **합격 최대 6.7% / 불합격 13.1% 사이 — 여유가 얇다.**
#                              재보정 1순위. 지배 정점이 CROSS_MIN_VERTS(100) 미만인
#                              본은 비율이 조각 하나에 휘둘려 보지 않는다.
#     DOM_MIN_PCT     = 0.01   지배 정점이 전체의 이 비율(%) 미만이면 "따라올 정점이
#                              없다" 로 본다. 합격 최소 0.262% / f60 은 0.
#
#   **판정 수위.** 불합격은 **같은 본에서 ①과 ③이 함께** 걸릴 때만이다 — 본이 메쉬
#   밖에 있고 따라올 정점도 없으면, 그 본이 움직일 때 주변 조각이 다른 본을 따라간다.
#   f60 의 L_Wrist 가 그 경우다. 하나만 걸리면 경고다. ② 는 단독으로는 항상 경고다
#   (여유가 얇아 불합격을 낼 근거가 약하다).
#
#   **불합격 대상에서 손(Hand)은 뺀다 — FAIL_BONES.** zombie1 1세대가 R_Hand 에서 ①③ 이
#   함께 걸리는데, 렌더로 확인하니 손 메쉬는 온전하고 SMPL 의 손 본만 메쉬 옆 허공에
#   있다(메쉬의 손은 아래로 늘어졌고 SMPL 의 손은 팔 방향으로 뻗었다). 손 정점은 손목을
#   따라간다. 그런데 **WHAM 은 손 관절을 거의 움직이지 않는다** — 5편에서 손 관절 회전
#   범위가 1.3~6.0° 이고 손목은 12.7~35.3° 다. 손목이 정점을 쥐고 있으면 손 본이 비어
#   있어도 동작에 차이가 없다. f60 은 **손목까지** 비어 있어서(L_Wrist·L_Hand) 손목
#   회전이 통째로 사라졌다. 그래서 불합격은 WHAM 이 실제로 움직이는 관절(손목·발목·발)
#   에서만 내고, 손에서 걸리면 경고로 둔다.
#   **이 면제의 전제는 모션 소스가 WHAM 이라는 것이다.** WHAM 은 손 관절을 거의 구동하지
#   않는다(실측 1.3~6.0°). 손 관절을 움직이는 모션 소스 — AMASS 같은 외부 SMPL 모션 —
#   를 들여오면 손 본이 비어 있는 것이 그대로 결함이 되므로 **이 면제를 재검토한다.**
#
#   ④ 는 아래대로 독립 경고다. 수위를 올리는 데 쓰지 않고, 불합격 사유에 "사라진
#   정점이 어디로 갔는지" 의 근거로 인용한다.
#   실측 1.49%(512) / 3.67%(1024) 이고 둘 다 포즈 시험을 통과했다. 상한의 근거가
#   약해 불합격이 아니라 경고로 둔다 — 8%는 1024 실측의 두 배를 조금 넘는 값이다.
#
# ── ④ 폴백 분포 판정 — 상시 평가 (2026-10-07 구현) ──────────────────────────
#   폴백 총량은 품질을 가르지 못한다. 표본 둘이 정반대로 나왔다 —
#
#                         폴백      사지 본 비율   소스거리 p90   육안
#     char_shuffle f60    3.708%    47.53%         0.0606         불합격 (10/1)
#     char_shuffle f6     8.921%     1.84%         0.0229         합격   (10/6)
#     (f6 은 1536_cascade)
#
#   총량으로는 f6 이 2.4배 나쁜데 결과는 반대다. 가르는 것은 **어느 본으로,
#   얼마나 멀리서** 붙었느냐다. f6 의 폴백은 58.9% 가 Head, 27.2% 가 Collar 로
#   간다 — 머리카락 UV 섬과 어깨 장비가 강체 본에 붙은 것이라 움직여도 티가
#   나지 않는다. f60 은 L_Elbow 한 본으로 26.8% 가 갔다 — 정렬이 어긋나 SMPL
#   에서 멀어진 왼손 메쉬가 통째로 팔꿈치 웨이트를 빌렸다.
#
#   그래서 분포를 **총량과 무관하게 항상** 본다.
#     FB_LIMB_MAX_PCT = 35.0    사지 본(어깨·팔꿈치·손목·손·엉덩이·무릎·발목·발)
#                               으로 간 폴백 비율. **합격 최대 26.5% / 불합격 47.5%**
#                               (5샘플). 10/7 에는 2샘플(1.84 / 47.53)로 20 을 잡았는데,
#                               10/9 에 zombie1 1024·512(합격)가 21.0%·26.5% 로 나와
#                               오탐 경고가 됐다 — 35 로 올렸다.
#     FB_SRC_P90_MAX  = 0.04    웨이트를 빌려 온 거리의 p90 (정렬 공간, 신장 약 1.0).
#                               0.0229 와 0.0606 사이. 1차 전이 반경 0.08 의 절반.
#                               5샘플에서도 유효하다 (합격 최대 0.0336).
#   둘 중 하나라도 넘으면 "위험", 둘 다 아래면 "무해" 다.
#     FB_MIN_VERTS    = 1000    잡음 가드. 폴백 정점이 이보다 적으면 분류하지 않는다.
#                               p90 과 본별 비율은 표본이 작으면 조각 한두 개에
#                               휘둘린다. 1000 은 70만 정점 메쉬의 약 0.14% 로,
#                               지금까지의 실측 최솟값(zombie1 512 의 1.49%)보다
#                               한 자릿수 아래다 — 실제 샘플은 걸리지 않고, 폴백이
#                               사실상 없는 메쉬만 건너뛴다.
#
#   **발동 조건을 총량에 걸지 않는다.** 처음에는 "폴백이 8% 경고선을 넘을 때만
#   2차 판정" 으로 짰는데, 그러면 이 메모의 전제("총량은 품질을 가르지 못한다")와
#   모순된다 — f60 은 3.708% 라 판정이 돌지 않아 위험 분류인데도 무경고 PASS 였다.
#   그래서 상시 평가로 바꿨다. 결과는 넷이다.
#
#       총량 ≤ 8%, 분포 무해   경고 없음
#       총량 ≤ 8%, 분포 위험   경고 ("총량은 낮지만 분포가 위험")      ← f60
#       총량 > 8%, 분포 무해   경고 ("총량은 높지만 분포 무해")        ← f6+1536
#       총량 > 8%, 분포 위험   경고 (가장 강한 문구)
#
#   **"위험" 은 경고이지 불합격이 아니다.** 표본이 2건이고 위험 표본은 f60 하나라
#   FAIL 로 올릴 근거가 없다. 표본이 쌓이면 격상을 검토한다.
#
#   높이 밴드(머리/상체/…)는 판정에 쓰지 않는다. 팔이 몸통과 같은 높이에 있어
#   f60 의 "상체 64.6%" 와 f6 의 "상체 29.6%" 가 뜻하는 바가 전혀 다르다.
SCALE_MIN, SCALE_MAX = 0.55, 0.65
IOU_MIN = 0.5
JOINT_DIST_MAX = 0.2
FALLBACK_WARN_PCT = 8.0
UNASSIGNED_MAX = 0
FB_LIMB_MAX_PCT = 35.0
FB_SRC_P90_MAX = 0.04
FB_MIN_VERTS = 1000
DISTAL = ("Wrist", "Hand", "Ankle", "Foot")
DISTAL_DIST_MAX = 0.03
CROSS_MAX_PCT = 10.0
CROSS_MIN_VERTS = 100
DOM_MIN_PCT = 0.01
FAIL_BONES = ("Wrist", "Ankle", "Foot")      # ①∧③ 이 불합격이 되는 본. Hand 는 경고 (위 메모)

THRESHOLD_STATUS = "스케일은 5회 검증, 나머지는 잠정(표본 4건). 폴백 분포·리깅 지표 임계는 표본 5건(불합격 실물 1건). 재보정: 신규 10건 누적 시 / PASS 후 하류 실패 발생 시"


def classify_fallback(detail):
    """폴백 분포를 "benign"(무해) / "risky"(위험) 로 가른다.

    돌려주는 값은 (분류, 사유 목록) 이다. 자료가 없으면 분류가 None, 폴백 정점이
    FB_MIN_VERTS 에 못 미치면 "too_few"(잡음 가드) 다. 근거와 임계의 출처는 위 ④ 메모.
    """
    if not detail or detail.get("verts") is None:
        return None, []
    if detail["verts"] < FB_MIN_VERTS:
        return "too_few", []
    why = []
    limb = detail.get("limb_pct")
    p90 = (detail.get("src_dist") or {}).get("p90")
    if limb is None or p90 is None:
        return None, []
    if limb > FB_LIMB_MAX_PCT:
        why.append(f"사지 본으로 간 폴백 {limb}% > {FB_LIMB_MAX_PCT}%")
    if p90 > FB_SRC_P90_MAX:
        why.append(f"소스거리 p90 {p90} > {FB_SRC_P90_MAX}")
    return ("risky" if why else "benign"), why


def check_rig(rc, detail=None):
    """①②③ 을 판정한다. (불합격 사유, 경고, 기록) 을 돌려준다. 근거는 위 메모."""
    if not rc:
        return [], [], None
    n = rc.get("vertices") or 0
    dist, dom, cross = rc.get("bone_dist", {}), rc.get("dominant", {}), rc.get("cross", {})
    far = {b: d for b, d in dist.items() if b.endswith(DISTAL) and d > DISTAL_DIST_MAX}
    empty = [b for b, c in dom.items() if n and 100.0 * c / n < DOM_MIN_PCT]
    crossed = {b: round(100.0 * c / dom[b], 1) for b, c in cross.items()
               if dom.get(b, 0) >= CROSS_MIN_VERTS and 100.0 * c / dom[b] > CROSS_MAX_PCT}
    both = [b for b in far if b in empty]
    fatal = [b for b in both if b.endswith(FAIL_BONES)]
    reasons, warnings = [], []
    if fatal:
        msg = (f"{' · '.join(fatal)}: 본이 메쉬 밖에 있고(거리 "
               f"{' · '.join(str(far[b]) for b in fatal)} > {DISTAL_DIST_MAX}) 따라올 정점이 없다"
               f"(지배 정점 0) — 이 본이 움직여도 메쉬가 따라오지 않는다")
        # 사라진 정점이 어디로 갔는지 — ④ 폴백 분포를 근거로 붙인다 (수위에는 쓰지 않는다)
        by = (detail or {}).get("by_bone") or {}
        side = {b[:2] for b in fatal}
        limb = [(b, c) for b, c in by.items()
                if b[:2] in side and b.endswith(("Shoulder", "Elbow", "Hip", "Knee"))]
        if limb:
            b, c = max(limb, key=lambda kv: kv[1])
            msg += f". 폴백 {c:,}정점이 {b} 로 갔다"
        reasons.append(msg)
    rest_both = [b for b in both if b not in fatal]
    if rest_both:
        warnings.append(
            f"{' · '.join(rest_both)}: 본이 메쉬 밖이고(거리 "
            f"{' · '.join(str(far[b]) for b in rest_both)}) 지배 정점이 없다 — 손 본은 WHAM 이 "
            f"거의 움직이지 않아 불합격으로 보지 않는다. 손목이 정점을 쥐고 있는지 확인할 것")
    only_far = [b for b in far if b not in both]
    if only_far:
        warnings.append("말단 본이 메쉬에서 멀다: "
                        + ", ".join(f"{b} {far[b]}" for b in only_far)
                        + f" (> {DISTAL_DIST_MAX}) — 정렬을 확인할 것")
    only_empty = [b for b in empty if b not in both]
    if only_empty:
        warnings.append(f"지배 정점이 없는 본: {', '.join(only_empty)} — 그 본이 회전해도 "
                        f"따라올 지오메트리가 없다")
    if crossed:
        warnings.append("좌우 교차 배정: "
                        + ", ".join(f"{b} {p}%" for b, p in sorted(crossed.items(), key=lambda kv: -kv[1]))
                        + f" (> {CROSS_MAX_PCT}%) — 다리·팔이 붙은 메쉬에서 웨이트가 반대편으로 넘어갔다")
    flags = {"far": far, "empty": empty, "crossed": crossed, "fatal": fatal}
    return reasons, warnings, flags


def judge(m):
    reasons, warnings = [], []
    s = m.get("scale")
    if s is None:
        reasons.append("aligned_params.json 에 scale 이 없다")
    elif not (SCALE_MIN <= s <= SCALE_MAX):
        reasons.append(
            f"정렬 스케일 {s} 이 구조 상수 범위 {SCALE_MIN}-{SCALE_MAX} 밖이다 — "
            f"상류(SMPL 생성 또는 TRELLIS 스케일) 오류 신호")
    iou = m.get("bbox_iou")
    if iou is None:
        reasons.append("aligned_params.json 에 bbox_iou 가 없다")
    elif iou < IOU_MIN:
        reasons.append(f"bbox IoU {iou} < {IOU_MIN} — 정렬이 어긋났다")
    jd = m.get("joint_dist")
    if jd is None:
        warnings.append("관절-메쉬 거리가 주어지지 않아 좌표계 판정을 확인하지 못했다")
    elif jd > JOINT_DIST_MAX:
        reasons.append(f"관절-메쉬 거리 {jd} > {JOINT_DIST_MAX} — 좌표계 판정이 틀렸을 수 있다")
    ua = m.get("unassigned_pct")
    if ua is not None and ua > UNASSIGNED_MAX:
        reasons.append(f"웨이트 무배정 {ua}% > {UNASSIGNED_MAX}% — 전이가 끝나지 않았다")
    detail = m.get("fallback_detail")
    r2, w2, flags = check_rig(m.get("rig_check"), detail)
    reasons += r2
    warnings += w2
    m["rig_flags"] = flags
    fb = m.get("fallback_pct")
    cls, why = classify_fallback(detail)
    over = fb is not None and fb > FALLBACK_WARN_PCT
    m["fallback_check"] = {"class": cls, "why": why, "over_warn_pct": over}
    if fb is None:
        warnings.append("직선거리 폴백률이 주어지지 않았다")
    else:
        size = (f"직선거리 폴백 {fb}% 가 {FALLBACK_WARN_PCT}% 를 넘는다" if over
                else f"직선거리 폴백 {fb}% 는 {FALLBACK_WARN_PCT}% 아래다")
        if cls == "risky":
            # 총량과 무관하게 경고한다 — 총량은 품질을 가르지 못한다 (④ 메모).
            warnings.append(
                f"{size} — 분포 위험: {'; '.join(why)}. "
                f"먼 데서 빌린 웨이트가 팔다리에 붙었다 — 포즈 시험 필수")
        elif over and cls == "benign":
            top = ", ".join(f"{b} {c}" for b, c in list(detail.get("by_bone", {}).items())[:3])
            warnings.append(
                f"{size} — 분포 무해: 사지 본 {detail['limb_pct']}%, "
                f"소스거리 p90 {detail['src_dist']['p90']} (상위 본: {top})")
        elif over:
            # 분포 자료가 없거나(None) 정점이 너무 적다(too_few). 조용히 넘기지 않는다.
            warnings.append(f"{size} — 분포를 판정하지 못했다({cls}). 포즈 시험으로 확인할 것")
    return ("FAIL" if reasons else "PASS"), reasons, warnings


def parse_args():
    ap = argparse.ArgumentParser(description="G2r 게이트 — SMPL 정렬·리깅 판정")
    ap.add_argument("--params", required=True, help="aligned_params.json 경로")
    ap.add_argument("--out", required=True, help="판정 결과를 쓸 폴더")
    ap.add_argument("--name", default=None, help="샘플 이름. 기본값: --out 폴더 이름")
    ap.add_argument("--joint-dist", type=float, default=None,
                    help="create_smpl_armature.py 가 찍은 평균 관절-메쉬 거리")
    ap.add_argument("--fallback-pct", type=float, default=None,
                    help="transfer_weights.py 의 직선거리 폴백 비율(%%)")
    ap.add_argument("--unassigned-pct", type=float, default=0.0,
                    help="웨이트 무배정 비율(%%). 기본 0")
    ap.add_argument("--transferred", default=None,
                    help="transferred_params.json 경로. 폴백 분포(fallback_detail)를 읽어 "
                         "총량과 무관하게 판정한다. --fallback-pct 를 생략하면 "
                         "폴백률도 여기서 읽는다")
    return ap.parse_args()


def main():
    a = parse_args()
    out = os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)
    name = a.name or os.path.basename(os.path.normpath(out))
    p = json.load(open(os.path.expanduser(a.params)))
    t = json.load(open(os.path.expanduser(a.transferred))) if a.transferred else {}
    metrics = {
        "scale": p.get("scale"),
        "bbox_iou": p.get("bbox_iou"),
        "joint_dist": a.joint_dist,
        "fallback_pct": a.fallback_pct if a.fallback_pct is not None else t.get("fallback_pct"),
        "unassigned_pct": a.unassigned_pct,
        "rot_x": p.get("rot_x"),
        "fallback_detail": t.get("fallback_detail"),
        "rig_check": t.get("rig_check"),
    }
    verdict, reasons, warnings = judge(metrics)
    result = {
        "gate": "G2r", "version": 1, "name": name, "verdict": verdict,
        "reasons": reasons, "warnings": warnings, "metrics": metrics,
        "thresholds": {
            "scale_min": SCALE_MIN, "scale_max": SCALE_MAX, "iou_min": IOU_MIN,
            "joint_dist_max": JOINT_DIST_MAX, "fallback_warn_pct": FALLBACK_WARN_PCT,
            "unassigned_max": UNASSIGNED_MAX,
            "fb_limb_max_pct": FB_LIMB_MAX_PCT, "fb_src_p90_max": FB_SRC_P90_MAX,
            "fb_min_verts": FB_MIN_VERTS,
            "distal_dist_max": DISTAL_DIST_MAX, "cross_max_pct": CROSS_MAX_PCT,
            "cross_min_verts": CROSS_MIN_VERTS, "dom_min_pct": DOM_MIN_PCT,
            "fail_bones": list(FAIL_BONES),
            "status": THRESHOLD_STATUS,
        },
        "source": {"type": "aligned_params", "path": a.params},
    }
    path = os.path.join(out, "gate_g2r.json")
    with open(path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    mark = "✅" if verdict == "PASS" else "❌"
    print(f"{mark} [{verdict}] {name}  스케일 {metrics['scale']}  IoU {metrics['bbox_iou']}  "
          f"관절거리 {metrics['joint_dist']}  폴백 {metrics['fallback_pct']}%")
    for r in reasons:
        print(f"    사유: {r}")
    for w in warnings:
        print(f"    주의: {w}")
    print(f"    → {path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
