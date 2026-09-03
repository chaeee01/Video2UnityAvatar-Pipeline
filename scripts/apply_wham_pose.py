"""
SMPL 리깅 4단계: WHAM pose 시퀀스를 리깅된 좀비에 재생.

transferred.blend 의 SMPL_rig 에 WHAM pose(69프레임)를 키프레임으로 굽습니다.
리그의 rest 자세 = frame 3 이므로, 각 프레임의 회전을 frame 3 기준 상대
회전(delta)으로 변환해 적용합니다. 좌표계는 SMPL_body 오브젝트의 월드 회전을
읽어 자동 변환합니다 (정렬 때 적용한 X-90 등을 수동 지정할 필요 없음).

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background \
      --python apply_wham_pose.py -- \
      --blend ~/Desktop/transferred.blend \
      --npz ~/Desktop/wham_pose.npz \
      --out ~/Desktop/animated.blend
"""
import argparse
import sys

import bpy
import numpy as np
from mathutils import Matrix

SMPL_PARENTS = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9,
                12, 13, 14, 16, 17, 18, 19, 20, 21]
SMPL_NAMES = ["Pelvis", "L_Hip", "R_Hip", "Spine1", "L_Knee", "R_Knee",
              "Spine2", "L_Ankle", "R_Ankle", "Spine3", "L_Foot", "R_Foot",
              "Neck", "L_Collar", "R_Collar", "Head", "L_Shoulder",
              "R_Shoulder", "L_Elbow", "R_Elbow", "L_Wrist", "R_Wrist",
              "L_Hand", "R_Hand"]


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--npz", required=True, help="wham_pose.npz (pose, trans)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rig-name", default="SMPL_rig")
    ap.add_argument("--smpl-name", default="SMPL_body")
    ap.add_argument("--frame", type=int, default=3,
                    help="리그 rest 에 해당하는 프레임 (메쉬 생성 프레임)")
    ap.add_argument("--fps", type=int, default=24)
    return ap.parse_args(argv)


def rodrigues(v):
    """axis-angle (3,) -> 회전행렬 (3,3)"""
    theta = np.linalg.norm(v)
    if theta < 1e-8:
        return np.eye(3)
    k = v / theta
    K = np.array([[0, -k[2], k[1]],
                  [k[2], 0, -k[0]],
                  [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(theta) * K + (1 - np.cos(theta)) * (K @ K)


def global_rots(pose_f):
    """(24,3) axis-angle -> 각 관절의 전역 회전 리스트"""
    Rg = [None] * 24
    for i in range(24):
        Rl = rodrigues(pose_f[i])
        p = SMPL_PARENTS[i]
        Rg[i] = Rl if p < 0 else Rg[p] @ Rl
    return Rg


def main():
    a = parse_args()
    bpy.ops.wm.open_mainfile(filepath=a.blend)

    rig = bpy.data.objects.get(a.rig_name)
    smpl = bpy.data.objects.get(a.smpl_name)
    if rig is None:
        raise RuntimeError(f"{a.rig_name} 없음")

    data = np.load(a.npz)
    pose = data["pose"].reshape(-1, 24, 3)   # (T,24,3)
    trans = data["trans"]                    # (T,3)
    T = len(pose)
    ref = a.frame
    print(f"[1/3] pose {pose.shape}, 기준 프레임 {ref}")

    # 좌표 변환: WHAM 공간 -> 아마추어(월드) 공간
    if smpl is not None:
        mw = smpl.matrix_world
        Rw = np.array(mw.to_3x3().normalized())
        scale = mw.to_scale()[0]
    else:
        from math import radians
        Rw = np.array(Matrix.Rotation(radians(-90), 3, "X"))
        scale = 1.0
    print(f"[2/3] 좌표 변환 회전 확보 (scale {scale:.4f})")

    # 본 rest 회전 (아마추어 공간)
    B = {}
    for name in SMPL_NAMES:
        B[name] = np.array(rig.data.bones[name].matrix_local.to_3x3())

    Rg_ref = global_rots(pose[ref])

    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"

    print(f"[3/3] {T}프레임 베이킹")
    pelvis_B = B["Pelvis"]
    for f in range(T):
        Rg_f = global_rots(pose[f])
        Rd = [Rw @ Rg_f[i] @ Rg_ref[i].T @ Rw.T for i in range(24)]
        for i, name in enumerate(SMPL_NAMES):
            p = SMPL_PARENTS[i]
            Rd_rel = Rd[i] if p < 0 else Rd[p].T @ Rd[i]
            basis = B[name].T @ Rd_rel @ B[name]
            pb = rig.pose.bones[name]
            pb.rotation_quaternion = Matrix(basis.tolist()).to_quaternion()
            pb.keyframe_insert("rotation_quaternion", frame=f)
        # 루트 이동 (frame ref 기준 상대)
        t = scale * (Rw @ (trans[f] - trans[ref]))
        loc = pelvis_B.T @ t
        pb = rig.pose.bones["Pelvis"]
        pb.location = loc.tolist()
        pb.keyframe_insert("location", frame=f)
        if f % 10 == 0:
            print(f"  frame {f}/{T-1}")

    scn = bpy.context.scene
    scn.render.fps = a.fps
    scn.frame_start = 0
    scn.frame_end = T - 1
    scn.frame_set(0)
    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.wm.save_as_mainfile(filepath=a.out)
    print(f"\n저장: {a.out}")
    print("Blender 로 열어 Spacebar 로 재생하세요. 원본 영상과 나란히 비교.")


if __name__ == "__main__":
    main()
