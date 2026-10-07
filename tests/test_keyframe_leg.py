"""G1a 다리 항 회귀 시험 — 고쳐야 할 샘플만 뒤집히고 검증된 4종은 안 흔들리는지.

2026-10-07 설계 승인 시의 5샘플 실측을 그대로 고정한다. 임계(LEG_BAD·LEG_OK·
LEG_FLOOR·LEG_SIGNAL_P)나 밴드를 움직이면 여기가 먼저 깨진다.

시험지 두 갈래:
  char_shuffle  실제 마스크 PNG 192장 (~/data/02_sam2/char_shuffle/masks)
  4종           마스킹 클립에서 마스크 복원 (~/data/02_sam2/_masked_0910)
                test_keyframe_gap.py 가 쓰는 방식과 같다.

근거 — f60 으로 뽑은 에셋은 2026-10-01 에 불합격, f6 은 10/6 에 합격했다.
따라서 "f6 이 1등, f60 이 하위" 가 이 항의 존재 이유이고 여기서 고정한다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from run_sam2 import apply_leg_term, keyframe_score, leg_gap_ratio, pick_keyframes

MIRROR = os.path.expanduser("~/data/02_sam2")

# 2026-10-07 실측 고정값: (항 작동 여부, 기존 top5, 신규 top5)
EXPECT = {
    "char_shuffle": (True,  [60, 6, 36, 86, 144],     [6, 47, 67, 87, 26]),
    "walker":       (True,  [80, 164, 117, 139, 222], [80, 164, 117, 139, 222]),
    "stalker":      (False, [225, 201, 163, 119, 91], [225, 201, 163, 119, 91]),
    "dog":          (True,  [2, 23, 234, 197, 46],    [2, 23, 234, 197, 46]),
    "listener":     (False, [155, 112, 52, 24, 134],  [155, 112, 52, 24, 134]),
}


def masks_from_dir(d):
    import cv2
    for f in sorted(os.listdir(d)):
        if f.endswith(".png"):
            yield int(f[:-4]), cv2.imread(os.path.join(d, f), cv2.IMREAD_GRAYSCALE) > 127


def masks_from_clip(path):
    import cv2
    cam = cv2.VideoCapture(path)
    n = 0
    while True:
        got, fr = cam.read()
        if not got:
            break
        yield n, (fr.max(axis=2) > 8)      # 배경이 검은 클립이므로 임계 8 로 복원
        n += 1
    cam.release()


def score_all(src):
    out = []
    for idx, m in src:
        s, bbox = keyframe_score(m)
        out.append({"frame": idx, "score": round(float(s), 4), "bbox": bbox,
                    "leg_gap": round(leg_gap_ratio(m), 4)})
    return out


def source_for(name):
    if name == "char_shuffle":
        d = os.path.join(MIRROR, "char_shuffle", "masks")
        return masks_from_dir(d) if os.path.isdir(d) else None
    p = os.path.join(MIRROR, "_masked_0910", f"zombie_{name}_masked.mp4")
    return masks_from_clip(p) if os.path.exists(p) else None


def main():
    print("── 다리 항 5샘플 회귀")
    print(f"   {'샘플':14s} {'항':>6s} {'기존 top5':>26s} {'신규 top5':>26s}  판정")
    ok, skipped = True, 0
    ranks = {}
    for name, (want_on, want_old, want_new) in EXPECT.items():
        src = source_for(name)
        if src is None:
            print(f"   {name:14s} (미러에 자료 없음 — 건너뜀)")
            skipped += 1
            continue
        scores = score_all(src)
        old = [s["frame"] for s in pick_keyframes(scores, 5, 20)]   # score_adj 없음 = 옛 동작
        state, _ = apply_leg_term(scores, enabled=True)
        on = state == "on"
        # 꺼졌다면 반드시 가드 때문이어야 한다 (사용자 지정과 구분되는지)
        assert on or state == "off_no_signal", state
        new = [s["frame"] for s in pick_keyframes(scores, 5, 20)]
        ranks[name] = {s["frame"]: i + 1 for i, s in
                       enumerate(sorted(scores, key=lambda r: -r["score_adj"]))}
        good = (on == want_on and old == want_old and new == want_new)
        ok &= good
        print(f"   {name:14s} {('작동' if on else '꺼짐'):>6s} {str(old):>26s} "
              f"{str(new):>26s}  {'✅' if good else '❌'}")
        if not good:
            print(f"      기대: 항 {'작동' if want_on else '꺼짐'} / "
                  f"{want_old} / {want_new}")

    # 이 항의 존재 이유 — f6 이 1등, f60 은 하위여야 한다.
    if "char_shuffle" in ranks:
        r = ranks["char_shuffle"]
        f6, f60, n = r.get(6), r.get(60), len(r)
        good = f6 == 1 and f60 >= n * 0.9
        ok &= good
        print(f"\n   char_shuffle 순위: f6 {f6}/{n} (1등이어야 함), "
              f"f60 {f60}/{n} (하위 10% 여야 함)  {'✅' if good else '❌'}")

    # --leg-term off 가 옛 동작을 그대로 재현하는지
    if "char_shuffle" in ranks:
        src = source_for("char_shuffle")
        scores = score_all(src)
        base = [s["frame"] for s in pick_keyframes(scores, 5, 20)]
        assert apply_leg_term(scores, enabled=False)[0] == "off_user"
        off = [s["frame"] for s in pick_keyframes(scores, 5, 20)]
        good = off == base == EXPECT["char_shuffle"][1]
        ok &= good
        print(f"   --leg-term off 재현: {off}  {'✅' if good else '❌'}")

    if skipped:
        print(f"\n⚠️  {skipped}개 샘플을 건너뛰었다 (미러 자료 없음)")
    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
