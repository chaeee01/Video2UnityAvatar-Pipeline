"""G1a 시선 항 · 가드 off 판정 · 키프레임 내보내기 시험.

임계(GAZE_OK 30 / GAZE_BAD 50 / LEG_MOTION_MIN 15)를 확정한 2026-10-08 의 6샘플
실측을 고정한다. 임계를 움직이면 여기가 먼저 깨진다.

시험지: 미러의 마스크(char_shuffle 은 PNG, 4종은 마스킹 클립 복원)와 WHAM pkl.
zombie1 은 마스크가 미러에 없어 candidates.json 의 점수만 쓴다 (다리 항 없이).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import select_keyframes as sk

H = os.path.expanduser("~/data")
SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "select_keyframes.py")

# (재선정 top5, 다리 항 상태, 가드 off 판정, 다리 움직임)  — 2026-10-08 실측
EXPECT = {
    "char_shuffle":   ([6, 41, 86, 144, 109],     "on",            "ok",        106.8),
    "zombie_walker":  ([80, 164, 117, 139, 222],  "on",            "ok",        11.2),
    "zombie_stalker": ([225, 201, 163, 119, 91],  "off_no_signal", "ok_static", 10.4),
    "zombie_dog":     ([2, 234, 197, 177, 82],    "on",            "ok",        39.3),
    "zombie1":        ([228, 48, 128, 182, 0],    None,            None,        38.6),
}
# 실제로 채택해 결과가 좋았던 프레임은 감점이 없거나 가벼워야 하고, f60 은 바닥이어야 한다.
ADOPTED = {"char_shuffle": (6, 1.0), "zombie_stalker": (162, 1.0), "zombie_walker": (222, 1.0),
           "zombie1": (228, 1.0), "zombie_dog": (0, 0.9)}


def pkl(name):
    return f"{H}/04_wham/{name}_masked/wham_output.pkl"


def masks(name):
    import cv2
    if name == "char_shuffle":
        d = f"{H}/02_sam2/char_shuffle/masks"
        for f in sorted(os.listdir(d)):
            if f.endswith(".png"):
                yield int(f[:-4]), cv2.imread(f"{d}/{f}", cv2.IMREAD_GRAYSCALE) > 127
        return
    cam = cv2.VideoCapture(f"{H}/02_sam2/_masked_0910/{name}_masked.mp4")
    n = 0
    while True:
        got, fr = cam.read()
        if not got:
            break
        yield n, (fr.max(axis=2) > 8)
        n += 1
    cam.release()


def scores_for(name):
    if name == "zombie1":
        d = json.load(open(f"{H}/02_sam2/zombie1/keyframes/candidates.json"))["all"]
        return [dict(x) for x in d], False
    out = []
    for i, m in masks(name):
        s, bbox = sk.keyframe_score(m)
        out.append({"frame": i, "score": round(float(s), 4), "bbox": bbox,
                    "leg_gap": round(sk.leg_gap_ratio(m), 4)})
    return out, True


def main():
    ok, skipped = True, 0

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")

    print("── A. 6샘플 재선정 회귀 (다리 항 + 시선 항)")
    for name, (want, want_leg, want_legs, want_motion) in EXPECT.items():
        if not os.path.exists(pkl(name)):
            print(f"   {name}: 미러에 pkl 없음 — 건너뜀")
            skipped += 1
            continue
        fids, pose = sk.load_wham_track(pkl(name))
        gaze = {f: sk.gaze_offaxis_deg(p) for f, p in zip(fids, pose)}
        motion = round(sk.leg_motion_deg(pose), 1)
        sc, has_leg = scores_for(name)
        usable = [s for s in sc if s["frame"] in gaze and s["bbox"]]
        for s in usable:
            s["gaze_offaxis"] = gaze[s["frame"]]
        leg_state = sk.apply_leg_term(usable)[0] if has_leg else None
        sk.apply_gaze_term(usable)
        got = [s["frame"] for s in sk.pick_keyframes(usable, 5, 20)]
        legs = sk.judge_closed_legs(leg_state, motion)[0] if has_leg else None
        good = (got == want and leg_state == want_leg and legs == want_legs
                and abs(motion - want_motion) < 0.15)
        check(f"{name:15s} top5 {got}  다리 항 {leg_state}  판정 {legs}  움직임 {motion}°", good,
              "" if good else f"기대 {want} {want_leg} {want_legs} {want_motion}")
        if name in ADOPTED:
            f, floor = ADOPTED[name]
            m = next(s for s in usable if s["frame"] == f).get("gaze_mult", 1.0)
            check(f"    채택 프레임 f{f} 시선 계수 {m} ≥ {floor}", m >= floor)
        if name == "char_shuffle":
            by = {s["frame"]: s for s in usable}
            rank = {s["frame"]: i + 1 for i, s in
                    enumerate(sorted(usable, key=lambda r: -r["score_adj"]))}
            check(f"    f60 시선 계수 {by[60]['gaze_mult']} = 바닥 0.5, 순위 {rank[60]}/192 (하위 10%)",
                  by[60]["gaze_mult"] == 0.5 and rank[60] >= 173 and rank[6] == 1)
            check(f"    숙인 후보 f47·f67 탈락 (순위 {rank[47]}, {rank[67]})",
                  47 not in got and 67 not in got)

    if os.path.exists(pkl("zombie_listener")):
        try:
            sk.load_wham_track(pkl("zombie_listener"))
            check("listener: 트랙 0개 → 예외", False)
        except RuntimeError as e:
            check("listener: 트랙 0개 → 예외 (WHAM 거짓 성공의 실물)", "추적하지 못했다" in str(e))

    print("\n── B. 가드 off 판정 (경계)")
    j = sk.judge_closed_legs
    check("다리 항 작동 → ok", j("on", 100.0)[0] == "ok")
    check("사용자가 끔 → ok (가드가 아니다)", j("off_user", 100.0)[0] == "ok")
    check("가드 + 14.9° → ok_static", j("off_no_signal", 14.9)[0] == "ok_static")
    check("가드 + 15.0° → human", j("off_no_signal", 15.0)[0] == "human")

    print("\n── C. 시선 계수 (경계)")
    def mult(a):
        s = [{"score": 1.0, "gaze_offaxis": a}]
        sk.apply_gaze_term(s)
        return s[0]["score_adj"]
    check("30° 이하는 1.0", mult(0) == 1.0 and mult(30) == 1.0)
    check("40° 는 0.75 (선형)", mult(40) == 0.75)
    check("50° 이상은 0.5", mult(50) == 0.5 and mult(120) == 0.5)
    s = [{"score": 1.0, "gaze_offaxis": 60.0}]
    check("--gaze-term off → 그대로", sk.apply_gaze_term(s, enabled=False) == "off_user"
          and s[0]["score_adj"] == 1.0)

    print("\n── D. 종료 코드 2 인계 (CLI)")
    cs = f"{H}/02_sam2/char_shuffle"
    if os.path.isdir(f"{cs}/masks") and os.path.exists(pkl("char_shuffle")):
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, "cs")
            os.makedirs(os.path.join(work, "keyframes"))
            os.symlink(f"{cs}/masks", os.path.join(work, "masks"))
            # 다리가 전 프레임 붙은 클립을 흉내 낸다 (leg_gap 0). 동작은 char_shuffle 의 춤.
            allsc = [{"frame": i, "score": 0.2, "bbox": [0, 0, 10, 10], "leg_gap": 0.0}
                     for i in range(192)]
            kd = os.path.join(work, "keyframes")
            json.dump({"topk": allsc[:1], "all": allsc}, open(f"{kd}/candidates.json", "w"))
            open(f"{kd}/key1_f00000.png", "wb").write(b"S2")
            cmd = [sys.executable, SCRIPT, "--sam2-dir", work, "--video",
                   f"{cs}/char_shuffle_masked.mp4", "--wham-pkl", pkl("char_shuffle")]
            r = subprocess.run(cmd, capture_output=True, text=True)
            check("다리 붙음 + 다리 움직임 106.8° → 종료 코드 2", r.returncode == 2
                  and "[인계]" in r.stdout, r.returncode)
            check("인계 시 keyframes/ 를 건드리지 않는다",
                  sorted(os.listdir(kd)) == ["candidates.json", "key1_f00000.png"]
                  and open(f"{kd}/key1_f00000.png", "rb").read() == b"S2")
            r = subprocess.run(cmd + ["--allow-closed-legs"], capture_output=True, text=True)
            d = json.load(open(f"{kd}/candidates.json"))
            check("--allow-closed-legs → 0, forced 기록", r.returncode == 0
                  and d["closed_legs"] == {"verdict": "human", "forced": True,
                                           "leg_motion_min": 15.0}, r.returncode)
    else:
        skipped += 1

    print("\n── E. 키프레임 내보내기 — 옛 key*.png 가 쌓이지 않는다")
    import numpy as np
    import cv2
    with tempfile.TemporaryDirectory() as tmp:
        md, kd = os.path.join(tmp, "masks"), os.path.join(tmp, "keyframes")
        os.makedirs(md)
        for i in range(4):
            m = np.zeros((8, 8), np.uint8); m[2:6, 2:6] = 255
            cv2.imwrite(f"{md}/{i:05d}.png", m)
        frame = lambda i: np.full((8, 8, 3), 100, np.uint8)
        sk.export_keyframes([{"frame": 0}, {"frame": 1}], frame, md, kd)     # S2 시도 1
        sk.export_keyframes([{"frame": 2}, {"frame": 3}], frame, md, kd)     # S2 시도 2
        got = sorted(f for f in os.listdir(kd) if f.endswith(".png"))
        check("재시도 후 key1 은 한 장", got == ["key1_f00002.png", "key2_f00003.png"], got)
        open(f"{kd}/candidates.json", "w").write("{}")
        sk.export_keyframes([{"frame": 1}], frame, md, kd)
        check("PNG 외 파일은 지우지 않는다", os.path.exists(f"{kd}/candidates.json"))

    if skipped:
        print(f"\n⚠️  {skipped}건 건너뜀 (미러 자료 없음)")
    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
