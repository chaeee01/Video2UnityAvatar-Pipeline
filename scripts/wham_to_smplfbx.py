#!/usr/bin/env python3
"""
WHAM 의 wham_output.pkl 을 SMPL-to-FBX 가 기대하는 형식으로 변환합니다.

WHAM 출력:  {track_id: {'pose': (T,72), 'trans': (T,3), 'betas': (T,10), ...}}
SMPL-to-FBX 입력: {'smpl_poses': (T,72), 'smpl_trans': (T,3)}

사용법:
  python wham_to_smplfbx.py --pkl wham_output.pkl --out ./motions/zombie.pkl

옵션:
  --world      카메라 좌표 대신 월드 좌표 사용 (DPVO 없이 돌렸다면 신뢰도 낮음)
  --smooth N   포즈에 N 프레임 이동평균. 튀는 프레임 완화용 (기본 0 = 끔)
  --scale S    trans 스케일. SMPL FBX 템플릿이 scale5 이므로 보통 100 이 맞습니다
"""
import argparse
import pickle
from pathlib import Path

import joblib
import numpy as np


def moving_average(x: np.ndarray, k: int) -> np.ndarray:
    """축각 표현에 그대로 이동평균을 걸면 각도 점프에서 왜곡이 생기지만,
    작은 k(3~5)에서는 실용적으로 잘 동작합니다."""
    if k <= 1:
        return x
    pad = k // 2
    padded = np.pad(x, ((pad, pad), (0, 0)), mode="edge")
    kernel = np.ones(k) / k
    return np.stack([np.convolve(padded[:, i], kernel, mode="valid")
                     for i in range(x.shape[1])], axis=1)[:len(x)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", required=True, help="WHAM 의 wham_output.pkl")
    ap.add_argument("--out", required=True, help="출력 pkl 경로")
    ap.add_argument("--track", type=int, default=None, help="트랙 ID (기본: 첫 번째)")
    ap.add_argument("--world", action="store_true")
    ap.add_argument("--smooth", type=int, default=0)
    ap.add_argument("--scale", type=float, default=100.0)
    a = ap.parse_args()

    data = joblib.load(a.pkl)
    keys = list(data.keys())
    print(f"트랙 목록: {keys}")

    key = a.track if a.track is not None else keys[0]
    track = data[key]
    print(f"사용 트랙: {key}")

    pose_key = "pose_world" if a.world else "pose"
    trans_key = "trans_world" if a.world else "trans"

    poses = np.asarray(track[pose_key], dtype=np.float64)   # (T, 72)
    trans = np.asarray(track[trans_key], dtype=np.float64)  # (T, 3)

    if poses.shape[1] != 72:
        raise ValueError(f"pose 차원이 72 가 아닙니다: {poses.shape}")

    T = len(poses)
    print(f"프레임: {T}")
    print(f"포즈 표준편차: {poses.std():.4f}  (0.01 미만이면 동작 추정 실패 의심)")

    if a.smooth > 1:
        poses = moving_average(poses, a.smooth)
        trans = moving_average(trans, a.smooth)
        print(f"스무딩 적용: {a.smooth} 프레임")

    # 루트를 원점 기준으로 이동. 유니티에서 배치하기 편합니다.
    trans = trans - trans[0]
    trans = trans * a.scale

    out = {
        "smpl_poses": poses.astype(np.float32),
        "smpl_trans": trans.astype(np.float32),
    }

    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        pickle.dump(out, f)

    print(f"\n저장: {out_path}")
    print(f"  smpl_poses {out['smpl_poses'].shape}")
    print(f"  smpl_trans {out['smpl_trans'].shape}")
    print(f"  루트 총 이동거리: {np.linalg.norm(np.diff(trans, axis=0), axis=1).sum():.1f}")


if __name__ == "__main__":
    main()
