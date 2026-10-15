"""웨빙 진단용 덤프: 프레임별 4배 늘어난 엣지 수(본 쌍별) + 최악 프레임 좌표 + 리그 정지 상태."""
import bpy, sys, json, numpy as np
blend, out, step, full = sys.argv[sys.argv.index("--")+1:][:4]
step=int(step); full=full=="1"
bpy.ops.wm.open_mainfile(filepath=blend)
sc=bpy.context.scene; rig=bpy.data.objects["SMPL_rig"]; smpl=bpy.data.objects.get("SMPL_body")
mesh=max([o for o in bpy.data.objects if o.type=="MESH" and o.name!="SMPL_body"], key=lambda o:len(o.data.vertices))
bones=[b.name for b in rig.data.bones]; bi={n:i for i,n in enumerate(bones)}
def doms(ob):
    name={vg.index:vg.name for vg in ob.vertex_groups}; n=len(ob.data.vertices)
    dom=np.full(n,-1,np.int16); wl=np.zeros(n,np.float32); wr=np.zeros(n,np.float32); wd=np.zeros(n,np.float32)
    ARM=("Shoulder","Elbow","Wrist","Hand")
    for v in ob.data.vertices:
        best=None
        for g in v.groups:
            nm=name[g.group]
            if nm not in bi: continue
            if best is None or g.weight>best[0]: best=(g.weight,nm)
            if nm.endswith(ARM):
                if nm[0]=="L": wl[v.index]+=g.weight
                else: wr[v.index]+=g.weight
        if best and best[0]>=1e-4: dom[v.index]=bi[best[1]]; wd[v.index]=best[0]
    return dom,wl,wr,wd
def co(ob_eval_mesh, mw):
    a=np.empty(len(ob_eval_mesh.vertices)*3,np.float32); ob_eval_mesh.vertices.foreach_get("co",a); a=a.reshape(-1,3)
    M=np.array(mw); return a@M[:3,:3].T+M[:3,3]
dom,wl,wr,wd=doms(mesh)
E=np.empty(len(mesh.data.edges)*2,np.int32); mesh.data.edges.foreach_get("vertices",E); E=E.reshape(-1,2)
rest=co(mesh.data,mesh.matrix_world); rl=np.linalg.norm(rest[E[:,0]]-rest[E[:,1]],axis=1); ok=rl>1e-6
da,db=dom[E[:,0]],dom[E[:,1]]; lo,hi=np.minimum(da,db),np.maximum(da,db); pid=(lo.astype(np.int32)+1)*32+(hi+1)
scan={}; long={}; worst=(-1,None,None)
for f in range(sc.frame_start, sc.frame_end+1, step):
    sc.frame_set(f); dg=bpy.context.evaluated_depsgraph_get(); ev=mesh.evaluated_get(dg); me=ev.to_mesh()
    c=co(me,ev.matrix_world); ev.to_mesh_clear()
    ln=np.linalg.norm(c[E[:,0]]-c[E[:,1]],axis=1); st=ok&(ln>4.0*np.where(ok,rl,1))
    long[f]=[int((st&(ln>0.05)).sum()),int((st&(ln>0.10)).sum()),float(ln[st].max()) if st.any() else 0.0]
    if (st&(ln>0.05)).any():
        u2,k2=np.unique(pid[st&(ln>0.05)],return_counts=True); long[f].append({f"{bones[a//32-1] if a//32 else '-'}|{bones[a%32-1] if a%32 else '-'}":int(n) for a,n in zip(u2,k2)})
    u,k=np.unique(pid[st],return_counts=True)
    scan[f]={f"{bones[a//32-1] if a//32 else '-'}|{bones[a%32-1] if a%32 else '-'}":int(n) for a,n in zip(u,k)}
    tot=int(st.sum())
    if tot>worst[0]: worst=(tot,f,c.copy())
res={"blend":blend,"frames":[sc.frame_start,sc.frame_end],"verts":len(rest),"edges":len(E),"worst_frame":worst[1],"worst_total":worst[0],"scan":scan,"long":long}
json.dump(res,open(out+".json","w"),ensure_ascii=False)
if full:
    pb={}
    sc.frame_set(worst[1]); bpy.context.view_layer.update()
    heads_rest=np.array([list(rig.matrix_world@b.head_local) for b in rig.data.bones],np.float32)
    heads_w=np.array([list(rig.matrix_world@rig.pose.bones[n].head) for n in bones],np.float32)
    d=dict(rest=rest,E=E,dom=dom,wl=wl,wr=wr,wd=wd,worst=worst[2],heads_rest=heads_rest,heads_worst=heads_w,bones=np.array(bones))
    if smpl:
        sd,_,_,_=doms(smpl); SE=np.empty(len(smpl.data.edges)*2,np.int32); smpl.data.edges.foreach_get("vertices",SE)
        d.update(s_rest=co(smpl.data,smpl.matrix_world),s_dom=sd,s_E=SE.reshape(-1,2))
    np.savez(out+".npz",**d)
print("DUMPOK",worst[1],worst[0])
