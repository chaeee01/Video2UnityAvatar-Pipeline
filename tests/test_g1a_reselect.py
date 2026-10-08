"""G1a 재선정 단계 시험 — 구조(보존·내보내기·정지 경로).

감점 임계는 여기서 보지 않는다 (test_keyframe_leg.py 와 시선 항 시험의 몫).
시험지는 미러의 char_shuffle (마스크 192장 + WHAM pkl). 원본 영상이 미러에 없어
마스킹 클립을 --video 자리에 넣는다 — 프레임 수와 순서가 같으므로 구조 시험에는 충분하다.
미러를 건드리지 않도록 임시 폴더에 keyframes/ 를 복사하고 masks/ 는 심볼릭 링크로 건다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(__file__)
SCRIPT = os.path.join(HERE, "..", "scripts", "select_keyframes.py")
MIRROR = os.path.expanduser("~/data")
SAM2 = os.path.join(MIRROR, "02_sam2", "char_shuffle")
CLIP = os.path.join(SAM2, "char_shuffle_masked.mp4")
PKL = os.path.join(MIRROR, "04_wham", "char_shuffle_masked", "wham_output.pkl")


def run(work, pkl=PKL):
    r = subprocess.run([sys.executable, SCRIPT, "--sam2-dir", work, "--video", CLIP,
                        "--wham-pkl", pkl], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def keys(d):
    return sorted(f for f in os.listdir(d) if f.startswith("key") and f.endswith(".png"))


def main():
    if not (os.path.isdir(os.path.join(SAM2, "masks")) and os.path.exists(PKL)):
        print("⚠️  미러에 char_shuffle 마스크·pkl 이 없어 건너뛴다")
        return 0
    ok = True

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")

    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "cs")
        os.makedirs(work)
        shutil.copytree(os.path.join(SAM2, "keyframes"), os.path.join(work, "keyframes"))
        os.symlink(os.path.join(SAM2, "masks"), os.path.join(work, "masks"))
        kd = os.path.join(work, "keyframes")
        shutil.rmtree(os.path.join(kd, "_s2pick"), ignore_errors=True)
        before = keys(kd)
        s2_cand = open(os.path.join(kd, "candidates.json")).read()

        print("── 1회차")
        rc, out = run(work)
        check("종료 코드 0", rc == 0, out[-300:] if rc else "")
        now = keys(kd)
        check("key PNG 가 순위당 한 장 (옛 파일 정리)", len(now) == 5
              and [k[:4] for k in now] == ["key1", "key2", "key3", "key4", "key5"], now)
        check("1등은 f6", now and now[0] == "key1_f00006.png", now[:1])
        keep = os.path.join(kd, "_s2pick")
        check("_s2pick/ 에 S2 원본 PNG 전부 보존", keys(keep) == before, len(keys(keep)))
        check("_s2pick/ 에 S2 원본 candidates.json 보존",
              open(os.path.join(keep, "candidates.json")).read() == s2_cand)
        d = json.load(open(os.path.join(kd, "candidates.json")))
        check("기록: stage · wham · 프레임별 시선각",
              d.get("stage") == "g1a_reselect" and d["wham"]["frames"] == 192
              and all("gaze_offaxis" in s for s in d["all"]))
        f6 = next(s for s in d["all"] if s["frame"] == 6)
        f60 = next(s for s in d["all"] if s["frame"] == 60)
        check("시선 이탈각 실측 재현 (f6 5.4° / f60 56.6°)",
              abs(f6["gaze_offaxis"] - 5.4) < 0.1 and abs(f60["gaze_offaxis"] - 56.6) < 0.1,
              (f6["gaze_offaxis"], f60["gaze_offaxis"]))
        check("다리 움직임 실측 재현 (106.8°)", abs(d["wham"]["leg_motion_deg"] - 106.8) < 0.1,
              d["wham"]["leg_motion_deg"])

        print("── 2회차 (재실행이 S2 보존분을 덮지 않는가)")
        rc, out = run(work)
        check("종료 코드 0, '보존분 유지'", rc == 0 and "보존분 유지" in out)
        check("_s2pick/ 불변", keys(keep) == before
              and open(os.path.join(keep, "candidates.json")).read() == s2_cand)
        check("결과 동일 (멱등)", keys(kd) == now)

        print("── 정지 경로")
        rc, out = run(work, pkl=os.path.join(tmp, "없는파일.pkl"))
        check("pkl 없음 → 실패", rc != 0)
        import joblib
        import numpy as np
        src = joblib.load(PKL)
        t = dict(list(src.values())[0])
        # 다른 영상의 pkl (프레임 수가 마스크보다 많다)
        big = dict(t, pose=np.concatenate([t["pose"], t["pose"]]),
                   frame_ids=np.arange(len(t["pose"]) * 2))
        p_big = os.path.join(tmp, "big.pkl")
        joblib.dump({0: big}, p_big)
        rc, out = run(work, pkl=p_big)
        check("frame_ids 가 마스크 범위 밖 → 정지", rc != 0 and "범위를 벗어난다" in out, out[-120:])
        check("정지 시 기존 키프레임을 건드리지 않는다", keys(kd) == now)
        # 추적 누락: f0~f19 를 뺀 pkl → f6 은 후보가 될 수 없다
        sub = dict(t, pose=t["pose"][20:], frame_ids=t["frame_ids"][20:])
        p_sub = os.path.join(tmp, "sub.pkl")
        joblib.dump({0: sub}, p_sub)
        rc, out = run(work, pkl=p_sub)
        d = json.load(open(os.path.join(kd, "candidates.json")))
        picked = [s["frame"] for s in d["topk"]]
        check("추적 누락 프레임(f0~f19)은 후보에서 제외", rc == 0 and min(picked) >= 20
              and d["wham"]["untracked"] == list(range(20)), picked)
        # 트랙이 비어 있음
        p_empty = os.path.join(tmp, "empty.pkl")
        joblib.dump({}, p_empty)
        rc, out = run(work, pkl=p_empty)
        check("트랙 0개 → 정지", rc != 0 and "추적하지 못했다" in out)

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
