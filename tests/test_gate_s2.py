"""게이트의 게이트 — gate_s2 가 좋은 산출물을 막지 않고 나쁜 것을 놓치지 않는지 시험한다.

두 층으로 나눈다.

  A. 판정 시험 (7건) — 2026-09-10 에 기록된 지표를 judge() 에 그대로 넣는다.
     실패 3건 중 2건(listener 1·2차)은 마스크가 남아 있지 않아 실물 시험이
     불가능하므로, 판정 로직만이라도 전수로 시험한다.
  B. 측정 시험 (4건) — 미러의 마스킹 클립에서 마스크를 복원해 measure() 부터
     끝까지 돌린다. 측정 코드와 판정 코드를 잇는 통합 시험이다.

B 가 4건뿐인 이유: 마스크 PNG 폴더를 회수하지 않았고(볼륨에만 있다), listener
1·2차는 재실행 스크립트가 rm -rf 로 지워 어디에도 없다. 실패 산출물이 게이트의
시험지라는 것을 그때는 몰랐다.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import gate_s2

# (이름, 지표, 기대 판정, 무엇을 시험하는가)
JUDGE_CASES = [
    ("walker",          dict(coverage_mean=9.21,  empty_frames=0,  parts_mean=1.00), "PASS", "전신 성공 (최저 커버리지 성공 사례)"),
    ("stalker 2차",     dict(coverage_mean=9.31,  empty_frames=0,  parts_mean=1.00), "PASS", "겉옷 좌표로 재시도해 성공"),
    ("dog",             dict(coverage_mean=12.44, empty_frames=0,  parts_mean=1.00), "PASS", "기는 자세, 커버리지 최대"),
    ("zombie1",         dict(coverage_mean=9.50,  empty_frames=0,  parts_mean=1.00), "PASS", "9/4 기준선 (근사치)"),
    ("listener 1차",    dict(coverage_mean=3.00,  empty_frames=0,  parts_mean=1.00), "FAIL", "속옷만 — 커버리지로 잡아야 한다"),
    ("listener 2차",    dict(coverage_mean=6.04,  empty_frames=0,  parts_mean=3.11), "FAIL", "겉옷만 — 커버리지가 애매해 조각 수로 잡아야 한다"),
    ("listener 3차",    dict(coverage_mean=0.81,  empty_frames=0,  parts_mean=1.00), "FAIL", "얼굴만 — 커버리지로 잡아야 한다"),
    ("stalker 1차",     dict(coverage_mean=0.52,  empty_frames=54, parts_mean=2.48), "FAIL", "셔츠 띠만 — 세 지표 모두 걸려야 한다"),
]

VIDEO_CASES = [
    ("zombie_walker",   "PASS"),
    ("zombie_stalker",  "PASS"),
    ("zombie_dog",      "PASS"),
    ("zombie_listener", "FAIL"),   # 3차(얼굴) 실행분이 남아 있다
]


def run_judge():
    print("── A. 판정 시험 (기록된 지표 → judge())")
    print(f"   {'사례':16s} {'cov':>6s} {'빈':>3s} {'조각':>5s}  {'기대':>4s} {'결과':>4s}  판정")
    ok = 0
    for name, m, expect, why in JUDGE_CASES:
        metrics = dict(m)
        verdict, reasons, warns = gate_s2.judge(metrics)
        good = verdict == expect
        ok += good
        print(f"   {name:16s} {m['coverage_mean']:>6.2f} {m['empty_frames']:>3d} "
              f"{m['parts_mean']:>5.2f}  {expect:>4s} {verdict:>4s}  "
              f"{'✅' if good else '❌ 불일치'}")
        if not good:
            print(f"      시험 의도: {why}")
            print(f"      사유: {reasons or '(없음)'}")
    print(f"   → {ok}/{len(JUDGE_CASES)} 정답")
    return ok == len(JUDGE_CASES)


def run_video(tmp):
    print("\n── B. 측정 시험 (마스킹 클립 복원 → 전 구간)")
    base = os.path.expanduser("~/data/02_sam2/_masked_0910")
    ok = 0
    for name, expect in VIDEO_CASES:
        clip = os.path.join(base, f"{name}_masked.mp4")
        if not os.path.exists(clip):
            print(f"   {name:16s} (클립 없음 — 건너뜀)")
            continue
        out = os.path.join(tmp, name)
        r = subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "..", "scripts", "gate_s2.py"),
             "--video", clip, "--out", out, "--stride", "4"],
            capture_output=True, text=True)
        verdict = "PASS" if r.returncode == 0 else "FAIL"
        good = verdict == expect
        ok += good
        head = r.stdout.strip().splitlines()[0] if r.stdout.strip() else "(출력 없음)"
        print(f"   {head}")
        print(f"   {'':3s}기대 {expect} / 결과 {verdict}  {'✅' if good else '❌ 불일치'}")
    print(f"   → {ok}/{len(VIDEO_CASES)} 정답")
    return ok == len(VIDEO_CASES)


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        a = run_judge()
        b = run_video(tmp)
    print(f"\n{'✅ 전체 통과' if (a and b) else '❌ 실패 있음'}")
    sys.exit(0 if (a and b) else 1)
