"""G2·G2r 오탐 시험 — 기존 실측 전부를 시험지로 쓴다.

G2 는 미러의 GLB 실물로 돌린다(측정+판정 통합). 실측 metallic 이 0.2~254.7 로
두 자릿수 넘게 벌어져 있어 경계 근처 사례가 없다 — 임계값 32 는 그 사이 어디든
가르므로, 이 시험은 "임계값이 옳다" 가 아니라 "게이트가 알려진 양/불을 뒤집지
않는다" 를 확인하는 것이다.

G2r 은 관통 4회의 기록된 수치로 판정 로직만 시험한다.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import gate_g2r

GEN2 = os.path.expanduser("~/data/03_trellis/gen2")

# (표시명, GLB 경로, 기대 판정, 근거)
G2_CASES = [
    ("walker 512",        f"{GEN2}/zombie_walker/zombie_walker.glb",   "PASS", "metallic 0.2 — 무광 셔츠"),
    ("zombie1 512",       f"{GEN2}/zombie1/zombie1.glb",               "PASS", "metallic 1.0"),
    ("stalker 512",       f"{GEN2}/zombie_stalker/zombie_stalker.glb", "FAIL", "metallic 254.7 — 전신 금속 오판"),
    ("dog 512",           f"{GEN2}/zombie_dog/zombie_dog.glb",         "FAIL", "metallic 51.5 — 번들거림"),
    ("zombie1 1024",      f"{GEN2}/zombie1_1024/zombie1_1024.glb",     "FAIL", "metallic 254.7"),
    ("zombie1 1024 보정", f"{GEN2}/zombie1_1024/zombie1_1024_dielectric.glb", "PASS",
     "같은 텍스처지만 metallicFactor 0 — 유효 metallic 이 0 이므로 통과해야 한다"),
    ("walker 1024 s1",    f"{GEN2}/_probe_walker_1024_s1/_probe_walker_1024_s1.glb", "FAIL",
     "metallic 143.4 — 1024 계통 상승"),
]

# 측정 자체가 실패하는 경우. 게이트가 "못 재서 통과" 하면 안 된다 —
# 2026-09-15 오탐 시험에서 실제로 그렇게 통과하던 것을 잡았다.
G2_UNMEASURABLE = [
    ("텍스처 없음", f"{GEN2}/zombie_walker/zombie_walker.glb", "FAIL",
     "--textures 를 빈 폴더로 줘 측정 불가 상태를 만든다"),
]

# (표시명, aligned_params 값, joint_dist, fallback_pct, 기대, 근거)
G2R_CASES = [
    ("zombie_sample1", dict(scale=0.588,  bbox_iou=0.717), 0.028,  3.0,  "PASS", "1세대 첫 관통"),
    ("zombie1 1세대",  dict(scale=0.5906, bbox_iou=0.797), 0.0293, 3.0,  "PASS", "1세대 기준선"),
    ("zombie1 512",    dict(scale=0.5892, bbox_iou=0.743), 0.0292, 1.49, "PASS", "2세대 512"),
    ("zombie1 1024",   dict(scale=0.5914, bbox_iou=0.760), 0.0293, 3.67, "PASS", "2세대 1024"),
    ("스케일 이탈",    dict(scale=0.42,   bbox_iou=0.70),  0.03,   2.0,  "FAIL", "상수 범위 밖 — 상류 오류"),
    ("좌표계 오판",    dict(scale=0.59,   bbox_iou=0.70),  2.6645, 2.0,  "FAIL", "차순위 후보 거리 — 잡아야 한다"),
    ("정렬 실패",      dict(scale=0.59,   bbox_iou=0.31),  0.03,   2.0,  "FAIL", "IoU 미달"),
    ("무배정 잔존",    dict(scale=0.59,   bbox_iou=0.70),  0.03,   2.0,  "FAIL", "무배정 0.4% — 전이 미완"),
]


def run_g2(tmp):
    print("── G2 (GLB 실물 → 측정+판정)")
    ok = 0
    for name, glb, expect, why in G2_CASES:
        if not os.path.exists(glb):
            print(f"   {name:18s} (GLB 없음 — 건너뜀: {glb})")
            continue
        out = os.path.join(tmp, name.replace(" ", "_"))
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "gate_g2.py"),
                            "--glb", glb, "--out", out, "--name", name],
                           capture_output=True, text=True)
        verdict = "PASS" if r.returncode == 0 else "FAIL"
        good = verdict == expect
        ok += good
        head = r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr[-200:]
        print(f"   {head}")
        print(f"      기대 {expect} / 결과 {verdict}  {'✅' if good else '❌ 불일치 — ' + why}")
    # 측정 불가 사례
    for name, glb, expect, why in G2_UNMEASURABLE:
        if not os.path.exists(glb):
            continue
        empty = os.path.join(tmp, "empty_tex"); os.makedirs(empty, exist_ok=True)
        out = os.path.join(tmp, "unmeasurable")
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "gate_g2.py"),
                            "--glb", glb, "--out", out, "--name", name,
                            "--textures", empty],
                           capture_output=True, text=True)
        verdict = "PASS" if r.returncode == 0 else "FAIL"
        good = verdict == expect
        ok += good
        head = r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr[-200:]
        print(f"   {head}")
        print(f"      기대 {expect} / 결과 {verdict}  {'✅' if good else '❌ 불일치 — ' + why}")
    total = len(G2_CASES) + len(G2_UNMEASURABLE)
    print(f"   → {ok}/{total} 정답")
    return ok == total


def run_g2r():
    print("\n── G2r (기록 수치 → judge())")
    print(f"   {'사례':16s} {'scale':>7s} {'IoU':>6s} {'관절':>7s} {'폴백':>6s}  {'기대':>4s} {'결과':>4s}")
    ok = 0
    for name, p, jd, fb, expect, why in G2R_CASES:
        m = dict(scale=p["scale"], bbox_iou=p["bbox_iou"], joint_dist=jd,
                 fallback_pct=fb, unassigned_pct=0.4 if name == "무배정 잔존" else 0.0)
        verdict, reasons, warns = gate_g2r.judge(m)
        good = verdict == expect
        ok += good
        print(f"   {name:16s} {p['scale']:>7.4f} {p['bbox_iou']:>6.3f} {jd:>7.4f} {fb:>6.2f}  "
              f"{expect:>4s} {verdict:>4s}  {'✅' if good else '❌'}")
        if not good:
            print(f"      의도: {why} / 사유: {reasons}")
    print(f"   → {ok}/{len(G2R_CASES)} 정답")
    return ok == len(G2R_CASES)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        a = run_g2(tmp)
    b = run_g2r()
    print(f"\n{'✅ 전체 통과' if (a and b) else '❌ 실패 있음'}")
    sys.exit(0 if (a and b) else 1)
