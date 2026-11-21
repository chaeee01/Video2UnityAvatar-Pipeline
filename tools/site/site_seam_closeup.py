"""5-4b 수리 전후 근접 그림용 렌더 (2026-11-21) — tools/review/closeup.py 와 같은 카메라(정면 직교, Workbench 텍스처, 배경 0.3/0.3/0.32, 본 앞 3 단위)에
화면 중심 오프셋(dx 가로 · dz 세로, 정규화 단위)과 해상도를 더했다. 오프셋 0 · 해상도 800 이면 closeup.py 와 같은 그림이다.

  Blender --background --python tools/site/site_seam_closeup.py -- <blend> <출력 폴더> <해상도> <프레임:본:폭:dx:dz:이름> …

공개 페이지 사례 ② · README 의 그림을 만든 명령 (<R> = 렌더 폴더, <E> = ~/Desktop/3D_avatar_work/experiments/e2e_check):
  # 가랑이 — listener run_04b f34, 근접 Pelvis 폭 0.4 · 중심 (+0.02, −0.14), 전신 Pelvis 1.1
  … -- ~/data/06_rig/listener_apose_06/motions/listener_run_04b/animated.blend <R>/crotch 800 34:Pelvis:0.4:0.02:-0.14:pre 34:Pelvis:1.1:0:0:pre_full
  … -- <E>/review_1021/02_wfix/bake04b_a/animated.blend <R>/crotch 800 34:Pelvis:0.4:0.02:-0.14:post
  # 겨드랑이 — listener run(listener_x_stalker_run_fwd) f62, 근접 L_Shoulder 폭 0.4 · 중심 (0, −0.1), 전신 Pelvis 1.1
  … -- <E>/review_1019/01_listener_run_slide/transplant_stalker_run_fwd/animated.blend <R>/armpit 800 62:L_Shoulder:0.4:0:-0.1:pre 62:Pelvis:1.1:0:0:pre_full
  … -- ~/data/06_rig/listener_apose_06_wfix/motions/listener_x_stalker_run_fwd/animated.blend <R>/armpit 800 62:L_Shoulder:0.4:0:-0.1:post
그다음 tools/site/site_seam_compose.py <R> site/assets. 출처 · sha256 은 site/assets/manifest.md 와 docs/assets/seam_figures_1121.md.
"""
import bpy, sys, math
a = sys.argv[sys.argv.index("--") + 1:]
blend, out, res = a[0], a[1], int(a[2])
shots = [s.split(":") for s in a[3:]]
bpy.ops.wm.open_mainfile(filepath=blend)
sc = bpy.context.scene; rig = bpy.data.objects["SMPL_rig"]
if "SMPL_body" in bpy.data.objects:
    bpy.data.objects["SMPL_body"].hide_render = True
sc.render.engine = "BLENDER_WORKBENCH"; sh = sc.display.shading; sh.light = "STUDIO"; sh.color_type = "TEXTURE"
sc.render.resolution_x = sc.render.resolution_y = res; sc.render.film_transparent = False
sc.world = sc.world or bpy.data.worlds.new("w"); sc.world.color = (0.3, 0.3, 0.32)
cd = bpy.data.cameras.new("c"); cd.type = "ORTHO"; cam = bpy.data.objects.new("c", cd)
sc.collection.objects.link(cam); sc.camera = cam
for fr, bone, width, dx, dz, name in shots:
    sc.frame_set(int(fr)); bpy.context.view_layer.update()
    p = rig.matrix_world @ rig.pose.bones[bone].head
    cd.ortho_scale = float(width)
    cam.location = (p.x + float(dx), p.y - 3, p.z + float(dz)); cam.rotation_euler = (math.radians(90), 0, 0)
    sc.render.filepath = f"{out}/{name}.png"; bpy.ops.render.render(write_still=True)
    print("SHOT", name, "center", tuple(round(v, 4) for v in cam.location), "width", width)
