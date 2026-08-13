"""
SMPL 포즈 파라미터를 애니메이션 FBX 로 변환합니다. Blender 의 bpy 만 사용하므로
Autodesk FBX SDK 가 필요 없습니다.

실행 (맥):
  /Applications/Blender.app/Contents/MacOS/Blender --background --python smpl_pkl_to_fbx.py -- \
      --pkl ./motions/zombie.pkl \
      --fbx "/경로/SMPL_m_unityDoubleBlends_lbs_10_scale5_207_v1.0.0.fbx" \
      --out ./output/zombie_anim.fbx

동작 원리
  SMPL Unity FBX 는 본의 rest 방향이 SMPL 의 관절 좌표계와 일치하도록 제작되어 있어,
  축각(axis-angle) 파라미터를 pose bone 의 쿼터니언에 그대로 넣으면 됩니다.
  (공식 SMPL-X Blender 애드온도 같은 방식입니다.)
  결과가 뒤틀리면 --bone-space 를 붙여 rest 행렬 보정을 적용해 보세요.
"""
import argparse
import pickle
import sys
from math import radians

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

# SMPL 24 관절 순서. FBX 본 이름의 접미사와 대응합니다.
SMPL_JOINT_SUFFIX = [
    "Pelvis", "L_Hip", "R_Hip", "Spine1", "L_Knee", "R_Knee", "Spine2",
    "L_Ankle", "R_Ankle", "Spine3", "L_Foot", "R_Foot", "Neck",
    "L_Collar", "R_Collar", "Head", "L_Shoulder", "R_Shoulder",
    "L_Elbow", "R_Elbow", "L_Wrist", "R_Wrist", "L_Hand", "R_Hand",
]


def parse_args() -> argparse.Namespace:
    # Blender 는 -- 뒤의 인자만 스크립트로 넘겨줍니다
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", required=True, help="smpl_poses/smpl_trans 가 든 pkl")
    ap.add_argument("--fbx", required=True, help="SMPL Unity 템플릿 FBX")
    ap.add_argument("--out", required=True, help="출력 FBX")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--trans-scale", type=float, default=1.0,
                    help="루트 이동 스케일. 어댑터에서 --scale 1 로 뽑았다면 1.0")
    ap.add_argument("--no-trans", action="store_true",
                    help="제자리 애니메이션으로 만들기 (루트 이동 제거)")
    ap.add_argument("--bone-space", action="store_true",
                    help="rest 행렬 보정 적용 (기본 방식이 뒤틀릴 때)")
    return ap.parse_args(argv)


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.armatures, bpy.data.actions):
        for item in list(block):
            block.remove(item)


def find_armature():
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            return obj
    raise RuntimeError("FBX 안에서 아마추어를 찾지 못했습니다.")


def resolve_bone_names(arm) -> list:
    """'m_avg_Pelvis' 처럼 접두사가 붙은 실제 본 이름을 찾아 순서대로 반환합니다."""
    names = [b.name for b in arm.pose.bones]
    resolved = []
    for suffix in SMPL_JOINT_SUFFIX:
        match = [n for n in names if n.endswith(suffix)]
        if not match:
            raise RuntimeError(f"본을 찾지 못했습니다: {suffix}\n사용 가능한 본: {names[:10]} ...")
        # 가장 짧은 것 = 정확히 그 관절 (Spine1 vs Spine10 같은 오매칭 방지)
        resolved.append(min(match, key=len))
    return resolved


def axis_angle_to_quat(rod) -> Quaternion:
    v = Vector((float(rod[0]), float(rod[1]), float(rod[2])))
    angle = v.length
    if angle < 1e-8:
        return Quaternion((1.0, 0.0, 0.0, 0.0))
    return Quaternion(v.normalized(), angle)


def main() -> None:
    a = parse_args()

    with open(a.pkl, "rb") as f:
        data = pickle.load(f)

    poses = np.asarray(data["smpl_poses"], dtype=np.float64)   # (T, 72)
    trans = np.asarray(data["smpl_trans"], dtype=np.float64)   # (T, 3)
    T = len(poses)
    print(f"[info] 프레임 {T}, 포즈 {poses.shape}")

    clear_scene()
    bpy.ops.import_scene.fbx(filepath=a.fbx, automatic_bone_orientation=False, axis_forward="-Z", axis_up="Y")

    arm = find_armature()
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")

    bone_names = resolve_bone_names(arm)
    print(f"[info] 본 매핑 예시: {bone_names[:4]} ...")

    for name in bone_names:
        arm.pose.bones[name].rotation_mode = "QUATERNION"

    scene = bpy.context.scene
    scene.render.fps = a.fps
    scene.frame_start = 1
    scene.frame_end = T

    # rest 행렬 보정용 (옵션)
    rest_rot = {}
    if a.bone_space:
        for name in bone_names:
            rest_rot[name] = arm.pose.bones[name].bone.matrix_local.to_3x3()

    for t in range(T):
        scene.frame_set(t + 1)

        for j, name in enumerate(bone_names):
            pb = arm.pose.bones[name]
            q = axis_angle_to_quat(poses[t, j * 3:(j + 1) * 3])

            if a.bone_space:
                B = rest_rot[name]
                m = B.inverted() @ q.to_matrix() @ B
                q = m.to_quaternion()

            pb.rotation_quaternion = q
            pb.keyframe_insert("rotation_quaternion", frame=t + 1)

        # 루트 이동은 아마추어 오브젝트 자체에 적용합니다.
        # 본 로컬 좌표 변환을 피할 수 있어 훨씬 안전합니다.
        if not a.no_trans:
            tr = trans[t] * a.trans_scale
            # SMPL 은 Y-up, Blender 는 Z-up 이므로 축을 바꿔줍니다
            arm.location = Vector((float(tr[0]), -float(tr[2]), float(tr[1])))
            arm.keyframe_insert("location", frame=t + 1)

    bpy.ops.object.mode_set(mode="OBJECT")

    bpy.ops.export_scene.fbx(
        filepath=a.out,
        use_selection=False,
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        armature_nodetype="NULL",
        axis_forward="-Z",
        axis_up="Y",
    )
    print(f"[done] 저장: {a.out}")


if __name__ == "__main__":
    main()
