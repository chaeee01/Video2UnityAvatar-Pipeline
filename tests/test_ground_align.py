"""바닥 정렬 로직(ground_align) 단위 시험 — Blender 없이 돈다.

고정하는 것 (2026-10-26 실측 · 사용자 승인 설계):
  - 서서 시작해 서서 끝나는 클립은 보정 ~0 (시간 보간, o0 · o1 이 0 근처)
  - get_up(누워 시작 → 서서 끝): 처음은 o0, 끝은 o1 — 둘 다 바닥에 닿는다
  - fall_back(서서 → 누움): 선 구간은 o0(≈0) 그대로, 누운 구간만 o1 — 자세(높이 폭)로 잇는다
  - 처음 · 끝은 창 안의 최저점 — 공중 프레임으로 끝나도 보정이 튀지 않는다
  - 중간에 묻힌 프레임(listener_fall_front f105~124, −0.15)만 들어 올린다 — 묻힘 ≤ SINK_TOL, 내리지 않음, 매끄럽게
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from ground_align import SINK_TOL, WINDOW, lift, offsets, weights

ok = True


def check(msg, cond):
    global ok
    print(("   ✅ " if cond else "   ❌ ") + msg)
    ok = ok and cond


FLOOR = -0.50


def main():
    print("── 서서 시작 · 서서 끝 (회귀: 보정 ~0)")
    T = 240
    ext = np.full(T, 0.82) + 0.01 * np.sin(np.arange(T) / 10)
    off, info = offsets([-0.497] * WINDOW, [-0.503] * WINDOW, ext, FLOOR)
    check(f"시간 보간 ({info['mode']})", info["mode"] == "time")
    check(f"최대 |보정| {info['max_abs']} ≤ 0.005", info["max_abs"] <= 0.005)

    print("\n── 공중 프레임으로 끝나는 달리기")
    last = [-0.50, -0.46, -0.42, -0.40, -0.41, -0.44]      # 창 안에 접지 프레임이 하나 있다
    off, info = offsets([-0.50] * WINDOW, last, ext, FLOOR)
    check(f"끝 보정은 창 안 최저점 기준 → 0 ({info['o1']})", abs(info["o1"]) < 1e-9)

    print("\n── get_up: 누워 시작(+0.36 뜸) → 서서 끝(+0.29 뜸)")
    ext = np.concatenate([np.full(60, 0.22), np.linspace(0.22, 0.82, 120), np.full(60, 0.82)])
    off, info = offsets([-0.14] * WINDOW, [-0.21] * WINDOW, ext, FLOOR)
    check(f"자세 보간 ({info['mode']})", info["mode"] == "pose")
    check(f"처음 보정 o0 = {off[0]:+.2f} (−0.36)", abs(off[0] + 0.36) < 1e-6)
    check(f"끝 보정 o1 = {off[-1]:+.2f} (−0.29)", abs(off[-1] + 0.29) < 1e-6)
    check("중간은 둘 사이", bool(np.all((off <= -0.29 + 1e-9) & (off >= -0.36 - 1e-9))))

    print("\n── fall_back: 서서(바닥) → 누워 끝(+0.12 뜸)")
    ext = np.concatenate([np.full(40, 0.82), np.linspace(0.82, 0.25, 30), np.full(10, 0.25)])
    off, info = offsets([-0.50] * WINDOW, [-0.38] * WINDOW, ext, FLOOR)
    check(f"선 구간(f0~39) 보정 0 (최대 {np.abs(off[:40]).max():.4f})", np.abs(off[:40]).max() < 1e-9)
    check(f"누운 끝 보정 −0.12 ({off[-1]:+.3f})", abs(off[-1] + 0.12) < 1e-6)
    check("넘어지는 구간은 단조", bool(np.all(np.diff(off[40:70]) <= 1e-12)))

    print("\n── 가중치 경계")
    w, mode = weights(np.full(10, 0.5))
    check("높이 폭 변화 없음 → 시간 보간 0→1", mode == "time" and w[0] == 0 and w[-1] == 1)
    w, mode = weights(np.array([0.8] * 6 + [1.0] * 4 + [0.2] * 6))
    check("범위 밖 높이 폭은 0~1 로 자른다", mode == "pose" and w.min() >= 0 and w.max() <= 1)

    print("\n── 묻힌 프레임 들어 올리기")
    lows = np.full(240, FLOOR)
    lows[105:125] = FLOOR - 0.15 * np.sin(np.linspace(0, np.pi, 20))
    up = lift(lows, FLOOR)
    after = lows + up
    check(f"묻힘이 SINK_TOL 안으로 (최저 {after.min() - FLOOR:+.3f})", after.min() >= FLOOR - SINK_TOL - 1e-9)
    check("내리는 프레임 없음", bool(np.all(up >= 0)))
    check("처음 · 끝은 그대로", up[:WINDOW].max() == 0 and up[-WINDOW:].max() == 0)
    check(f"매끄러움 — 프레임 간 변화 ≤ 0.03 (최대 {np.abs(np.diff(up)).max():.3f})", np.abs(np.diff(up)).max() <= 0.03)
    check("묻힘 없으면 0", not lift(np.full(50, FLOOR - 0.01), FLOOR).any())

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
