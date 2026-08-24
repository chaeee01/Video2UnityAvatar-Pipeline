"""
SMPL 리깅 2단계: TRELLIS 메쉬와 SMPL 메쉬 자동 정렬.

오늘 수동 검증한 절차(회전 X-90 → 스케일 0.588 → 이동 Y-2.58)를 자동화합니다.
수치는 하드코딩하지 않고 바운딩박스에서 유도하므로 다른 영상에도 적용됩니다.

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background \
      --python align_smpl_to_trellis.py -- \
      --trellis ~/Downloads/sample_2026-08-03T073636.203.glb \
      --smpl ~/Desktop/06_smpl_mesh/smpl_frame3.obj \
      --out ~/Desktop/aligned.blend

검증된 기본값: --rot-x -90 (WHAM 카메라 좌표계 -> Z-up 보정)

출력:
  aligned.blend      정렬된 두 메쉬가 담긴 Blender 파일 (다음 단계 입력)
  aligned_params.json  적용된 변환 수치 기록 (재현성)
"""
import argparse
import json
import sys
from math import radians

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--trellis", required=True, help="TRELLIS GLB")
    ap.add_argument("--smpl", required=True, help="SMPL OBJ (generate_smpl_mesh.py 출력)")
    ap.add_argument("--out", required=True, help="출력 .blend 경로")
    ap.add_argument("--rot-x", type=float, default=-90.0,
                    help="SMPL 사전 회전(도). WHAM 카메라 좌표계 보정. 검증값 -90")
    ap.add_argument("--rot-z", type=float, default=0.0,
                    help="정면 방향 추가 보정이 필요하면 지정")
    return ap.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def import_and_get_meshes(path):
    """임포트하고 새로 생긴 메쉬 오브젝트들을 반환합니다."""
    before = set(bpy.data.objects)
    p = path.lower()
    if p.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    elif p.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=path)
    else:
        raise RuntimeError(f"지원하지 않는 형식: {path}")
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"메쉬를 찾지 못함: {path}")
    return meshes


def world_bounds(objs):
    """오브젝트들의 월드 좌표 바운딩박스 (min, max)."""
    pts = []
    bpy.context.view_layer.update()
    for o in objs:
        for corner in o.bound_box:
            pts.append(o.matrix_world @ Vector(corner))
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def main():
    a = parse_args()
    clear_scene()

    print("[1/4] 임포트")
    trellis_meshes = import_and_get_meshes(a.trellis)
    smpl_meshes = import_and_get_meshes(a.smpl)
    smpl = smpl_meshes[0]
    smpl.name = "SMPL_body"

    # ---- 2. SMPL 사전 회전 (카메라 좌표계 보정) ----
    print(f"[2/4] 회전 X {a.rot_x}도" + (f", Z {a.rot_z}도" if a.rot_z else ""))
    smpl.rotation_mode = "XYZ"
    smpl.rotation_euler = (radians(a.rot_x), 0.0, radians(a.rot_z))
    bpy.context.view_layer.update()

    # ---- 3. 스케일: 세로(Z) 높이를 일치시킴 ----
    t_lo, t_hi = world_bounds(trellis_meshes)
    s_lo, s_hi = world_bounds([smpl])
    t_h = t_hi.z - t_lo.z
    s_h = s_hi.z - s_lo.z
    scale = t_h / s_h
    smpl.scale = (scale,) * 3
    bpy.context.view_layer.update()
    print(f"[3/4] 스케일 {scale:.4f}  (TRELLIS 높이 {t_h:.3f} / SMPL 높이 {s_h:.3f})")

    # ---- 4. 이동: 바운딩박스 중심 정합 (바닥 기준 Z 정렬) ----
    s_lo, s_hi = world_bounds([smpl])
    t_center = (t_lo + t_hi) / 2
    s_center = (s_lo + s_hi) / 2
    offset = Vector((t_center.x - s_center.x,
                     t_center.y - s_center.y,
                     t_lo.z - s_lo.z))          # 바닥끼리 맞춤 (발 위치 우선)
    smpl.location = smpl.location + offset
    bpy.context.view_layer.update()
    print(f"[4/4] 이동 ({offset.x:.3f}, {offset.y:.3f}, {offset.z:.3f})")

    # ---- 검증 지표: 정렬 후 바운딩박스 겹침 정도 ----
    s_lo, s_hi = world_bounds([smpl])
    ix = max(0, min(t_hi.x, s_hi.x) - max(t_lo.x, s_lo.x))
    iy = max(0, min(t_hi.y, s_hi.y) - max(t_lo.y, s_lo.y))
    iz = max(0, min(t_hi.z, s_hi.z) - max(t_lo.z, s_lo.z))
    inter = ix * iy * iz
    vol_t = (t_hi.x-t_lo.x) * (t_hi.y-t_lo.y) * (t_hi.z-t_lo.z)
    vol_s = (s_hi.x-s_lo.x) * (s_hi.y-s_lo.y) * (s_hi.z-s_lo.z)
    iou = inter / (vol_t + vol_s - inter) if (vol_t + vol_s - inter) > 0 else 0
    print(f"바운딩박스 IoU: {iou:.3f}  (0.5 이상이면 정렬 양호)")

    params = {
        "rot_x": a.rot_x, "rot_z": a.rot_z,
        "scale": round(scale, 6),
        "offset": [round(v, 6) for v in offset],
        "bbox_iou": round(iou, 4),
        "trellis": a.trellis, "smpl": a.smpl,
    }
    out_json = a.out.rsplit(".", 1)[0] + "_params.json"
    with open(out_json, "w") as f:
        json.dump(params, f, indent=2)

    bpy.ops.wm.save_as_mainfile(filepath=a.out)
    print(f"\n저장: {a.out}")
    print(f"파라미터: {out_json}")


if __name__ == "__main__":
    main()
