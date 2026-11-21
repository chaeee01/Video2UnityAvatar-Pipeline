"""G3 — 재투영 일관성 (S5 뒤, 외형 · 동작 트랙 공통). 판정은 PASS / CHECK 뿐이고 실행을 멈추지 않는다.

  python gate_g3.py --pkl <04_wham/<샘플>_masked/wham_output.pkl> --tracking <…/tracking_results.pth> \
      --regressor <WHAM/dataset/body_models/J_regressor_coco.npy> --width 1080 --height 1920 --out <폴더> [--name 이름]

무엇을 재고 어떻게 판정하는지 · 기준값 근거 · 한계는 g3_rules.py 독스트링이 원본이다. 요약:
  WHAM 의 SMPL 몸을 WHAM 카메라로 투영한 COCO 17관절 ↔ WHAM 이 입력으로 받은 ViTPose 2D 검출, 사람 키 대비 거리.
  몸 관절 12개의 프레임 중앙값이 0.05 를 넘는 프레임이 5프레임 이상 연속이면 CHECK.
  **자기 일관성 지표다** — 깊이 방향 자세 오류(walker_walk_02 f138 · char_shuffle f60)는 잡지 못한다.
  CHECK 는 WHAM 이 약한 자세 구간(눕기 · 엎드리기 · 기기)을 표시한다. 결과물의 결함은 G4 바닥 판정이 판정한다.

tracking_results.pth 는 WHAM 이 joblib 로 쓴 dict 이고 torch 텐서(features 등)가 섞여 있어 **읽으려면 torch 가 있어야
한다** (wham 환경). 판정이 쓰는 키(frame_id · bbox · keypoints)는 numpy 다. 읽기는 load_tracking() 하나에 모았다.

출력: <out>/gate_g3.json + 표준출력 요약. 종료 코드 0 (PASS · CHECK 모두). 입력을 읽지 못하면 0 이 아니다(오류).
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g3_rules as R  # noqa: E402
from wham_track import pick_track  # noqa: E402


def load_tracking(path):
    """tracking_results.pth → {트랙 키: {frame_id, bbox, keypoints}} (numpy). torch 가 필요한 곳은 여기뿐이다."""
    import joblib
    raw = joblib.load(path)
    return {k: {"frame_id": np.asarray(t["frame_id"]), "bbox": np.asarray(t["bbox"]),
                "keypoints": np.asarray(t["keypoints"])} for k, t in raw.items()}


def match_2d(tracking, frame_ids, uv):
    """프레임마다 2D 검출을 고른다 — 그 프레임의 검출 중 투영과 가장 가까운 것(이어 붙인 트랙은 여러 트랙 키에 걸친다).
    → (keypoints (N,17,3), 키 px (N,), 쓴 프레임 번호 (N,), uv 행 번호 (N,))"""
    by_frame = {}
    for t in tracking.values():
        for i, f in enumerate(t["frame_id"]):
            by_frame.setdefault(int(f), []).append((t["keypoints"][i], float(t["bbox"][i][2]) * 200.0))
    kps, hs, fs, rows = [], [], [], []
    for i, f in enumerate(frame_ids):
        cands = by_frame.get(int(f))
        if not cands:
            continue
        kp, h = min(cands, key=lambda c: float(np.mean(np.linalg.norm(np.asarray(c[0])[:, :2] - uv[i], axis=1))))
        kps.append(kp); hs.append(h); fs.append(int(f)); rows.append(i)
    return np.asarray(kps, np.float64).reshape(-1, 17, 3), np.asarray(hs), np.asarray(fs), np.asarray(rows, int)


def evaluate(wham, tracking, regressor, width, height):
    """WHAM pkl dict · tracking dict · 회귀 행렬 → (판정, 사유, 기록, 프레임 표). 파일 입출력 없음."""
    tid = pick_track(wham)
    t = wham[tid]
    fids = np.asarray(t["frame_ids"])
    uv = R.project(t["verts"], regressor, width, height)
    kp, h, used_f, rows = match_2d(tracking, fids, uv)
    if len(rows) == 0:
        raise RuntimeError("WHAM 트랙의 프레임에 맞는 2D 검출이 하나도 없다 (tracking_results)")
    e, used = R.errors(uv[rows], kp, h)
    verdict, reasons, record, fm = R.judge(e, used, used_f)
    record.update({"track": str(tid), "frames_track": int(len(fids)), "frames_2d": int(len(rows))})
    table = {"frame": [int(f) for f in used_f],
             "body_median": [None if not np.isfinite(v) else round(float(v), 4) for v in fm],
             "face_median": [None if not np.isfinite(v) else round(float(v), 4)
                             for v in R.frame_median(e, used, R.FACE)]}
    return verdict, reasons, record, table


def main():
    ap = argparse.ArgumentParser(description="G3 — 재투영 일관성 (PASS / CHECK)")
    ap.add_argument("--pkl", required=True, help="wham_output.pkl (이어 붙였으면 wham_output_stitched.pkl)")
    ap.add_argument("--tracking", required=True, help="tracking_results.pth (WHAM 2D 검출)")
    ap.add_argument("--regressor", required=True, help="J_regressor_coco.npy (17 × 6890)")
    ap.add_argument("--width", type=float, required=True, help="영상 폭 px (G0 실측)")
    ap.add_argument("--height", type=float, required=True, help="영상 높이 px (G0 실측)")
    ap.add_argument("--out", required=True, help="판정 결과를 쓸 폴더")
    ap.add_argument("--name", default=None, help="샘플 이름. 기본값: --out 폴더 이름")
    a = ap.parse_args()
    import joblib
    os.makedirs(a.out, exist_ok=True)
    name = a.name or os.path.basename(os.path.normpath(a.out))
    wham = joblib.load(os.path.expanduser(a.pkl))
    if not wham:
        raise SystemExit("[오류] WHAM pkl 에 트랙이 없다 — gate_s5 가 먼저 걸렀어야 한다")
    tracking = load_tracking(os.path.expanduser(a.tracking))
    regressor = np.load(os.path.expanduser(a.regressor))
    if regressor.shape[0] != 17:
        raise SystemExit(f"[오류] 회귀 행렬이 COCO 17관절이 아니다: {regressor.shape}")
    verdict, reasons, record, table = evaluate(wham, tracking, regressor, a.width, a.height)
    result = {
        "gate": "G3", "version": 1, "name": name, "verdict": verdict, "reasons": reasons, "warnings": [],
        "metrics": record,
        "frames": table,
        "thresholds": {"frame_max": R.FRAME_MAX, "run_min": R.RUN_MIN, "conf_min": R.CONF_MIN,
                       "joints": "몸 12 (얼굴 5 제외 — 따로 기록)", "status": R.STATUS},
        "limits": ["WHAM 입력과 같은 2D 검출에 대한 자기 일관성 — 깊이 방향 자세 오류는 잡지 못한다",
                   "CHECK = WHAM 이 약한 자세 구간(눕기 · 엎드리기 · 기기). 결과물 결함은 G4 바닥 판정"],
        "source": {"pkl": a.pkl, "tracking": a.tracking, "regressor": a.regressor,
                   "camera": {"width": a.width, "height": a.height,
                              "focal": round((a.width ** 2 + a.height ** 2) ** 0.5, 3)}},
    }
    path = os.path.join(a.out, "gate_g3.json")
    with open(path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    b = record["body"]
    mark = "✅" if verdict == "PASS" else "⚠️ "
    print(f"{mark} [{verdict}] {name}  몸 관절 오차 중앙 {b['median']} · p95 {b['p95']} · PCK@0.05 {b['pck05']}"
          f"  {R.FRAME_MAX} 초과 {record['frames_over']}프레임 (최장 연속 {record['longest_run']})"
          f"  2D {record['frames_2d']}/{record['frames_track']}프레임")
    for r in reasons:
        print(f"    사유: {r}")
    print(f"    → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
