"""
SMPL 리깅 4단계: WHAM pose 시퀀스를 리깅된 좀비에 재생.

transferred.blend 의 SMPL_rig 에 WHAM pose(69프레임)를 키프레임으로 굽습니다.
리그의 rest 자세 = frame 3 이므로, 각 프레임의 회전을 frame 3 기준 상대
회전(delta)으로 변환해 적용합니다. 좌표계는 SMPL_body 오브젝트의 월드 회전을
읽어 자동 변환합니다 (정렬 때 적용한 X-90 등을 수동 지정할 필요 없음).

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background \
      --python apply_wham_pose.py -- \
      --blend ~/data/06_rig/zombie_sample1/transferred.blend \
      --npz ~/data/06_rig/zombie_sample1/wham_pose.npz \
      --out ~/data/06_rig/zombie_sample1/animated.blend

**다른 클립의 동작을 굽기 (모션 트랙, 2026-10-12~).** 리그를 만든 클립이 아닌 클립의 pose 를
구울 때는 기준 자세를 그 클립에서 찾을 수 없다. 리그 옆의 rest_pose.json(make_rest_pose.py)
을 --ref-pose 로 준다:

      --blend ~/data/06_rig/walker_walk_02/transferred.blend \
      --npz   ~/data/06_rig/walker/motions/idle/wham_pose.npz \
      --ref-pose ~/data/06_rig/walker_walk_02/rest_pose.json \
      --action-name idle --height-ratio 1.0 \
      --out   ~/data/06_rig/walker/motions/idle/animated.blend

회전은 그 기준 자세 대비 상대 회전으로, 루트 이동은 **클립의 첫 프레임을 원점**으로 한다
(방향은 리그 기준 자세 그대로). 리그의 rest 가 첫 프레임 자세가 아니므로 그 차이는
rest_pose.json 의 (trans_first - trans_ref) 로 메운다 — 모션 클립의 첫 프레임이 리그 클립의
첫 프레임과 같은 자세라는 가정이다(make_rest_pose.py 독스트링). --height-ratio 는
리그 체형의 신장 ÷ 모션 클립 체형의 신장이다 (betas 가 다르면 보폭이 달라야 한다).

첫 프레임이 선 자세가 아니면(누워서 시작하는 get_up 등) 위 가정이 깨져 몸이 뜬다.
--ground-align 은 루트 높이만 옮겨 처음 · 끝의 메쉬 최저점을 바닥에 맞춘다 (ground_align.py, 기본 꺼짐).
"""
import argparse
import json
import sys
from pathlib import Path

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
    ap.add_argument("--ref-pose", default=None,
                    help="rest_pose.json — 기준 자세를 다른 클립에서 받는다 (모션 트랙). "
                         "주면 --frame 은 쓰지 않는다")
    ap.add_argument("--height-ratio", type=float, default=1.0,
                    help="루트 이동에 곱할 신장비 (리그 신장 ÷ 모션 클립 신장). --ref-pose 와 함께")
    ap.add_argument("--action-name", default=None, help="저장할 액션 이름 (기본: Blender 가 붙이는 이름)")
    ap.add_argument("--ground-align", action="store_true",
                    help="루트 높이를 옮겨 처음 · 끝 0.25초의 메쉬 최저점을 바닥(rest 메쉬 최저점)에 맞춘다 "
                         "(ground_align.py). 결과는 out 옆 ground_align.json")
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


def ground_align_root(rig, smpl_name, T, locs, pelvis_B):
    """구운 루트 이동에 프레임별 높이 보정을 더해 다시 키를 넣는다. 반환: 요약 dict."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from ground_align import WINDOW, lift, offsets

    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.name != smpl_name]
    mesh = max(meshes, key=lambda o: len(o.data.vertices))

    def low_z(me, mw):
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        M = np.array(mw)
        return float((co.reshape(-1, 3) @ M[2, :3] + M[2, 3]).min())

    floor = low_z(mesh.data, mesh.matrix_world)      # rest 메쉬 (변형 전)
    sc = bpy.context.scene
    k = min(WINDOW, T)
    ext, lows = [], []
    for f in range(T):
        sc.frame_set(f)
        hz = [(rig.matrix_world @ rig.pose.bones[n].head).z for n in SMPL_NAMES]
        ext.append(max(hz) - min(hz))
        ev = mesh.evaluated_get(bpy.context.evaluated_depsgraph_get())
        me = ev.to_mesh()
        lows.append(low_z(me, ev.matrix_world))
        ev.to_mesh_clear()
    lows = np.array(lows)
    off, info = offsets(lows[:k], lows[-k:], ext, floor)
    up = lift(lows + off, floor)                     # 보정 뒤에도 묻힌 프레임만 올린다
    off = off + up
    info.update(lift_max=round(float(up.max()), 4), lift_frames=int((up > 1e-6).sum()),
                max_abs=round(float(np.abs(off).max()), 4))
    Rinv = np.linalg.inv(np.array(rig.matrix_world.to_3x3()))
    pb = rig.pose.bones["Pelvis"]
    for f in range(T):
        pb.location = (locs[f] + pelvis_B.T @ (Rinv @ np.array([0.0, 0.0, off[f]]))).tolist()
        pb.keyframe_insert("location", frame=f)
    info.update(floor=round(floor, 4), mesh=mesh.name, frames=T,
                ext_first=round(float(np.mean(ext[:k])), 4), ext_last=round(float(np.mean(ext[-k:])), 4))
    return info


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
    if a.ref_pose:
        rp = json.load(open(a.ref_pose))
        ref_pose = np.asarray(rp["pose"], dtype=np.float64).reshape(24, 3)
        # 원점은 이 클립의 첫 프레임. 리그 rest(키프레임)와 첫 프레임 자세의 차이는 리그
        # 클립에서 잰 값으로 메운다.
        t_origin = trans[0]
        t_shift = np.asarray(rp["trans_first"], dtype=np.float64) - np.asarray(rp["trans_ref"], dtype=np.float64)
        ratio = a.height_ratio
        print(f"[1/3] pose {pose.shape}, 기준 자세 {rp['rig_sample']} f{rp['frame']} "
              f"(다른 클립), 신장비 {ratio}")
    else:
        ref = a.frame
        ref_pose = pose[ref]
        t_origin, t_shift, ratio = trans[ref], np.zeros(3), 1.0
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

    Rg_ref = global_rots(ref_pose)

    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"

    print(f"[3/3] {T}프레임 베이킹")
    pelvis_B = B["Pelvis"]
    locs = []
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
        # 루트 이동 (기준 대비 상대). 같은 클립이면 (trans[f] - trans[ref]) 그대로다.
        t = scale * (Rw @ (ratio * (trans[f] - t_origin) + t_shift))
        loc = pelvis_B.T @ t
        locs.append(loc)
        pb = rig.pose.bones["Pelvis"]
        pb.location = loc.tolist()
        pb.keyframe_insert("location", frame=f)
        if f % 10 == 0:
            print(f"  frame {f}/{T-1}")

    if a.ground_align:
        info = ground_align_root(rig, a.smpl_name, T, locs, pelvis_B)
        Path(a.out).with_name("ground_align.json").write_text(json.dumps(info, indent=1, ensure_ascii=False))
        print(f"바닥 정렬: 시작 {info['o0']:+.4f} · 끝 {info['o1']:+.4f} ({info['mode']}), 최대 |보정| {info['max_abs']}"
              f", 묻힘 들어 올림 최대 {info['lift_max']} ({info['lift_frames']}프레임)")

    if a.action_name and rig.animation_data and rig.animation_data.action:
        rig.animation_data.action.name = a.action_name
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
