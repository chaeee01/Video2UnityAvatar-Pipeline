"""확대 캡처: 지정 본 둘레를 정면 직교 카메라로 찍는다 (Workbench, 텍스처)."""
import bpy, sys, math, mathutils
a=sys.argv[sys.argv.index("--")+1:]; blend,out=a[0],a[1]; shots=[s.split(":") for s in a[2:]]   # 프레임:본:폭:이름
bpy.ops.wm.open_mainfile(filepath=blend)
sc=bpy.context.scene; rig=bpy.data.objects["SMPL_rig"]
if "SMPL_body" in bpy.data.objects: bpy.data.objects["SMPL_body"].hide_render=True
sc.render.engine="BLENDER_WORKBENCH"; sh=sc.display.shading; sh.light="STUDIO"; sh.color_type="TEXTURE"; sc.render.resolution_x=sc.render.resolution_y=800; sc.render.film_transparent=False
sc.world=sc.world or bpy.data.worlds.new("w"); sc.world.color=(0.3,0.3,0.32)
cd=bpy.data.cameras.new("c"); cd.type="ORTHO"; cam=bpy.data.objects.new("c",cd); sc.collection.objects.link(cam); sc.camera=cam
for fr,bone,width,name in shots:
    sc.frame_set(int(fr)); bpy.context.view_layer.update()
    p=rig.matrix_world@rig.pose.bones[bone].head
    cd.ortho_scale=float(width); cam.location=(p.x,p.y-3,p.z); cam.rotation_euler=(math.radians(90),0,0)
    sc.render.filepath=f"{out}/{name}.png"; bpy.ops.render.render(write_still=True); print("SHOT",name)
