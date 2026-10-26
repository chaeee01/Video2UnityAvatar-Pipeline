#!/usr/bin/env python3
"""갈라진 WHAM 트랙 둘을 **합성 전환**으로 이어 한 클립의 wham_pose.npz 를 만든다 (맥북, numpy · scipy).

stitch_wham_tracks.py 는 이음매에서 자세가 튀면 잇기를 거부한다(JUMP_MAX). 그렇게 거부된 클립 중 사람이 보고
"전환을 만들어 잇는다" 고 정한 것만 이 도구로 잇는다 — 전환 구간은 추적이 아니라 **만든 동작**이라
결과 옆 blend_seam.json 에 어디가 추적이고 어디가 합성 · 유지인지 남긴다. (2026-10-26 사용자 승인:
stalker_fall_back_c · listener_fall_front, 0.5초)

  python blend_track_seam.py --a A.npz --a-start 0 --b B.npz --b-start 113 \\
      --cut 85 --blend 12 --frames 240 --out merged.npz
  (A · B 는 convert_wham_npz.py --track 으로 뽑은 트랙별 npz. 시작 프레임은 stitch.json 의 tracks)

프레임 f 의 출처:
  f ≤ cut                      A[f]                  (추적)
  cut < f ≤ cut+blend          A[cut] → 목표 를 관절별 slerp, 가중치 smoothstep  (합성)
  그 뒤 f < b_start            B[b_start] 유지       (유지 — 영상이 가만히 있는 구간에만 쓸 것)
  f ≥ b_start                  B[f]                  (추적)
목표는 f ≥ b_start 면 B[f], 아니면 B[b_start]. B 의 루트 이동은 이음매에서 끊기지 않게 상수만큼 옮긴다
(높이는 베이킹의 --ground-align 이 바닥에 맞춘다).
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as R


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def slerp_pose(p0, p1, w):
    """p0 · p1: (72,) axis-angle 24관절. 관절별 최단 경로 slerp."""
    q0 = R.from_rotvec(p0.reshape(24, 3)).as_quat()
    q1 = R.from_rotvec(p1.reshape(24, 3)).as_quat()
    dot = np.sum(q0 * q1, axis=1)
    q1[dot < 0] *= -1
    dot = np.abs(np.clip(dot, -1, 1))
    th = np.arccos(np.clip(dot, -1, 1))
    s = np.sin(th)
    small = s < 1e-6
    a = np.where(small, 1 - w, np.sin((1 - w) * th) / np.where(small, 1, s))
    b = np.where(small, w, np.sin(w * th) / np.where(small, 1, s))
    q = a[:, None] * q0 + b[:, None] * q1
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    return R.from_quat(q).as_rotvec().reshape(72)


def merge(A, a_start, B, b_start, cut, blend, frames):
    """A · B: {"pose" (n,72), "trans" (n,3)}. 반환 (pose, trans, source 목록)."""
    a_end = a_start + len(A["pose"]) - 1
    b_end = b_start + len(B["pose"]) - 1
    if not (a_start <= cut <= a_end):
        raise ValueError(f"cut f{cut} 이 A 범위 f{a_start}~{a_end} 밖")
    if b_end < frames - 1:
        raise ValueError(f"B 가 f{b_end} 에서 끝나 f{frames - 1} 까지 못 채운다")
    if cut + blend >= b_end:
        raise ValueError("전환이 B 의 끝을 넘는다")
    pa = lambda f: A["pose"][f - a_start]
    ta = lambda f: A["trans"][f - a_start]
    bi = lambda f: max(f, b_start) - b_start
    delta = ta(cut) - B["trans"][bi(cut + blend + 1)]        # B 루트를 이음매에 붙인다
    pose = np.zeros((frames, 72))
    trans = np.zeros((frames, 3))
    src = []
    for f in range(frames):
        if f <= cut:
            pose[f], trans[f] = pa(f), ta(f)
            src.append("A")
        elif f <= cut + blend:
            w = smoothstep((f - cut) / (blend + 1))
            pose[f] = slerp_pose(pa(cut), B["pose"][bi(f)], w)
            trans[f] = (1 - w) * ta(cut) + w * (B["trans"][bi(f)] + delta)
            src.append("blend")
        else:
            pose[f], trans[f] = B["pose"][bi(f)], B["trans"][bi(f)] + delta
            src.append("hold" if f < b_start else "B")
    return pose, trans, src


def runs(src):
    out, s = [], 0
    for i in range(1, len(src) + 1):
        if i == len(src) or src[i] != src[s]:
            out.append({"source": src[s], "from": s, "to": i - 1})
            s = i
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--a", required=True)
    ap.add_argument("--a-start", type=int, required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--b-start", type=int, required=True)
    ap.add_argument("--cut", type=int, required=True, help="A 에서 쓰는 마지막 프레임")
    ap.add_argument("--blend", type=int, default=12, help="전환 프레임 수 (기본 12 = 0.5초 @24fps)")
    ap.add_argument("--frames", type=int, required=True, help="클립 프레임 수")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    A, B = np.load(a.a), np.load(a.b)
    pose, trans, src = merge(A, a.a_start, B, a.b_start, a.cut, a.blend, a.frames)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out, pose=pose, trans=trans)
    meta = {"a": a.a, "a_start": a.a_start, "b": a.b, "b_start": a.b_start, "cut": a.cut, "blend": a.blend,
            "frames": a.frames, "segments": runs(src)}
    out.with_name("blend_seam.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    print(f"저장: {out}  " + " · ".join(f"{r['source']} f{r['from']}~{r['to']}" for r in meta["segments"]))


if __name__ == "__main__":
    main()
