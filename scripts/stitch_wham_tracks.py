"""S5 보조: 한 사람짜리 클립에서 WHAM 트랙이 잠깐 끊겨 둘로 갈린 것을 이어 붙인다.

  python stitch_wham_tracks.py --pkl <.../wham_output.pkl> --video <마스킹 클립>     # 또는 --frames N

WHAM 은 사람을 한 프레임만 놓쳐도 트랙을 새로 만든다. 2026-10-13 에 listener_roar_02 가
f38 한 프레임에서 끊겨 f0~37 · f39~191 두 트랙이 됐고(팔을 빠르게 휘두르는 구간), gate_s5 가
"가장 긴 트랙 79.7%" 로 불합격시켰다. 동작 데이터는 191/192 프레임이 멀쩡하다.

**좁게만 고친다.** 아래를 모두 만족할 때만 잇고, 하나라도 어긋나면 아무것도 쓰지 않는다
(그 pkl 은 그대로 gate_s5 로 가서 불합격한다):
  - 트랙들이 시간순으로 겹치지 않는다
  - 트랙 사이의 공백이 모두 MAX_GAP(3)프레임 이하다
  - 이은 뒤 클립 프레임의 COVERAGE_MIN(95%) 이상을 덮는다
  - 이음매에서 자세가 튀지 않는다 — 이음매 양쪽의 관절 회전차가 주변의 같은 간격 변화의
    JUMP_MAX(3)배 이하

원본 pkl 은 건드리지 않는다. 이은 것은 옆에 wham_output_stitched.pkl 로, 무엇을 했는지는
stitch.json 으로 쓴다. 오케스트레이터와 gate_s5 는 stitched 가 있으면 그것을 쓴다.

빈 프레임은 관절 회전을 구면 보간(slerp), 위치 · 정점을 선형 보간으로 채운다. 체형(betas)은
가장 긴 트랙의 것을 전체에 쓴다 — 리그와 신장비가 한 값을 쓰기 때문이다.
월드 좌표(pose_world · trans_world)도 같은 식으로 채우지만 **트랙마다 원점이 달라 이은 뒤
연속이 아니다.** 하류(5-1 · 5-5 · G1a)는 카메라 좌표만 쓴다.

종료 코드: 0 이었다 또는 이을 필요가 없다(트랙 1개) · 3 조건에 맞지 않아 잇지 않았다 · 1 오류.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

MAX_GAP = 3
COVERAGE_MIN = 0.95
# 이음매 튐 상한. 2026-10-13 실측: listener_roar_02 의 이음매(2프레임 간격)는 관절 평균 9.93°,
# 그 앞 10프레임의 2프레임 간격 변화는 평균 3.96° — 2.5배. 그것은 통과시키고 그 이상은 막는
# 값이다. **표본 1건 기준 잠정.**
JUMP_MAX = 3.0
JUMP_WINDOW = 10          # 이음매 양쪽에서 "주변" 으로 보는 프레임 수
EXIT_NOT_APPLICABLE = 3
PER_FRAME = ("pose", "trans", "pose_world", "trans_world", "betas", "verts")


def _R(aa):
    return cv2.Rodrigues(np.asarray(aa, dtype=np.float64).reshape(3, 1))[0]


def _aa(R):
    return cv2.Rodrigues(R)[0].reshape(3)


def geodesic_deg(a, b):
    return float(np.degrees(np.arccos(np.clip((np.trace(_R(a).T @ _R(b)) - 1) / 2, -1, 1))))


def pose_diff_deg(pa, pb):
    """두 프레임(72,)의 관절 회전차 평균(도). 루트(0번)는 뺀다 — 몸 전체의 방향은 따로 본다."""
    pa, pb = np.asarray(pa).reshape(24, 3), np.asarray(pb).reshape(24, 3)
    return float(np.mean([geodesic_deg(pa[j], pb[j]) for j in range(1, 24)]))


def slerp_pose(pa, pb, t):
    """axis-angle 자세(72,) 두 개 사이를 t(0~1)에서 구면 보간한다."""
    pa, pb = np.asarray(pa, dtype=np.float64).reshape(24, 3), np.asarray(pb, dtype=np.float64).reshape(24, 3)
    out = np.empty((24, 3))
    for j in range(24):
        Ra = _R(pa[j])
        out[j] = _aa(Ra @ _R(t * _aa(Ra.T @ _R(pb[j]))))
    return out.reshape(72)


def plan(data, n_frames):
    """이을 수 있는가. (ok, 사유, 기록) — 순수 함수라 tests/ 에서 dict 로 시험한다."""
    rec = {"tracks": {str(k): [int(t["frame_ids"][0]), int(t["frame_ids"][-1]), len(t["frame_ids"])]
                      for k, t in data.items()}, "frames": n_frames}
    if len(data) < 2:
        return False, "트랙이 하나다 — 이을 것이 없다", rec
    order = sorted(data, key=lambda k: int(data[k]["frame_ids"][0]))
    rec["order"] = [str(k) for k in order]
    for k in order:
        ids = np.asarray(data[k]["frame_ids"], dtype=np.int64)
        if np.any(np.diff(ids) != 1):
            return False, f"트랙 {k} 안에서 프레임 번호가 건너뛴다", rec
    seams = []
    for a, b in zip(order, order[1:]):
        ea, sb = int(data[a]["frame_ids"][-1]), int(data[b]["frame_ids"][0])
        gap = sb - ea - 1
        if gap < 0:
            return False, f"트랙 {a} 와 {b} 가 겹친다 (f{ea} ≥ f{sb}) — 두 사람이거나 중복 추적이다", rec
        span = gap + 1
        pa, pb = np.asarray(data[a]["pose"]), np.asarray(data[b]["pose"])
        seam = pose_diff_deg(pa[-1], pb[0])
        near = [pose_diff_deg(p[i], p[i + span]) for p in (pa[-JUMP_WINDOW - span:], pb[:JUMP_WINDOW + span])
                for i in range(len(p) - span)]
        ref = float(np.mean(near)) if near else 0.0
        seams.append({"after": ea, "before": sb, "gap": gap, "seam_deg": round(seam, 2),
                      "near_deg": round(ref, 2), "jump": round(seam / ref, 2) if ref > 1e-6 else None})
    rec["seams"] = seams
    big = [s for s in seams if s["gap"] > MAX_GAP]
    if big:
        return False, (f"공백이 {MAX_GAP}프레임을 넘는다: " +
                       ", ".join(f"f{s['after']}→f{s['before']} ({s['gap']}프레임)" for s in big)), rec
    covered = sum(len(data[k]["frame_ids"]) for k in order) + sum(s["gap"] for s in seams)
    rec["covered"] = covered
    if n_frames and covered / n_frames < COVERAGE_MIN:
        return False, f"이어도 {covered}/{n_frames}프레임({100 * covered / n_frames:.1f}%) < {100 * COVERAGE_MIN:.0f}%", rec
    wild = [s for s in seams if s["jump"] is None or s["jump"] > JUMP_MAX]
    if wild:
        return False, ("이음매에서 자세가 튄다: " +
                       ", ".join(f"f{s['after']}→f{s['before']} 주변의 {s['jump']}배 (> {JUMP_MAX})" for s in wild)), rec
    return True, "", rec


def stitch(data, rec):
    """plan 이 허락한 트랙들을 하나로 잇는다. 입력은 바꾸지 않는다."""
    order = [k for k in sorted(data, key=lambda k: int(data[k]["frame_ids"][0]))]
    longest = max(order, key=lambda k: len(data[k]["frame_ids"]))
    keys = [f for f in PER_FRAME if all(f in data[k] for k in order)]
    out = {f: [np.asarray(data[order[0]][f])] for f in keys}
    ids = [np.asarray(data[order[0]]["frame_ids"], dtype=np.int64)]
    for a, b in zip(order, order[1:]):
        ea, sb = int(data[a]["frame_ids"][-1]), int(data[b]["frame_ids"][0])
        gap = sb - ea - 1
        for g in range(1, gap + 1):
            t = g / (gap + 1)
            for f in keys:
                va, vb = np.asarray(data[a][f])[-1], np.asarray(data[b][f])[0]
                v = slerp_pose(va, vb, t) if f in ("pose", "pose_world") else (1 - t) * va + t * vb
                out[f].append(np.asarray(v, dtype=np.asarray(data[a][f]).dtype)[None])
        if gap:
            ids.append(np.arange(ea + 1, sb, dtype=np.int64))
        for f in keys:
            out[f].append(np.asarray(data[b][f]))
        ids.append(np.asarray(data[b]["frame_ids"], dtype=np.int64))
    merged = {f: np.concatenate(out[f], axis=0) for f in keys}
    merged["frame_ids"] = np.concatenate(ids)
    if "betas" in merged:                       # 체형은 가장 긴 트랙의 평균 하나로
        merged["betas"] = np.repeat(np.asarray(data[longest]["betas"]).mean(axis=0, keepdims=True),
                                    len(merged["frame_ids"]), axis=0).astype(np.asarray(data[longest]["betas"]).dtype)
    for f in data[longest]:                     # 프레임별이 아닌 나머지 필드는 가장 긴 트랙의 것
        merged.setdefault(f, data[longest][f])
    return {order[0]: merged}


def count_frames(video):
    cap = cv2.VideoCapture(video)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    if n <= 0:
        raise RuntimeError(f"프레임 수를 읽지 못했다: {video}")
    return n


def main():
    ap = argparse.ArgumentParser(description="WHAM 트랙 이어 붙이기 (공백 3프레임 이하만)")
    ap.add_argument("--pkl", required=True, help="wham_output.pkl (바꾸지 않는다)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--frames", type=int, help="클립 프레임 수")
    g.add_argument("--video", help="프레임 수를 셀 영상")
    a = ap.parse_args()
    import joblib
    pkl = os.path.expanduser(a.pkl)
    out_pkl = os.path.join(os.path.dirname(pkl), "wham_output_stitched.pkl")
    out_json = os.path.join(os.path.dirname(pkl), "stitch.json")
    for stale in (out_pkl, out_json):           # 이전 실행의 결과가 이번 판정처럼 보이지 않게
        if os.path.exists(stale):
            os.replace(stale, stale + ".prev")
    data = joblib.load(pkl)
    n = a.frames or count_frames(os.path.expanduser(a.video))
    ok, why, rec = plan(data, n)
    rec.update({"stitched": ok, "reason": why, "source": pkl,
                "limits": {"max_gap": MAX_GAP, "coverage_min": COVERAGE_MIN, "jump_max": JUMP_MAX}})
    if not ok:
        if len(data) < 2:
            print(f"이어 붙이기: 필요 없음 (트랙 {len(data)}개)")
            return 0
        json.dump(rec, open(out_json, "w"), ensure_ascii=False, indent=1)
        print(f"이어 붙이기: 하지 않음 — {why}")
        return EXIT_NOT_APPLICABLE
    merged = stitch(data, rec)
    joblib.dump(merged, out_pkl)
    rec["out"] = out_pkl
    json.dump(rec, open(out_json, "w"), ensure_ascii=False, indent=1)
    t = next(iter(merged.values()))
    print(f"이어 붙이기: 트랙 {len(data)}개 → 1개, {len(t['frame_ids'])}/{n}프레임. " +
          ", ".join(f"f{s['after']}→f{s['before']} 공백 {s['gap']} · 튐 {s['jump']}배" for s in rec["seams"]))
    print(f"  → {out_pkl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
