"""
SMPL 애니메이션을 Mixamo 리그로 리타게팅합니다. 애드온 없이 bpy 만 사용합니다.

  /Applications/Blender.app/Contents/MacOS/Blender --background --python retarget_smpl_to_mixamo.py -- \
      --src ./output/zombie_anim2.fbx \
      --tgt ~/Downloads/zombie_tpose.fbx \
      --out ./output/zombie_final.fbx \
      --root-fix-x 180

동작 원리
  본 회전을 그대로 복사하면 두 리그의 rest 방향이 달라 뒤틀립니다.
  그래서 "rest 대비 얼마나 회전했는가"를 옮깁니다.

      offset      = src_rest_rot⁻¹ @ tgt_rest_rot
      tgt_pose    = src_pose_rot @ offset

  이렇게 하면 팔 길이나 본 개수가 달라도 자세가 보존됩니다.
  Unity Humanoid 근육 변환을 거치지 않으므로 그 단계의 문제도 사라집니다.
"""
import argparse
import sys

import bpy
from mathutils import Matrix, Vector

# SMPL 본 접미사 -> Mixamo 본 이름
# L_Hand / R_Hand 는 SMPL 에 손가락이 없어 생략합니다.
BONE_MAP = {
    "Pelvis":     "Hips",
    "L_Hip":      "LeftUpLeg",
    "R_Hip":      "RightUpLeg",
    "Spine1":     "Spine",
    "L_Knee":     "LeftLeg",
    "R_Knee":     "RightLeg",
    "Spine2":     "Spine1",
    "L_Ankle":    "LeftFoot",
    "R_Ankle":    "RightFoot",
    "Spine3":     "Spine2",
    "L_Foot":     "LeftToeBase",
    "R_Foot":     "RightToeBase",
    "Neck":       "Neck",
    "L_Collar":   "LeftShoulder",
    "R_Collar":   "RightShoulder",
    "Head":       "Head",
    "L_Shoulder": "LeftArm",
    "R_Shoulder": "RightArm",
    "L_Elbow":    "LeftForeArm",
    "R_Elbow":    "RightForeArm",
    "L_Wrist":    "LeftHand",
    "R_Wrist":    "RightHand",
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="SMPL 애니메이션 FBX")
    ap.add_argument("--tgt", required=True, help="Mixamo 리깅된 캐릭터 FBX")
    ap.add_argument("--out", required=True)
    ap.add_argument("--root-fix-x", type=float, default=0.0,
                    help="뒤집힘 보정. 거꾸로면 180, 옆으로 누우면 ±90")
    ap.add_argument("--copy-root-loc", action="store_true",
                    help="루트 이동도 복사 (기본은 제자리)")
    return ap.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for coll in (bpy.data.meshes, bpy.data.armatures, bpy.data.actions,
                 bpy.data.objects, bpy.data.materials):
        for item in list(coll):
            try:
                coll.remove(item)
            except Exception:
                pass


def import_fbx(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path, use_custom_props=False,
                             ignore_leaf_bones=True, force_connect_children=False)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next((o for o in new if o.type == "ARMATURE"), None)
    if arm is None:
        raise RuntimeError(f"아마추어를 찾지 못했습니다: {path}")
    return arm, new


def find_bone(arm, needle, exact_prefix=None):
    """접미사 또는 mixamorig 접두사로 본을 찾습니다."""
    names = [b.name for b in arm.pose.bones]
    if exact_prefix:
        cands = [n for n in names if n.endswith(":" + needle) or n == needle
                 or n.endswith("_" + needle)]
    else:
        cands = [n for n in names if n.endswith(needle)]
    if not cands:
        return None
    return min(cands, key=len)


def main():
    a = parse_args()
    clear_scene()

    print("[1/5] SMPL 애니메이션 임포트")
    src_arm, _ = import_fbx(a.src)
    src_arm.name = "SRC_ARM"

    print("[2/5] 캐릭터 임포트")
    tgt_arm, _ = import_fbx(a.tgt)
    tgt_arm.name = "TGT_ARM"

    # ---- 본 이름 해석 ----
    pairs = []
    missing = []
    for smpl_suffix, mixamo_name in BONE_MAP.items():
        s = find_bone(src_arm, smpl_suffix)
        t = find_bone(tgt_arm, mixamo_name, exact_prefix=True)
        if s and t:
            pairs.append((s, t))
        else:
            missing.append((smpl_suffix, mixamo_name, s, t))

    print(f"[3/5] 매핑 {len(pairs)}쌍")
    for smpl, mix, s, t in missing:
        print(f"    누락: {smpl} -> {mix}  (찾은값 src={s} tgt={t})")
    if len(pairs) < 15:
        print("    본 목록(src):", [b.name for b in src_arm.pose.bones][:30])
        print("    본 목록(tgt):", [b.name for b in tgt_arm.pose.bones][:30])
        raise RuntimeError("매핑이 너무 적습니다. 본 이름을 확인하세요.")

    # ---- rest 방향 차이(offset) 계산 ----
    offsets = {}
    for s_name, t_name in pairs:
        s_rest = src_arm.data.bones[s_name].matrix_local.to_3x3()
        t_rest = tgt_arm.data.bones[t_name].matrix_local.to_3x3()
        offsets[t_name] = s_rest.inverted() @ t_rest

    # ---- 프레임 범위 ----
    act = src_arm.animation_data.action if src_arm.animation_data else None
    if act is None:
        raise RuntimeError("소스에 애니메이션이 없습니다.")
    f0, f1 = (int(round(v)) for v in act.frame_range)
    print(f"[4/5] 프레임 {f0}~{f1} 베이킹")

    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = f0, f1

    # 뒤집힘 보정: 타깃 아마추어 오브젝트에 회전을 걸어 두면
    # 아래 계산이 그 위에서 이루어져 자연스럽게 반영됩니다.
    root_fix = Matrix.Rotation(a.root_fix_x * 3.14159265358979 / 180.0, 3, "X")

    for pb in tgt_arm.pose.bones:
        pb.rotation_mode = "QUATERNION"

    bpy.context.view_layer.objects.active = tgt_arm
    bpy.ops.object.mode_set(mode="POSE")

    # 부모부터 처리해야 자식 계산이 맞습니다
    order = sorted(pairs, key=lambda p: len(tgt_arm.pose.bones[p[1]].parent_recursive))

    hips_src, hips_tgt = pairs[0]
    hips_rest_loc = tgt_arm.pose.bones[hips_tgt].bone.head_local.copy()

    for f in range(f0, f1 + 1):
        scene.frame_set(f)

        for s_name, t_name in order:
            s_pb = src_arm.pose.bones[s_name]
            t_pb = tgt_arm.pose.bones[t_name]

            rot = s_pb.matrix.to_3x3() @ offsets[t_name]
            if t_pb.parent is None:
                rot = root_fix @ rot

            loc = t_pb.matrix.translation.copy()
            t_pb.matrix = Matrix.Translation(loc) @ rot.to_4x4()
            bpy.context.view_layer.update()

            t_pb.keyframe_insert("rotation_quaternion", frame=f)

        if a.copy_root_loc:
            s_hips = src_arm.pose.bones[hips_src]
            t_hips = tgt_arm.pose.bones[hips_tgt]
            delta = s_hips.matrix.translation - src_arm.pose.bones[hips_src].bone.head_local
            t_hips.location = root_fix @ delta
            t_hips.keyframe_insert("location", frame=f)

    bpy.ops.object.mode_set(mode="OBJECT")

    # ---- 소스 제거 후 캐릭터만 내보내기 ----
    print("[5/5] 내보내기")
    bpy.ops.object.select_all(action="DESELECT")
    src_arm.select_set(True)
    for child in src_arm.children:
        child.select_set(True)
    bpy.ops.object.delete()

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.fbx(
        filepath=a.out,
        use_selection=True,
        add_leaf_bones=False,
        bake_anim=True,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        armature_nodetype="NULL",
        path_mode="COPY",
        embed_textures=True,
    )
    print(f"[done] 저장: {a.out}")


if __name__ == "__main__":
    main()
