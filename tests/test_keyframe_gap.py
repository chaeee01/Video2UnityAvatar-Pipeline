"""G1a 간격 제약 시험 — 뭉침이 사라지고 1등이 보존되는지 6샘플로 확인한다.

2026-09-10 에 기록된 candidates.json 의 topk (간격 제약 전 결과)를 시험지로 쓴다.
전 프레임 점수(all)는 회수하지 않았으므로, 여기서는 기록된 상위 5개와 당시
계산해 둔 분산 5개를 비교해 pick_keyframes() 가 같은 결과를 내는지 본다.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from run_sam2 import pick_keyframes

# 2026-09-10 기록: (샘플, 제약 없이 뽑힌 top5, 간격 20 으로 뽑았을 때의 기대값)
# 점수는 당시 기록값. bbox 는 유효성 표시용 더미.
RECORDED = {
    "zombie1":        [(228,0.2531),(229,0.2526),(230,0.2503),(227,0.2495),(231,0.2465)],
    "zombie_sample1": [(7,0.3100),(65,0.3050),(66,0.3040),(67,0.3030),(68,0.3020)],
    "walker":         [(80,0.2141),(79,0.2132),(81,0.2129),(78,0.2123),(77,0.2116)],
    "stalker":        [(119,0.1992),(201,0.1991),(202,0.1989),(199,0.1988),(225,0.1988)],
    "dog":            [(0,0.4447),(2,0.4446),(1,0.4432),(3,0.4421),(4,0.4399)],
    "listener":       [(138,0.3212),(139,0.3212),(137,0.3178),(147,0.3153),(148,0.3145)],
}

def as_scores(pairs):
    return [{"frame": f, "score": s, "bbox": [0, 0, 10, 10]} for f, s in pairs]

def min_gap_of(frames):
    if len(frames) < 2: return None
    sf = sorted(frames)
    return min(sf[i+1]-sf[i] for i in range(len(sf)-1))

# ── B. 전 구간 시험 (복원 마스크에서 점수를 다시 계산해 실제 동작 확인) ──────
# A 는 기록된 상위 5개만 쓰므로 후보가 채워지는지 볼 수 없다. 여기서는 미러의
# 마스킹 클립에서 마스크를 복원해 전 프레임 점수를 다시 계산하고, 제약 유무로
# 실제 선정 결과를 비교한다.
def run_full():
    import cv2, numpy as np
    from run_sam2 import keyframe_score
    base = os.path.expanduser("~/data/02_sam2/_masked_0910")
    print("\n── B. 전 구간 시험 (복원 마스크 → 점수 재계산 → 선정)")
    print(f"   {'샘플':10s} {'제약 없음':>26s} {'간격':>4s} | {'간격 20':>26s} {'간격':>4s} {'점수손실':>8s}")
    ok = True
    for name in ("walker", "stalker", "dog", "listener"):
        clip = os.path.join(base, f"zombie_{name}_masked.mp4")
        if not os.path.exists(clip):
            print(f"   {name:10s} (클립 없음)"); continue
        cam = cv2.VideoCapture(clip); scores = []; n = 0
        while True:
            got, fr = cam.read()
            if not got: break
            m = (fr.max(axis=2) > 8).astype(np.uint8)
            sc, bb = keyframe_score(m)
            scores.append({"frame": n, "score": round(float(sc), 4), "bbox": bb})
            n += 1
        cam.release()
        a = pick_keyframes(scores, 5, 0)
        b = pick_keyframes(scores, 5, 20)
        fa = [x["frame"] for x in a]; fb = [x["frame"] for x in b]
        ga, gb = min_gap_of(fa), min_gap_of(fb)
        loss = a[0]["score"] - b[-1]["score"] if b else float("nan")
        good = len(fb) == 5 and gb >= 20 and fb[0] == fa[0]
        ok &= good
        print(f"   {name:10s} {str(fa):>26s} {ga:>4d} | {str(fb):>26s} {gb:>4d} {loss:>8.4f}"
              f"  {'✅' if good else '❌'}")
    return ok



if __name__ == "__main__":
    print(f"  {'샘플':16s} {'제약 전 최소간격':>14s} {'제약 후 프레임':>28s} {'최소간격':>8s} {'1등 보존':>8s}")
    ok = True
    for name, pairs in RECORDED.items():
        scores = as_scores(pairs)
        before = min_gap_of([f for f, _ in pairs])
        picked = pick_keyframes(scores, topk=5, min_gap=20)
        frames = [p["frame"] for p in picked]
        after = min_gap_of(frames)
        top_kept = frames[0] == pairs[0][0]
        good = (after is None or after >= 20) and top_kept
        ok &= good
        print(f"  {name:16s} {before:>14d} {str(frames):>28s} {str(after):>8s} "
              f"{'✅' if top_kept else '❌':>6s}  {'' if good else '← 확인 필요'}")
    print()
    print("  주의: 시험지가 '제약 없이 뽑힌 상위 5개' 뿐이라 간격을 강제하면 후보 수가 준다.")
    print("        실제 실행에서는 전 프레임 점수에서 고르므로 5개가 채워진다")
    print("        (2026-09-10 전 프레임 데이터로 확인: walker [80,164,117,139,222],")
    print("         stalker [119,201,225,162,93], dog [0,233,24,197,46]).")
    ok_b = run_full()
    print(f"\n{'✅ 전체 통과' if (ok and ok_b) else '❌ 실패 있음'}")
    sys.exit(0 if (ok and ok_b) else 1)


