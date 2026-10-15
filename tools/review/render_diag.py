"""광택·색감 진단 렌더: 같은 카메라·조명으로 GLB 를 찍는다. flat = 텍스처 색 그대로(조명 없음), lit = 조명 받은 모습. --scale N 은 해상도를 N 배로 (얼굴 · 무늬 확대용은 3)."""
import bpy, sys, os, math, mathutils, argparse
ap=argparse.ArgumentParser(); ap.add_argument("--glb"); ap.add_argument("--out"); ap.add_argument("--tex",default=None); ap.add_argument("--rough",type=float,default=None)
ap.add_argument("--mode",default="lit"); ap.add_argument("--scale",type=int,default=1); ap.add_argument("--angle",type=float,default=0)
a=ap.parse_args(sys.argv[sys.argv.index("--")+1:])
bpy.ops.wm.read_factory_settings(use_empty=True); bpy.ops.import_scene.gltf(filepath=os.path.expanduser(a.glb)); sc=bpy.context.scene
info={}
for m in bpy.data.materials:
    if not m.use_nodes: continue
    nt=m.node_tree; bsdf=next((n for n in nt.nodes if n.type=="BSDF_PRINCIPLED"),None)
    if not bsdf: continue
    bc=bsdf.inputs["Base Color"]; src=bc.links[0].from_socket if bc.links else None
    info[m.name]={"rough_linked":bool(bsdf.inputs["Roughness"].links),"rough_default":round(bsdf.inputs["Roughness"].default_value,3),"metal_linked":bool(bsdf.inputs["Metallic"].links),"metal_default":round(bsdf.inputs["Metallic"].default_value,3),
                  "spec":{k:round(bsdf.inputs[k].default_value,3) for k in ("Specular IOR Level","IOR","Coat Weight","Sheen Weight") if k in bsdf.inputs}}
    if a.tex and src and src.node.type=="TEX_IMAGE": src.node.image=bpy.data.images.load(os.path.expanduser(a.tex))
    if a.rough is not None:
        for l in list(bsdf.inputs["Roughness"].links): nt.links.remove(l)
        bsdf.inputs["Roughness"].default_value=a.rough
    if a.mode=="flat" and src:
        em=nt.nodes.new("ShaderNodeEmission"); nt.links.new(src,em.inputs["Color"]); out=next(n for n in nt.nodes if n.type=="OUTPUT_MATERIAL"); nt.links.new(em.outputs[0],out.inputs["Surface"])
print("MATINFO",info)
meshes=[o for o in bpy.data.objects if o.type=="MESH"]; mn=mathutils.Vector((1e9,)*3); mx=mathutils.Vector((-1e9,)*3)
for o in meshes:
    for c in o.bound_box:
        w=o.matrix_world@mathutils.Vector(c); mn=mathutils.Vector(min(mn[i],w[i]) for i in range(3)); mx=mathutils.Vector(max(mx[i],w[i]) for i in range(3))
ctr,size=(mn+mx)/2,max(mx-mn)
cam=bpy.data.objects.new("c",bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera=cam; cam.data.type="ORTHO"; cam.data.ortho_scale=size*1.1
for nm,en,rot in (("key",3.0,(55,0,35)),("fill",1.5,(70,0,215)),("front",1.5,(80,0,0))):
    l=bpy.data.objects.new(nm,bpy.data.lights.new(nm,type="SUN")); l.data.energy=en; sc.collection.objects.link(l); l.rotation_euler=tuple(math.radians(x) for x in rot)
sc.world=bpy.data.worlds.new("w"); sc.world.use_nodes=True; sc.world.node_tree.nodes["Background"].inputs[0].default_value=(0.45,0.45,0.47,1)
for eng in ("BLENDER_EEVEE_NEXT","BLENDER_EEVEE"):
    try: sc.render.engine=eng; break
    except TypeError: continue
sc.view_settings.view_transform="Standard"; sc.view_settings.look="None"
sc.render.resolution_x,sc.render.resolution_y=900*a.scale,1200*a.scale; r=math.radians(a.angle)
cam.location=(ctr.x+math.sin(r)*size*2,ctr.y-math.cos(r)*size*2,ctr.z); cam.rotation_euler=(math.radians(90),0,r)
sc.render.filepath=os.path.expanduser(a.out); bpy.ops.render.render(write_still=True); print("RENDERED",a.out)
