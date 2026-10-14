import bpy, sys, json
out=[]
for p in sys.argv[sys.argv.index("--")+1:]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=p)
    arm=[o for o in bpy.data.objects if o.type=="ARMATURE"]; mesh=[o for o in bpy.data.objects if o.type=="MESH"]
    acts=[(a.name,int(a.frame_range[0]),int(a.frame_range[1])) for a in bpy.data.actions]
    imgs=[(i.name,i.filepath,bool(i.packed_file)) for i in bpy.data.images]
    out.append(dict(file=p.split("/")[-1],arm=[a.name for a in arm],bones=[len(a.data.bones) for a in arm],mesh=[(m.name,len(m.data.vertices),len(m.data.polygons)) for m in mesh],actions=acts,fps=bpy.context.scene.render.fps,images=imgs,dims=[[round(x,3) for x in m.dimensions] for m in mesh]))
print("FBXCHK"+json.dumps(out,ensure_ascii=False))
