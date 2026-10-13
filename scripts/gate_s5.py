"""S5 게이트: WHAM 이 클립 전체를 한 사람으로 끊김 없이 추적했는지 판정한다.

  python gate_s5.py --pkl ~/data/04_wham/<샘플>_masked/wham_output.pkl --frames 192 --out <폴더>

동작의 **품질**(재투영 오차 · 발 접지)은 보지 않는다 — 그것은 G3 의 몫이고 아직 없다.
여기서는 "동작 데이터가 클립 전체에 대해 있기는 한가" 만 본다.

배경 (2026-10-12): listener_walk_fwd 에서 S2 가 바지만 잡았고, 그 마스크로 WHAM 은
34 · 54 · 65프레임짜리 트랙 셋을 냈다(192프레임 중 합쳐서 153). 그때의 검사는 "트랙이 1개
이상인가" 뿐이라 통과했고, 하류는 첫 트랙(34프레임)을 썼을 것이다.

출력: <out>/gate_s5.json + 표준출력 요약. 종료 코드 0 PASS / 1 FAIL.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wham_track import frame_gaps, pick_track, track_lengths  # noqa: E402

# 고른 트랙이 클립 프레임의 이 비율 이상을 덮어야 한다.
#   2026-10-12 실측: 정상 10건(walker 7 · stalker · listener 전신 마스크 등)은 전부 100%,
#   불량 1건은 가장 긴 트랙이 33.9%(65/192), 첫 트랙이 17.7%(34/192).
#   95% 는 "앞뒤 몇 프레임을 놓친 정도" 만 허용한다 — 192프레임에서 9프레임.
#   **잠정이다 (불량 표본 1건).** 재보정: PASS 뒤 하류 실패 시.
COVERAGE_MIN = 0.95


def judge(lengths, chosen, gaps, expected_frames):
    """트랙 길이 표 → (PASS/FAIL, 사유, 주의). 순수 함수."""
    reasons, warnings = [], []
    n = lengths[chosen]
    cov = n / expected_frames if expected_frames else None
    if cov is not None and cov < COVERAGE_MIN:
        reasons.append(
            f"고른 트랙이 {n}/{expected_frames}프레임({100 * cov:.1f}%) < {100 * COVERAGE_MIN:.0f}% "
            f"— 추적이 끊겼다. 마스크가 몸 전체를 담았는지(S2) 확인할 것")
    if gaps:
        reasons.append(f"고른 트랙 안에서 프레임 번호가 {gaps}번 건너뛴다 — 추적이 끊겼다")
    if len(lengths) > 1:
        others = {str(k): v for k, v in lengths.items() if k != chosen}
        warnings.append(f"트랙이 {len(lengths)}개다 — 가장 긴 것({chosen}, {n}프레임)을 쓴다. "
                        f"나머지: {others}")
    return ("FAIL" if reasons else "PASS"), reasons, warnings


def main():
    ap = argparse.ArgumentParser(description="S5 게이트 — WHAM 트랙 연속성 판정")
    ap.add_argument("--pkl", required=True, help="wham_output.pkl")
    ap.add_argument("--frames", type=int, required=True, help="클립 프레임 수 (G0 실측)")
    ap.add_argument("--out", required=True, help="판정 결과를 쓸 폴더")
    ap.add_argument("--name", default=None, help="샘플 이름. 기본값: --out 폴더 이름")
    a = ap.parse_args()
    import joblib
    os.makedirs(a.out, exist_ok=True)
    name = a.name or os.path.basename(os.path.normpath(a.out))
    data = joblib.load(os.path.expanduser(a.pkl))
    if not data:
        verdict, reasons, warnings = "FAIL", ["WHAM 이 사람을 하나도 추적하지 못했다 (트랙 0개)"], []
        lengths, chosen, gaps = {}, None, 0
    else:
        lengths = track_lengths(data)
        chosen = pick_track(data)
        gaps = frame_gaps(data[chosen]["frame_ids"])
        verdict, reasons, warnings = judge(lengths, chosen, gaps, a.frames)
    stitch = None
    if os.path.basename(a.pkl) == "wham_output_stitched.pkl":
        # 이어 붙인 pkl 이다. 통과해도 사람이 이음매를 볼 수 있게 남긴다.
        sj = os.path.join(os.path.dirname(os.path.expanduser(a.pkl)), "stitch.json")
        stitch = json.load(open(sj)) if os.path.exists(sj) else {"seams": []}
        warnings.append("이어 붙인 트랙이다 — " + ", ".join(
            f"f{s['after']}→f{s['before']} 공백 {s['gap']}프레임 · 이음매 튐 {s['jump']}배"
            for s in stitch.get("seams", [])) + ". 재생 영상에서 그 프레임을 확인할 것")
    n = lengths.get(chosen, 0)
    result = {
        "gate": "S5", "version": 1, "name": name, "verdict": verdict,
        "reasons": reasons, "warnings": warnings,
        "metrics": {"tracks": {str(k): v for k, v in lengths.items()},
                    "chosen": None if chosen is None else str(chosen),
                    "chosen_frames": n, "frames_expected": a.frames,
                    "coverage": round(n / a.frames, 4) if a.frames else None,
                    "gaps": gaps, "stitch": stitch},
        "thresholds": {"coverage_min": COVERAGE_MIN,
                       "status": "잠정 (불량 표본 1건). 재보정: PASS 후 하류 실패 발생 시"},
        "source": {"pkl": a.pkl},
    }
    path = os.path.join(a.out, "gate_s5.json")
    with open(path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    mark = "✅" if verdict == "PASS" else "❌"
    print(f"{mark} [{verdict}] {name}  트랙 {len(lengths)}개  고른 트랙 {n}/{a.frames}프레임  끊김 {gaps}")
    for r in reasons:
        print(f"    사유: {r}")
    for w in warnings:
        print(f"    주의: {w}")
    print(f"    → {path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
