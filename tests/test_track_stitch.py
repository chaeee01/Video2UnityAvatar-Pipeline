"""WHAM 트랙 이어 붙이기 (stitch_wham_tracks.py) — 좁은 조건에서만 잇고 그 밖은 건드리지 않는지.

합성 트랙으로 조건 판정 · 보간 · 입력 불변을 본다. 실물(listener_roar_02 는 이어지고
stalker_run_02 는 거부된다)은 미러에 pkl 이 있을 때만 돈다.
"""
import copy
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import gate_s5
import stitch_wham_tracks as st
import wham_track

OK = []


def check(name, cond, detail=""):
    OK.append(bool(cond))
    print(f"{'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))


def track(a, b, phase=0.0, betas=0.0, speed=0.02):
    """프레임 a..b-1 의 매끄러운 합성 트랙 — 모든 관절이 프레임마다 speed 라디안씩 돈다."""
    n = b - a
    f = np.arange(a, b, dtype=np.float32)
    pose = np.zeros((n, 24, 3), np.float32)
    pose[:, :, 0] = (f * speed + phase)[:, None]
    return {"frame_ids": np.arange(a, b, dtype=np.int64), "pose": pose.reshape(n, 72),
            "pose_world": pose.reshape(n, 72).copy(), "trans": np.stack([f * 0.01, f * 0, f * 0], 1).astype(np.float32),
            "trans_world": np.zeros((n, 3), np.float32), "betas": np.full((n, 10), betas, np.float32),
            "verts": np.zeros((n, 8, 3), np.float32) + f[:, None, None]}


def test_plan():
    ok, why, rec = st.plan({0: track(0, 192)}, 192)
    check("A1 트랙 하나 — 이을 것이 없다", not ok and "하나" in why)
    for gap, want in ((1, True), (3, True), (4, False)):
        d = {0: track(0, 40), 1: track(40 + gap, 192)}
        ok, why, rec = st.plan(d, 192)
        check(f"A2 공백 {gap}프레임 → {'잇는다' if want else '거부'}", ok == want, why or str(rec["seams"]))
    ok, why, _ = st.plan({0: track(0, 50), 1: track(45, 192)}, 192)
    check("A3 겹치는 트랙은 거부 (두 사람 · 중복 추적)", not ok and "겹친다" in why, why)
    ok, why, _ = st.plan({0: track(0, 40), 1: track(41, 170)}, 192)
    check("A4 이어도 95% 미만이면 거부", not ok and "95%" in why, why)
    ok, why, rec = st.plan({0: track(0, 40), 1: track(41, 192, phase=0.35)}, 192)
    check("A5 이음매에서 자세가 튀면 거부 (주변의 3배 초과)", not ok and "튄다" in why, why)
    ok, why, rec = st.plan({0: track(0, 40), 1: track(41, 192, phase=0.03)}, 192)
    check("A6 조금 튀는 것(3배 이하)은 통과", ok and 1.0 < rec["seams"][0]["jump"] <= 3.0, str(rec["seams"]))
    ok, why, _ = st.plan({5: track(41, 192), 2: track(0, 40)}, 192)
    check("A7 트랙 키의 순서가 아니라 시작 프레임 순으로 본다", ok, why)
    ok, why, _ = st.plan({0: track(0, 30), 1: track(31, 60), 2: track(62, 192)}, 192)
    check("A8 세 트랙도 공백이 모두 작으면 잇는다", ok, why)


def test_stitch():
    d = {0: track(0, 40, betas=1.0), 1: track(42, 192, betas=2.0)}
    before = copy.deepcopy(d)
    ok, why, rec = st.plan(d, 192)
    m = st.stitch(d, rec)
    t = next(iter(m.values()))
    check("B1 한 트랙 192프레임, 번호가 이어진다", len(m) == 1 and list(t["frame_ids"]) == list(range(192)))
    full = track(0, 192)
    err = float(np.abs(t["pose"] - full["pose"]).max())
    check("B2 빈 프레임의 회전은 구면 보간 — 등속 회전이면 원래 값과 같다", err < 1e-4, f"최대 오차 {err:.2e}")
    check("B3 위치 · 정점은 선형 보간", np.allclose(t["trans"], full["trans"], atol=1e-5) and np.allclose(t["verts"], full["verts"], atol=1e-4))
    check("B4 체형은 가장 긴 트랙의 것 하나로", np.allclose(t["betas"], 2.0) and t["betas"].shape == (192, 10))
    check("B5 필드의 자료형을 지킨다", t["pose"].dtype == np.float32 and t["frame_ids"].dtype == np.int64)
    same = all(np.array_equal(d[k][f], before[k][f]) for k in d for f in d[k])
    check("B6 입력 dict 는 바뀌지 않는다", same)
    lens = wham_track.track_lengths(m)
    v, r, w = gate_s5.judge(lens, wham_track.pick_track(m), wham_track.frame_gaps(t["frame_ids"]), 192)
    check("B7 이은 것은 gate_s5 를 통과한다", v == "PASS" and not w, str(r))
    v, r, w = gate_s5.judge(wham_track.track_lengths(d), wham_track.pick_track(d), 0, 192)
    check("B8 (대조) 잇기 전에는 불합격", v == "FAIL")


def test_real():
    import joblib
    H = os.path.expanduser("~/data/04_wham")
    a, b = f"{H}/listener_roar_02_masked/wham_output.pkl", f"{H}/stalker_run_02_masked/wham_output.pkl"
    if not os.path.exists(a):
        print("⚠️  미러에 listener_roar_02 pkl 이 없어 실물 시험을 건너뛴다")
        return
    d = joblib.load(a)
    ok, why, rec = st.plan(d, 192)
    s = rec["seams"][0]
    check("C1 listener_roar_02 — 이어진다 (f37→f39, 공백 1, 튐 3배 이하)",
          ok and (s["after"], s["before"], s["gap"]) == (37, 39, 1) and s["jump"] <= st.JUMP_MAX, str(rec.get("seams")))
    t = next(iter(st.stitch(d, rec).values()))
    check("C2 이은 결과 192프레임 · 원본 구간은 그대로", len(t["frame_ids"]) == 192
          and np.array_equal(t["pose"][:38], d[0]["pose"]) and np.array_equal(t["pose"][39:], d[1]["pose"]))
    # stalker_run_02 는 두 번 받았다. 10/13 새벽분(공백 17프레임)은 _prev_fail_1013/ 로 옮겨 뒀고,
    # 낮의 재생성분(공백 1프레임)이 제자리에 있다.
    old = f"{H}/stalker_run_02_masked/_prev_fail_1013/wham_output.pkl"
    if os.path.exists(old):
        ok, why, _ = st.plan(joblib.load(old), 192)
        check("C3 stalker_run_02 새벽 불합격분 — 거부 (공백 17프레임)", not ok and "17프레임" in why, why)
    else:
        print("⚠️  stalker_run_02 새벽 불합격분 pkl 이 없어 C3 을 건너뛴다")
    if os.path.exists(b):
        d2 = joblib.load(b)
        ok, why, rec = st.plan(d2, 192)
        s2 = rec.get("seams", [{}])[0]
        check("C4 stalker_run_02 재생성분 — 이어진다 (f43→f45, 공백 1)",
              ok and (s2.get("after"), s2.get("before"), s2.get("gap")) == (43, 45, 1), why or str(rec.get("seams")))

if __name__ == "__main__":
    test_plan()
    test_stitch()
    test_real()
    print(f"\n{'✅ 전체 통과' if all(OK) else '❌ 실패 있음'} ({sum(OK)}/{len(OK)})")
    sys.exit(0 if all(OK) else 1)
