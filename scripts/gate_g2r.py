"""G2r 게이트: SMPL 정렬·리깅 결과를 판정한다.

align_smpl_to_trellis.py 의 aligned_params.json 과 transfer_weights.py 의 로그를
읽어 리깅 사슬이 제대로 붙었는지 본다. 세 지표 모두 기존 RUNBOOK 5-2·5-3·5-4 의
확인 포인트를 그대로 옮긴 것이다 — 사람이 눈으로 보던 수치를 게이트로 만든다.

  python gate_g2r.py --params ~/data/06_rig/<샘플>/aligned_params.json --out <폴더>
  python gate_g2r.py --params ... --joint-dist 0.0293 --fallback-pct 3.67 --out <폴더>

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
#   실측 1.49%(512) / 3.67%(1024) 이고 둘 다 포즈 시험을 통과했다. 상한의 근거가
#   약해 불합격이 아니라 경고로 둔다 — 8%는 1024 실측의 두 배를 조금 넘는 값이다.
SCALE_MIN, SCALE_MAX = 0.55, 0.65
IOU_MIN = 0.5
JOINT_DIST_MAX = 0.2
FALLBACK_WARN_PCT = 8.0
UNASSIGNED_MAX = 0

THRESHOLD_STATUS = "스케일은 5회 검증, 나머지는 잠정(표본 4건). 재보정: 신규 10건 누적 시 / PASS 후 하류 실패 발생 시"


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
    if fb is None:
        warnings.append("직선거리 폴백률이 주어지지 않았다")
    elif fb > FALLBACK_WARN_PCT:
        warnings.append(
            f"직선거리 폴백 {fb}% 가 {FALLBACK_WARN_PCT}% 를 넘는다 — 포즈 시험으로 확인할 것")
    return ("FAIL" if reasons else "PASS"), reasons, warnings


def parse_args():
    ap = argparse.ArgumentParser(description="G2r 게이트 — SMPL 정렬·리깅 판정")
    ap.add_argument("--params", required=True, help="aligned_params.json 경로")
    ap.add_argument("--out", required=True, help="판정 결과를 쓸 폴더")
    ap.add_argument("--name", default=None, help="샘플 이름. 기본값: --out 폴더 이름")
    ap.add_argument("--joint-dist", type=float, default=None,
                    help="create_smpl_armature.py 가 찍은 평균 관절-메쉬 거리")
    ap.add_argument("--fallback-pct", type=float, default=None,
                    help="transfer_weights.py 의 직선거리 폴백 비율(%)")
    ap.add_argument("--unassigned-pct", type=float, default=0.0,
                    help="웨이트 무배정 비율(%). 기본 0")
    return ap.parse_args()


def main():
    a = parse_args()
    out = os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)
    name = a.name or os.path.basename(os.path.normpath(out))
    p = json.load(open(os.path.expanduser(a.params)))
    metrics = {
        "scale": p.get("scale"),
        "bbox_iou": p.get("bbox_iou"),
        "joint_dist": a.joint_dist,
        "fallback_pct": a.fallback_pct,
        "unassigned_pct": a.unassigned_pct,
        "rot_x": p.get("rot_x"),
    }
    verdict, reasons, warnings = judge(metrics)
    result = {
        "gate": "G2r", "version": 1, "name": name, "verdict": verdict,
        "reasons": reasons, "warnings": warnings, "metrics": metrics,
        "thresholds": {
            "scale_min": SCALE_MIN, "scale_max": SCALE_MAX, "iou_min": IOU_MIN,
            "joint_dist_max": JOINT_DIST_MAX, "fallback_warn_pct": FALLBACK_WARN_PCT,
            "unassigned_max": UNASSIGNED_MAX, "status": THRESHOLD_STATUS,
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
