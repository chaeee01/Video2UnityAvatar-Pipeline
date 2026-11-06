"""TRELLIS.2 GLB 를 공개 페이지용으로 렌더 — 정지 1장 또는 턴테이블 PNG 시퀀스.
  Blender --background --python site_render_glb.py -- <glb> <출력 접두사> [--turntable N] [--res 1080]
정면(-Y 에서 +Y 를 봄), 회색 배경, 3점 조명, EEVEE. 모델은 원점 중심 · 바닥 z=최저점으로 맞춘다."""
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
glb, out = argv[0], argv[1]
turn = int(argv[argv.index("--turntable") + 1]) if "--turntable" in argv else 0
res = int(argv[argv.index("--res") + 1]) if "--res" in argv else 1080

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
pivot = bpy.data.objects.new("pivot", None)
bpy.context.scene.collection.objects.link(pivot)
for o in meshes:
    if o.parent is None:
        o.parent = pivot

dg = bpy.context.evaluated_depsgraph_get()
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
mn = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
mx = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
ctr = (mn + mx) / 2
pivot.location = (-ctr.x, -ctr.y, -mn.z)          # 발바닥을 z=0, 수평 중심을 원점으로
h = mx.z - mn.z
w = max(mx.x - mn.x, mx.y - mn.y)

sc = bpy.context.scene
sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys() else "BLENDER_EEVEE"
sc.render.resolution_x = sc.render.resolution_y = res
sc.render.film_transparent = False
sc.world = bpy.data.worlds.new("w")
sc.world.use_nodes = True
sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.55, 0.56, 0.58, 1)
sc.world.node_tree.nodes["Background"].inputs[1].default_value = 0.6
sc.view_settings.view_transform = "Standard"

cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.lens = 50
dist = max(h, w) * 1.55
cam.location = (0, -dist, h * 0.52)
cam.rotation_euler = (math.radians(90), 0, 0)
cam.data.shift_y = 0.0

for name, energy, loc in (("key", 4.0, (-1.5, -2.0, 2.2)), ("fill", 1.5, (2.0, -1.5, 1.2)), ("rim", 3.0, (0.5, 2.5, 2.4))):
    li = bpy.data.objects.new(name, bpy.data.lights.new(name, "SUN"))
    li.data.energy = energy
    li.location = loc
    li.rotation_euler = (Vector((0, 0, h * 0.5)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
    sc.collection.objects.link(li)

if turn:
    sc.frame_start, sc.frame_end = 1, turn
    pivot.rotation_euler = (0, 0, 0)
    pivot.keyframe_insert("rotation_euler", frame=1)
    pivot.rotation_euler = (0, 0, math.radians(360) * (turn - 1) / turn)
    pivot.keyframe_insert("rotation_euler", frame=turn)
    for fc in pivot.animation_data.action.fcurves:
        for k in fc.keyframe_points:
            k.interpolation = "LINEAR"
    sc.render.filepath = out + "_"
    sc.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(animation=True)
else:
    sc.render.filepath = out + ".png"
    sc.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
print("RENDER_DONE", out, "h", round(h, 3))
