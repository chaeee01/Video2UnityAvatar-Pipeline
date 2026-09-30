"""
동작 재생 렌더 (5-5 보조): animated.blend 를 프레임 시퀀스로 렌더한다.

Unity 반입 전에 동작이 제대로 실렸는지 맥북에서 확인하기 위한 것이다.
텍스처를 그대로 두고 렌더하므로 외형과 동작을 함께 본다.

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background \
      --python render_playback.py -- \
      --blend ~/data/06_rig/char_shuffle/animated.blend \
      --out   ~/data/06_rig/char_shuffle/_playback

출력: <out>/0001.png … (ffmpeg 로 mp4 로 묶는다)

SMPL_body(보조 메쉬)는 숨긴다 — 리깅에 쓰인 참조일 뿐 결과물이 아니다.
"""
import argparse
import math
import os
import sys

import bpy
import mathutils


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True, help="animated.blend (5-5 출력)")
    ap.add_argument("--out", required=True, help="프레임 출력 폴더")
    ap.add_argument("--smpl-name", default="SMPL_body", help="숨길 보조 메쉬")
    ap.add_argument("--res", type=int, nargs=2, default=[540, 960], help="해상도 W H")
    ap.add_argument("--view", default="front", choices=["front", "side"])
    ap.add_argument("--samples", type=int, default=16, help="EEVEE 샘플 수")
    return ap.parse_args(argv)


def scene_bounds(objs):
    mn = mathutils.Vector((1e9,) * 3)
    mx = mathutils.Vector((-1e9,) * 3)
    for o in objs:
        for c in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(c)
            mn = mathutils.Vector(min(mn[i], w[i]) for i in range(3))
            mx = mathutils.Vector(max(mx[i], w[i]) for i in range(3))
    return mn, mx


def main():
    a = parse_args()
    out = os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=os.path.expanduser(a.blend))
    sc = bpy.context.scene

    hidden = None
    for ob in list(bpy.data.objects):
        if ob.type == "MESH" and a.smpl_name.lower() in ob.name.lower():
            ob.hide_render = True
            hidden = ob.name
    print(f"숨김: {hidden or '(없음)'}")

    meshes = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render]
    if not meshes:
        raise SystemExit("렌더할 메쉬가 없습니다")
    print(f"렌더 대상: {', '.join(o.name for o in meshes)}")

    # 카메라는 **전체 프레임의 움직임 범위**가 아니라 rest 자세 기준으로 잡는다.
    # 걸어 나가는 동작이라 프레임마다 위치가 달라지는데, 매 프레임 맞추면
    # 카메라가 따라다녀 동작이 안 보인다. 고정 카메라에 여유를 크게 둔다.
    mn, mx = scene_bounds(meshes)
    ctr, size = (mn + mx) / 2, max(mx - mn)

    cam = bpy.data.objects.new("pb_cam", bpy.data.cameras.new("pb_cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = size * 2.0        # 이동 여유
    r = math.radians(0 if a.view == "front" else 90)
    cam.location = (ctr.x + math.sin(r) * size * 3, ctr.y - math.cos(r) * size * 3, ctr.z)
    cam.rotation_euler = (math.radians(90), 0, r)

    for ang, e in ((40, 3.0), (-120, 1.5)):
        li = bpy.data.objects.new(f"pb_sun{ang}", bpy.data.lights.new(f"pb_sun{ang}", "SUN"))
        li.data.energy = e
        sc.collection.objects.link(li)
        li.rotation_euler = (math.radians(55), 0, math.radians(ang))

    sc.render.engine = "BLENDER_EEVEE_NEXT"
    try:
        sc.eevee.taa_render_samples = a.samples
    except AttributeError:
        pass
    sc.render.film_transparent = False
    sc.world = sc.world or bpy.data.worlds.new("pb_world")
    sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.18, 0.18, 0.2, 1)

    sc.render.resolution_x, sc.render.resolution_y = a.res
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = os.path.join(out, "")
    print(f"프레임 {sc.frame_start}-{sc.frame_end}, {a.res[0]}x{a.res[1]}, {a.view}")
    bpy.ops.render.render(animation=True)
    print(f"완료: {out}")


if __name__ == "__main__":
    main()
