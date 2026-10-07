"""G2r 게이트: SMPL 정렬·리깅 결과를 판정한다.

align_smpl_to_trellis.py 의 aligned_params.json 과 transfer_weights.py 의 로그를
읽어 리깅 사슬이 제대로 붙었는지 본다. 세 지표 모두 기존 RUNBOOK 5-2·5-3·5-4 의
확인 포인트를 그대로 옮긴 것이다 — 사람이 눈으로 보던 수치를 게이트로 만든다.

  python gate_g2r.py --params ~/data/06_rig/<샘플>/aligned_params.json --out <폴더>
  python gate_g2r.py --params ... --joint-dist 0.0293 --fallback-pct 3.67 --out <폴더>
  python gate_g2r.py --params ... --transferred <transferred_params.json> --out <폴더>

--transferred 를 주면 폴백 분포(fallback_detail)를 읽어 **폴백 총량과 무관하게**
분포를 판정한다. 위험 분류면 총량이 경고선 아래여도 경고한다.

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
#   **다음 작업 — 게이트 코드화.** 수동 측정이 2회 쌓였다(10/1 f60, 10/6 f6+1536):
#   ① 은 배수가 아니라 절댓값으로 봐야 한다(f6 도 배수는 6~8배지만 전부 0.01 이하,
#   f60 은 L_Hand 0.0852). ② f60 L_Ankle 38.3% / f6 최대 L_Hip 1.5%. ③ f60 2개 /
#   f6 없음. f60 을 불합격시키는 것은 아래 ④(경고)가 아니라 이 셋의 몫이다.
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
#     FB_LIMB_MAX_PCT = 20.0    사지 본(어깨·팔꿈치·손목·손·엉덩이·무릎·발목·발)
#                               으로 간 폴백 비율. 1.84 와 47.53 사이.
#     FB_SRC_P90_MAX  = 0.04    웨이트를 빌려 온 거리의 p90 (정렬 공간, 신장 약 1.0).
#                               0.0229 와 0.0606 사이. 1차 전이 반경 0.08 의 절반.
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
FB_LIMB_MAX_PCT = 20.0
FB_SRC_P90_MAX = 0.04
FB_MIN_VERTS = 1000

THRESHOLD_STATUS = "스케일은 5회 검증, 나머지는 잠정(표본 4건). 폴백 분포 임계는 표본 2건. 재보정: 신규 10건 누적 시 / PASS 후 하류 실패 발생 시"


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
    fb = m.get("fallback_pct")
    detail = m.get("fallback_detail")
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
