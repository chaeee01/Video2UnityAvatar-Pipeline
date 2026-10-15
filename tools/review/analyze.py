"""리그 겨드랑이 분석 (오늘 방법): 정지 상태 위팔–하부몸통 엣지, 높이 띠 연결, 최악 프레임의 긴 엣지."""
import sys, json, numpy as np, scipy.sparse as sp, scipy.sparse.csgraph as cg, collections, warnings; warnings.filterwarnings("ignore")
pre=sys.argv[1]; d=np.load(pre+".npz"); J=json.load(open(pre+".json"))
rest,E,dom,W=d["rest"],d["E"],d["dom"],d["worst"]; B=[str(x) for x in d["bones"]]; H=d["heads_rest"]; bi={n:i for i,n in enumerate(B)}; N=len(rest)
nm=lambda i:B[i] if i>=0 else "-"
ARM=("Shoulder","Elbow","Wrist","Hand")
def reg(n): return (1 if n[0]=="L" else 2) if n.endswith(ARM) else ((3 if n[0]=="L" else 4) if n.endswith(("Hip","Knee","Ankle","Foot")) else 0)
vr=np.array([-1]+[reg(n) for n in B])[dom+1]
rl=np.linalg.norm(rest[E[:,0]]-rest[E[:,1]],axis=1); wl=np.linalg.norm(W[E[:,0]]-W[E[:,1]],axis=1)
pc=collections.Counter(tuple(sorted((nm(a),nm(b)))) for a,b in zip(dom[E[:,0]],dom[E[:,1]]) if a!=b)
low={p:c for p,c in pc.items() if any(x.endswith("Shoulder") for x in p) and any(x in ("Pelvis","Spine1","Spine2") for x in p)}
print(f"[{pre.split('/')[-1]}] 정점 {N:,} 키 {np.ptp(rest[:,2]):.3f} | 최악 프레임 {J['worst_frame']} (4배↑ {J['worst_total']:,})")
print("  정지 상태 위팔–하부몸통 엣지:",dict(sorted(low.items())), "합", sum(low.values()))
for thr in (0.05,0.10):
    m=(wl>thr)&(wl>4*rl); print(f"  최악 프레임 길이>{thr} & 4배↑: {int(m.sum())}", collections.Counter(tuple(sorted((nm(dom[a]),nm(dom[b])))) for a,b in E[m]).most_common(4))
print("  최대 길이",round(float(wl[wl>4*rl].max()),4) if (wl>4*rl).any() else 0)
_,inv=np.unique(np.round(rest,6),axis=0,return_inverse=True); o=np.argsort(inv); si=inv[o]; s=np.where(si[1:]==si[:-1])[0]; EA=np.vstack([E,np.stack([o[s],o[s+1]],1)])
for side,code in (("L",1),("R",2)):
    sh,el=H[bi[side+"_Shoulder"]],H[bi[side+"_Elbow"]]; sgn=1 if sh[0]>0 else -1; out=[]
    # 위팔이 수평·위로 들린 리그에서는 높이 띠가 아니라 '위팔 축에 수직인 띠'로 자른다
    ax=el-sh; L=np.linalg.norm(ax); u=ax/L
    for t in (0.35,0.5,0.65,0.8,0.9):
        c=sh+t*ax; s_=(rest-c)@u; r=np.linalg.norm((rest-c)-np.outer(s_,u),axis=1)
        inb=(np.abs(s_)<0.008)&(r<0.16)
        idx=np.where(inb)[0]; mp=-np.ones(N,np.int64); mp[idx]=np.arange(len(idx))
        e=EA[inb[EA[:,0]]&inb[EA[:,1]]]; G=sp.coo_matrix((np.ones(len(e)),(mp[e[:,0]],mp[e[:,1]])),shape=(len(idx),len(idx)))
        nc,lab=cg.connected_components(G,directed=False)
        arm=np.bincount(lab[vr[idx]==code],minlength=nc); tor=np.bincount(lab[vr[idx]==0],minlength=nc)
        if arm.max()==0: out.append(f"t={t}: 팔 없음"); continue
        ka=int(np.argmax(arm)); mix=((vr[e[:,0]]==code)&(vr[e[:,1]]==0))|((vr[e[:,1]]==code)&(vr[e[:,0]]==0))
        out.append(f"t={t}: {'한 덩어리' if tor.max()>0 and ka==int(np.argmax(tor)) else '별개'}(팔 {arm[ka]:,}·같은 덩어리의 몸통 {tor[ka]:,}·팔–몸통 엣지 {int(mix.sum())})")
    print(f"  {side} 위팔 축 수직 띠(반경 0.16): "+" | ".join(out))
