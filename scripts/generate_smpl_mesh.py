#!/usr/bin/env python3
"""
SMPL 리깅 1단계: WHAM 결과에서 SMPL 메쉬를 뽑아냅니다.

출력 (기본 /workspace/data/06_smpl_mesh/):
  smpl_frame<N>.obj   키프레임 자세의 SMPL 메쉬 — TRELLIS 메쉬와 정렬할 대상
  smpl_tpose.obj      같은 체형(betas)의 T포즈 메쉬 — 골격 기준 확인용
  joints_frame<N>.json  24관절 3D 위치 — 이후 아마추어 생성에 사용
  smpl_faces.npy      SMPL 면 정보 — 로컬 재사용을 위해 저장

실행 (Pod, wham 환경):
  python generate_smpl_mesh.py \
      --pkl /workspace/data/05_wham/zombie_sample1/wham_output.pkl \
      --frame 0

--frame 은 TRELLIS에 넣었던 키프레임과 같은 프레임 번호를 지정하세요.
어느 프레임인지 애매하면 overlay.mp4를 보고 그 장면의 번호를 찾으면 됩니다.
"""
import argparse
import json
import pickle
from pathlib import Path

import joblib
import numpy as np
import torch
import trimesh

SMPL_DIR = "/workspace/repos/WHAM/dataset/body_models/smpl"


def load_faces(smpl_dir: str) -> np.ndarray:
    with open(Path(smpl_dir) / "SMPL_NEUTRAL.pkl", "rb") as f:
        data = pickle.load(f, encoding="latin1")
    return np.asarray(data["f"], dtype=np.int64)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", required=True)
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--out", default="/workspace/data/06_smpl_mesh")
    ap.add_argument("--smpl-dir", default=SMPL_DIR)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    track = next(iter(joblib.load(a.pkl).values()))
    verts = np.asarray(track["verts"])          # (T, 6890, 3)
    betas = np.asarray(track["betas"])          # (T, 10)
    T = len(verts)
    f = a.frame
    if not (0 <= f < T):
        raise SystemExit(f"프레임 범위 밖: {f} (0~{T-1})")

    faces = load_faces(a.smpl_dir)
    np.save(out / "smpl_faces.npy", faces)

    # ---- 키프레임 자세 메쉬 (WHAM 이 이미 계산한 verts 사용) ----
    posed = trimesh.Trimesh(vertices=verts[f], faces=faces, process=False)
    posed_path = out / f"smpl_frame{f}.obj"
    posed.export(str(posed_path))
    h = float(verts[f][:, 1].max() - verts[f][:, 1].min())
    print(f"자세 메쉬: {posed_path}  (세로 크기 {h:.3f})")

    # ---- T포즈 메쉬 (smplx forward, betas 평균 사용) ----
    import smplx
    model = smplx.create(str(Path(a.smpl_dir).parent), model_type="smpl",
                         gender="neutral", batch_size=1)
    mean_betas = torch.tensor(betas.mean(0, keepdims=True), dtype=torch.float32)
    with torch.no_grad():
        o = model(betas=mean_betas)
    tpose = trimesh.Trimesh(vertices=o.vertices[0].numpy(), faces=faces, process=False)
    tpose_path = out / "smpl_tpose.obj"
    tpose.export(str(tpose_path))
    print(f"T포즈 메쉬: {tpose_path}")

    # ---- 관절 위치 (아마추어 생성용) ----
    with open(Path(a.smpl_dir) / "SMPL_NEUTRAL.pkl", "rb") as fp:
        smpl_data = pickle.load(fp, encoding="latin1")
    J = smpl_data["J_regressor"]
    if hasattr(J, "toarray"):
        J = J.toarray()
    joints_posed = np.einsum("jv,vc->jc", np.asarray(J, dtype=np.float64), verts[f])
    joints_tpose = np.einsum("jv,vc->jc", np.asarray(J, dtype=np.float64),
                             o.vertices[0].numpy().astype(np.float64))
    with open(out / f"joints_frame{f}.json", "w") as fp:
        json.dump({"posed": joints_posed.tolist(),
                   "tpose": joints_tpose.tolist(),
                   "frame": f, "betas_mean": betas.mean(0).tolist()}, fp, indent=2)
    print(f"관절: {out / f'joints_frame{f}.json'}")

    print("\n다음 단계: 이 OBJ 들과 TRELLIS GLB 를 Blender 에서 겹쳐 스케일·자세 차이를 확인하세요.")


if __name__ == "__main__":
    main()
