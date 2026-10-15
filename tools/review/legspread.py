import bpy,sys,json,math
out=[]
for blend in sys.argv[sys.argv.index("--")+1:]:
    bpy.ops.wm.open_mainfile(filepath=blend); sc=bpy.context.scene; rig=bpy.data.objects["SMPL_rig"]; pb=rig.pose.bones; mw=rig.matrix_world
    H=None; seps=[]; knees=[]; angs=[]
    for f in range(sc.frame_start, sc.frame_end+1, 2):
        sc.frame_set(f); bpy.context.view_layer.update()
        P={n:mw@pb[n].head for n in ("L_Ankle","R_Ankle","L_Knee","R_Knee","L_Hip","R_Hip","Pelvis","Head")}
        if H is None: H=(P["Head"]-((P["L_Ankle"]+P["R_Ankle"])/2)).length
        seps.append((P["L_Ankle"]-P["R_Ankle"]).length/H); knees.append((P["L_Knee"]-P["R_Knee"]).length/H)
        a=(P["L_Knee"]-P["L_Hip"]).normalized(); b=(P["R_Knee"]-P["R_Hip"]).normalized(); angs.append(math.degrees(math.acos(max(-1,min(1,a.dot(b))))))
    s=sorted(seps); k=sorted(knees); g=sorted(angs)
    out.append(dict(clip=blend.split("/motions/")[-1].split("/")[0] if "/motions/" in blend else "기준자세", ankle_max=round(s[-1],3), ankle_p90=round(s[int(.9*len(s))],3), ankle_med=round(s[len(s)//2],3), knee_max=round(k[-1],3), thigh_angle_max=round(g[-1],1), thigh_angle_p90=round(g[int(.9*len(g))],1)))
print("LEG"+json.dumps(out,ensure_ascii=False))
