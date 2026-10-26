"""바닥 정렬 — 5-5 베이킹에서 루트 높이만 옮겨 몸이 바닥에 닿게 한다 (apply_wham_pose.py --ground-align 이 쓴다).

Blender 없이 돈다 (bpy 를 쓰지 않는다). 그래서 tests/ 에서 그대로 시험할 수 있다.

**왜** — 베이킹은 클립의 첫 프레임을 리그의 선 자세 골반 높이에 둔다(apply_wham_pose 독스트링의 가정).
누워서 시작하는 get_up 은 이 가정이 깨져 통째로 떠 있고(2026-10-26 실측 +0.36~0.45, 키 약 1.0),
WHAM 의 누운 구간 높이도 흔들려 fall 류가 뜨거나(+0.08~0.12) 묻힌다(−0.13).

**어떻게** — 처음 · 끝 WINDOW 프레임의 메쉬 최저점을 바닥(rest 메쉬 최저점)에 맞추는 높이 보정 o0 · o1 을
구하고, 그 사이는 **자세로** 잇는다: 관절 높이 폭(가장 높은 관절 − 가장 낮은 관절, 서면 약 0.8 · 누우면 약 0.2)이
처음에서 끝으로 얼마나 옮겨 갔는지를 가중치로 쓴다. 넘어지는 클립의 선 구간은 o0, 누운 구간은 o1 을 받는다.
처음과 끝의 높이 폭 차가 EXT_MIN 보다 작으면(서서 시작해 서서 끝나는 클립) 시간으로 선형 보간한다 —
그런 클립은 o0 · o1 이 0 에 가까워 보정도 0 에 가깝다.
그다음 **묻힌 프레임만 들어 올린다**: 위 보정 뒤에도 최저점이 바닥 아래 SINK_TOL 넘게 들어간 프레임(추적이 무릎
꿇는 구간의 골반을 너무 낮게 잡은 경우 — listener_fall_front f105~124, −0.15)을 그만큼 올리고, 갑자기 튀지 않게
LIFT_WIN 프레임 최대값 필터 뒤 삼각 평활한다. 내리는 일은 없다. 처음 · 끝은 바닥에 맞췄으므로 들리지 않는다.
처음 · 끝을 한 프레임이 아니라 WINDOW 의 최저점으로 재는 것은 달리기처럼 공중에 뜬 프레임으로 끝나는
클립에서 보정이 튀지 않게 하기 위해서다.
"""
import numpy as np

WINDOW = 6        # 처음 · 끝 0.25초 (24fps)
EXT_MIN = 0.2     # 자세로 가중치를 잡을 최소 높이 폭 차 (키 약 1.0)
SINK_TOL = 0.02   # 이만큼까지 묻히는 것은 둔다 (발바닥 · 옷자락 오차)
LIFT_WIN = 7      # 들어 올림을 펴는 창 (프레임, 홀수)


def weights(ext, k=WINDOW, ext_min=EXT_MIN):
    """ext: 프레임별 관절 높이 폭 (T,). 반환 (w (T,) 0~1, "pose" | "time")."""
    ext = np.asarray(ext, dtype=float)
    T = len(ext)
    k = max(1, min(k, T))
    e0, e1 = ext[:k].mean(), ext[-k:].mean()
    if abs(e1 - e0) >= ext_min:
        return np.clip((ext - e0) / (e1 - e0), 0.0, 1.0), "pose"
    return (np.linspace(0.0, 1.0, T) if T > 1 else np.zeros(T)), "time"


def offsets(lows_first, lows_last, ext, floor, k=WINDOW):
    """프레임별 높이 보정 (T,) 와 요약. lows_first · lows_last: 처음 · 끝 k 프레임의 메쉬 최저점."""
    o0 = float(floor - np.min(lows_first))
    o1 = float(floor - np.min(lows_last))
    w, mode = weights(ext, k)
    off = o0 + w * (o1 - o0)
    return off, {"o0": round(o0, 4), "o1": round(o1, 4), "mode": mode, "max_abs": round(float(np.abs(off).max()), 4)}


def lift(lows, floor, tol=SINK_TOL, win=LIFT_WIN):
    """lows: 높이 보정을 더한 뒤의 프레임별 메쉬 최저점 (T,). 반환: 추가로 올릴 양 (T,) ≥ 0.
    최대값 필터 뒤 같은 폭으로 평활하므로 각 프레임은 필요한 만큼 이상 올라간다(묻힘 ≤ tol 보장)."""
    need = np.maximum(0.0, (floor - tol) - np.asarray(lows, dtype=float))
    if not need.any():
        return need
    h = win // 2
    pad = np.pad(need, h, mode="edge")
    mx = np.array([pad[i:i + win].max() for i in range(len(need))])
    k = np.bartlett(win + 2)[1:-1]
    return np.convolve(np.pad(mx, h, mode="edge"), k / k.sum(), mode="valid")
