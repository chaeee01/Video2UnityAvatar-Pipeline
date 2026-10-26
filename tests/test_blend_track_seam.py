"""blend_track_seam 단위 시험 — 합성 전환으로 갈라진 트랙 잇기.

고정하는 것: 추적 구간은 원본 그대로, 전환은 A[cut] 에서 목표로 단조롭게, B 시작 전은 B 첫 프레임 유지,
루트 이동은 이음매에서 끊기지 않는다, 범위 밖 cut · 짧은 B 는 거부.
"""
import os
import sys

import numpy as np
from scipy.spatial.transform import Rotation as R

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from blend_track_seam import merge, runs, slerp_pose

ok = True


def check(msg, cond):
    global ok
    print(("   ✅ " if cond else "   ❌ ") + msg)
    ok = ok and cond


def track(n, angle_deg, z0):
    pose = np.zeros((n, 72))
    pose[:, 0] = np.radians(angle_deg)          # 루트를 x 축으로 기울인 자세
    trans = np.zeros((n, 3))
    trans[:, 2] = z0 + np.arange(n) * 0.001
    return {"pose": pose, "trans": trans}


def main():
    print("── slerp")
    p0, p1 = np.zeros(72), np.zeros(72)
    p1[0] = np.radians(80)
    check("w=0 → p0, w=1 → p1", np.allclose(slerp_pose(p0, p1, 0.0), p0) and np.allclose(slerp_pose(p0, p1, 1.0), p1))
    check("w=0.5 → 40°", abs(np.degrees(slerp_pose(p0, p1, 0.5)[0]) - 40) < 1e-6)

    print("\n── stalker_fall_back_c 형 (A f0~113, B f113~239, cut 85, 전환 12)")
    A, B = track(114, 60, 0.0), track(127, 88, 5.0)
    pose, trans, src = merge(A, 0, B, 113, 85, 12, 240)
    seg = runs(src)
    check("구간 A f0~85 · blend f86~97 · hold f98~112 · B f113~239",
          [(r["source"], r["from"], r["to"]) for r in seg] == [("A", 0, 85), ("blend", 86, 97), ("hold", 98, 112), ("B", 113, 239)])
    check("추적 구간은 원본 그대로", np.allclose(pose[:86], A["pose"][:86]) and np.allclose(pose[113:], B["pose"]))
    ang = np.degrees([R.from_rotvec(pose[f, :3]).magnitude() for f in range(85, 99)])
    check(f"전환 각도 단조 증가 60 → 88 ({ang[0]:.0f} … {ang[-1]:.0f})", bool(np.all(np.diff(ang) >= -1e-9)) and abs(ang[-1] - 88) < 1e-6)
    check("유지 구간은 B 첫 프레임", np.allclose(pose[98:113], B["pose"][0]))
    jump = np.abs(np.diff(trans, axis=0)).max()
    check(f"루트 이동이 끊기지 않음 (프레임 간 최대 {jump:.4f})", jump < 0.01)

    print("\n── listener_fall_front 형 (A f0~120, B f122~239, cut 120)")
    A, B = track(121, 5, 0.0), track(118, 75, -3.0)
    pose, trans, src = merge(A, 0, B, 122, 120, 12, 240)
    check("구간 A f0~120 · blend f121~132 · B f133~239 (유지 없음)",
          [(r["source"], r["from"], r["to"]) for r in runs(src)] == [("A", 0, 120), ("blend", 121, 132), ("B", 133, 239)])
    w = (1 / 13) ** 2 * (3 - 2 / 13)
    check("f121 (B 시작 전) 목표는 B 첫 프레임", np.allclose(pose[121], slerp_pose(A["pose"][120], B["pose"][0], w)))

    print("\n── 거부")
    for name, args in (("cut 이 A 밖", (A, 0, B, 122, 130, 12, 240)), ("B 가 짧다", (A, 0, B, 122, 120, 12, 260))):
        try:
            merge(*args)
            check(name, False)
        except ValueError:
            check(name + " → ValueError", True)

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
