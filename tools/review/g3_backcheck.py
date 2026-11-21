"""G3 역검증 — 미러의 tracking_results.pth 가 있는 클립 전부에 gate_g3.evaluate() 를 돌려 표로 낸다 (읽기 전용).

  python tools/review/g3_backcheck.py --data ~/data --regressor <J_regressor_coco.npy> [--json 결과.json]

tracking_results.pth 를 읽으려면 torch 가 있어야 한다(gate_g3.load_tracking). 맥에는 torch 가 없으므로 별도 venv 를
쓰거나 wham 환경에서 돌린다. 영상 크기는 02_sam2/<클립>/<클립>_masked.mp4 에서 읽는다(opencv).
2026-11-21 결과는 docs/G3_BACKCHECK.md.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import g3_rules as R  # noqa: E402
import gate_g3  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--regressor", required=True)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    import cv2
    import joblib
    import numpy as np
    data = Path(a.data).expanduser()
    reg = np.load(a.regressor)
    out = {}
    for d in sorted((data / "04_wham").glob("*_masked")):
        if not (d / "tracking_results.pth").exists():
            continue
        clip = d.name[:-len("_masked")]
        pkl = d / "wham_output_stitched.pkl" if (d / "wham_output_stitched.pkl").exists() else d / "wham_output.pkl"
        cap = cv2.VideoCapture(str(data / "02_sam2" / clip / f"{clip}_masked.mp4"))
        w, h = cap.get(3), cap.get(4)
        cap.release()
        if not w:
            out[clip] = {"error": "masked.mp4 없음"}
            continue
        v, reasons, rec, _ = gate_g3.evaluate(joblib.load(pkl), gate_g3.load_tracking(d / "tracking_results.pth"),
                                              reg, w, h)
        out[clip] = {"verdict": v, "pkl": pkl.name, "body": rec["body"], "face": rec["face"],
                     "frames_over": rec["frames_over"], "longest_run": rec["longest_run"],
                     "longest_run_start": rec["longest_run_start"], "frame_median_max": rec["frame_median_max"],
                     "check_spans": rec["check_spans"], "frames": rec["frames_track"], "frames_2d": rec["frames_2d"]}
        print(f"{clip:30s} {v:5s} med {rec['body']['median']:.4f} p95 {rec['body']['p95']:.4f} "
              f"pck05 {rec['body']['pck05']:.3f} over {rec['frames_over']:3d} run {rec['longest_run']:3d}", flush=True)
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1))
    n_check = sum(1 for v in out.values() if v.get("verdict") == "CHECK")
    print(f"\n{len(out)}편 · CHECK {n_check} (기준 {R.FRAME_MAX} 초과 연속 ≥ {R.RUN_MIN})")


if __name__ == "__main__":
    main()
