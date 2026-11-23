"""transferred.blend 의 TRELLIS 메쉬(geometry_0, 패킹된 텍스처 포함)만 rest 형상 그대로 GLB 로 내보낸다 (원본 blend 는 저장하지 않음).
  Blender --background --python tools/site/site_blend_to_glb.py -- <06_rig/<샘플>/transferred.blend> <out.glb>
2026-11-23 — 학교 좀비 2종(teacher · student)의 TRELLIS GLB 가 맥에 없어(Pod 볼륨에만) 리그 blend 에서 같은 메쉬 · 패킹 텍스처를 되살려
site_render_glb.py 에 넣었다(정점 수 GLB 와 같음: teacher 957,730 · student 730,561)."""
import bpy, sys
argv = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.open_mainfile(filepath=argv[0])
g = bpy.data.objects["geometry_0"]
for m in list(g.modifiers):          # 아마추어 변형 없이 rest 형상
    g.modifiers.remove(m)
mw = g.matrix_world.copy()
g.parent = None
g.matrix_world = mw
for o in bpy.data.objects:
    o.select_set(o is g)
bpy.context.view_layer.objects.active = g
bpy.ops.export_scene.gltf(filepath=argv[1], use_selection=True, export_format="GLB", export_skins=False,
                          export_animations=False, export_apply=False)
print("GLB_DONE", argv[1], len(g.data.vertices))
