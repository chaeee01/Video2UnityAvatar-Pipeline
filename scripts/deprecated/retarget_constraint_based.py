import argparse, sys
import bpy

BONE_MAP = {
    "Pelvis": "Hips", "L_Hip": "LeftUpLeg", "R_Hip": "RightUpLeg",
    "Spine1": "Spine", "L_Knee": "LeftLeg", "R_Knee": "RightLeg",
    "Spine2": "Spine1", "L_Ankle": "LeftFoot", "R_Ankle": "RightFoot",
    "Spine3": "Spine2", "Neck": "Neck", "Head": "Head",
    "L_Collar": "LeftShoulder", "R_Collar": "RightShoulder",
    "L_Shoulder": "LeftArm", "R_Shoulder": "RightArm",
    "L_Elbow": "LeftForeArm", "R_Elbow": "RightForeArm",
    "L_Wrist": "LeftHand", "R_Wrist": "RightHand",
}

argv = sys.argv[sys.argv.index("--")+1:]
ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--tgt", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args(argv)

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

def imp(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.fbx(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    return next(o for o in new if o.type == "ARMATURE")

src = imp(a.src); src.name = "SRC"
tgt = imp(a.tgt); tgt.name = "TGT"

def find(arm, needle):
    c = [b.name for b in arm.pose.bones if b.name.endswith(needle)]
    return min(c, key=len) if c else None

pairs = []
for s_sfx, t_name in BONE_MAP.items():
    s = find(src, s_sfx)
    t = find(tgt, t_name)
    if s and t:
        pairs.append((s, t))
    else:
        print(f"누락: {s_sfx}->{t_name} (src={s}, tgt={t})")
print(f"매핑 {len(pairs)}쌍")

# 핵심: 두 리그를 같은 rest 자세로 정렬한 뒤 컨스트레인트를 걸어야
# offset 없이도 자세가 보존됩니다. SMPL rest = T포즈, Mixamo rest = T포즈이므로
# world space Copy Rotation이 성립합니다.
bpy.context.view_layer.objects.active = tgt
bpy.ops.object.mode_set(mode="POSE")
for s_name, t_name in pairs:
    pb = tgt.pose.bones[t_name]
    con = pb.constraints.new("COPY_ROTATION")
    con.target = src
    con.subtarget = s_name
    con.target_space = "WORLD"
    con.owner_space = "WORLD"

act = src.animation_data.action
f0, f1 = (int(round(v)) for v in act.frame_range)
print(f"베이킹 {f0}~{f1}")
bpy.ops.nla.bake(frame_start=f0, frame_end=f1, only_selected=False,
                 visual_keying=True, clear_constraints=True, bake_types={"POSE"})
bpy.ops.object.mode_set(mode="OBJECT")

bpy.ops.object.select_all(action="DESELECT")
src.select_set(True)
for c in src.children:
    c.select_set(True)
bpy.ops.object.delete()

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.fbx(filepath=a.out, use_selection=True,
                         add_leaf_bones=False, bake_anim=True,
                         bake_anim_use_nla_strips=False,
                         bake_anim_use_all_actions=False)
print("저장:", a.out)
