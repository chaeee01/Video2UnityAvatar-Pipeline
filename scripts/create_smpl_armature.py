"""
SMPL 리깅 3단계-①②: 아마추어 생성 + SMPL 몸체 바인딩.

aligned.blend(2단계 출력)를 열어 joints json의 24관절 위치에 SMPL 본 계층을
세우고, SMPL 메쉬를 자동 웨이트로 바인딩합니다.

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background \
      --python create_smpl_armature.py -- \
      --blend ~/Desktop/aligned.blend \
      --joints ~/Desktop/06_smpl_mesh/joints_frame3.json \
      --out ~/Desktop/rigged.blend

좌표계 자동 보정:
  json 관절은 OBJ 원본 좌표계이고 메쉬는 정렬 변환이 적용된 상태입니다.
  후보 회전(0, ±90, 180도 X축)을 시험해 관절→메쉬 최근접 거리가 최소인
  변환을 자동 선택하므로, 임포터 축 변환을 수동으로 알아낼 필요가 없습니다.

옵션:
  --weights weights.npy   SMPL 공식 LBS 웨이트(6890x24)가 있으면 자동 웨이트
                          대신 사용 (추후 Pod에서 추출 가능)
"""
import argparse
import json
import sys
from math import radians

import bpy
import numpy as np
from mathutils import Matrix, Vector, kdtree

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
    ap.add_argument("--blend", required=True, help="aligned.blend (2단계 출력)")
    ap.add_argument("--joints", required=True, help="joints_frameN.json")
    ap.add_argument("--out", required=True, help="출력 rigged.blend")
    ap.add_argument("--weights", default=None, help="공식 LBS 웨이트 npy (선택)")
    ap.add_argument("--smpl-name", default="SMPL_body")
    return ap.parse_args(argv)


def calibrate_joints(joints_raw, smpl_obj):
    """후보 회전을 시험해 메쉬와 가장 잘 맞는 관절 월드 좌표를 찾습니다."""
    mesh = smpl_obj.data
    mw = smpl_obj.matrix_world
    kd = kdtree.KDTree(len(mesh.vertices))
    for i, v in enumerate(mesh.vertices):
        kd.insert(mw @ v.co, i)
    kd.balance()

    candidates = {
        "identity": Matrix.Identity(3),
        "X+90": Matrix.Rotation(radians(90), 3, "X"),
        "X-90": Matrix.Rotation(radians(-90), 3, "X"),
        "X180": Matrix.Rotation(radians(180), 3, "X"),
    }
    best = None
    for name, R in candidates.items():
        # 관절(OBJ 로컬)을 메쉬와 같은 오브젝트 변환으로 월드에 배치
        # 임포터가 넣었을 수 있는 회전 R 을 후보로 끼워 넣음
        pts = [mw @ (R @ Vector(j)) for j in joints_raw]
        d = float(np.mean([(kd.find(p)[0] - p).length for p in pts]))
        print(f"  후보 {name}: 평균 관절-메쉬 거리 {d:.4f}")
        if best is None or d < best[2]:
            best = (name, pts, d)
    print(f"  선택: {best[0]} (거리 {best[2]:.4f})")
    if best[2] > 0.2:
        print("  경고: 거리가 큽니다. 관절이 메쉬 밖에 있을 수 있으니 결과를 확인하세요.")
    return best[1]


def build_armature(joint_world):
    bpy.ops.object.armature_add(enter_editmode=True)
    arm_obj = bpy.context.object
    arm_obj.name = "SMPL_rig"
    arm = arm_obj.data
    arm.name = "SMPL_rig"

    eb = arm.edit_bones
    eb.remove(eb[0])  # 기본 본 제거

    children = {i: [] for i in range(24)}
    for i, p in enumerate(SMPL_PARENTS):
        if p >= 0:
            children[p].append(i)

    bones = []
    for i, name in enumerate(SMPL_NAMES):
        b = eb.new(name)
        b.head = joint_world[i]
        if children[i]:
            tail = Vector((0, 0, 0))
            for c in children[i]:
                tail += joint_world[c]
            b.tail = tail / len(children[i])
        else:
            # 말단 본: 부모 방향으로 짧게 연장
            p = SMPL_PARENTS[i]
            direction = (joint_world[i] - joint_world[p]).normalized()
            b.tail = joint_world[i] + direction * 0.06
        bones.append(b)

    for i, p in enumerate(SMPL_PARENTS):
        if p >= 0:
            bones[i].parent = bones[p]
            bones[i].use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj


def bind_official_weights(smpl_obj, arm_obj, weights_path):
    W = np.load(weights_path)  # (6890, 24)
    if W.shape != (len(smpl_obj.data.vertices), 24):
        raise RuntimeError(f"웨이트 형상이 안 맞음: {W.shape}")
    for j, name in enumerate(SMPL_NAMES):
        vg = smpl_obj.vertex_groups.new(name=name)
        w_col = W[:, j]
        for vi in np.nonzero(w_col > 1e-4)[0]:
            vg.add([int(vi)], float(w_col[vi]), "REPLACE")
    mod = smpl_obj.modifiers.new("Armature", "ARMATURE")
    mod.object = arm_obj
    smpl_obj.parent = arm_obj


def main():
    a = parse_args()
    bpy.ops.wm.open_mainfile(filepath=a.blend)

    smpl = bpy.data.objects.get(a.smpl_name)
    if smpl is None:
        names = [o.name for o in bpy.data.objects if o.type == "MESH"]
        raise RuntimeError(f"{a.smpl_name} 없음. 메쉬 목록: {names}")

    with open(a.joints) as f:
        joints_raw = json.load(f)["posed"]  # 24 x 3, OBJ 좌표계
    print("[1/3] 관절 좌표계 보정")
    joint_world = calibrate_joints(joints_raw, smpl)

    print("[2/3] 아마추어 생성 (24본)")
    arm_obj = build_armature(joint_world)

    print("[3/3] SMPL 바인딩")
    if a.weights:
        print("  공식 웨이트 사용:", a.weights)
        bind_official_weights(smpl, arm_obj, a.weights)
    else:
        print("  Automatic Weights 사용")
        bpy.ops.object.select_all(action="DESELECT")
        smpl.select_set(True)
        arm_obj.select_set(True)
        bpy.context.view_layer.objects.active = arm_obj
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")

    n_groups = len(smpl.vertex_groups)
    print(f"  정점그룹 {n_groups}개 생성")

    bpy.ops.wm.save_as_mainfile(filepath=a.out)
    print(f"\n저장: {a.out}")
    print("확인: Blender에서 열어 SMPL_rig 선택 -> Pose Mode -> "
          "L_Shoulder 회전 시 SMPL 몸이 자연스럽게 따라오는지 보세요.")


if __name__ == "__main__":
    main()
