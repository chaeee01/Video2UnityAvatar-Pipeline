"""
SMPL 리깅 3단계-③ (v3): SMPL 웨이트를 TRELLIS 메쉬로 2단계 전이.

1차 — Data Transfer, max-dist 내 정점만 정밀 전이 (기본 0.08).
      단위는 정렬 공간 기준이며 미터가 아니다 — S4 이후 좌표는 TRELLIS
      정규화 공간이고 신장이 약 1.0 이다. 0.08 은 신장의 8% 에 해당한다.
2차 — 못 받은 정점(옷자락 등)은 메쉬 엣지 연결을 따라(BFS) 최근접 수신
      정점에서 복사. 공간상 가깝지만 천으로는 떨어진 부위(자락-소매)로
      웨이트가 건너뛰는 오배정을 방지. 엣지로 도달 불가한 고립 조각만
      직선거리 폴백.

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background \
      --python transfer_weights.py -- \
      --blend ~/data/06_rig/zombie_sample1/rigged.blend \
      --out ~/data/06_rig/zombie_sample1/transferred.blend
"""
import argparse
import json
import sys
from collections import deque
from pathlib import Path

import bpy
from mathutils import kdtree

# Blender 는 --python 스크립트의 폴더를 sys.path 에 넣지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from part_islands import ISLAND_MAX_RATIO, find_islands, limb_conflict, region_of  # noqa: E402,F401


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--smpl-name", default="SMPL_body")
    ap.add_argument("--rig-name", default="SMPL_rig")
    ap.add_argument("--max-dist", type=float, default=0.08)
    ap.add_argument("--part-constraint", choices=["on", "off"], default="on",
                    help="부위 제약 (기본 on). off 는 2026-10-12 이전 동작 재현용 — "
                         "근거는 part_constraint() 독스트링")
    return ap.parse_args(argv)


def find_trellis_mesh(smpl_name):
    cands = [o for o in bpy.data.objects
             if o.type == "MESH" and o.name != smpl_name]
    if not cands:
        raise RuntimeError("TRELLIS 메쉬를 찾지 못함")
    return max(cands, key=lambda o: len(o.data.vertices))


# 높이 밴드 — 메쉬 전체 높이에 대한 비율(아래 0, 위 1). 2026-10-06 f6+1536 진단에
# 쓴 구분 그대로다 (PROJECT_STATUS 10/6 폴백 부위 분포표).
BANDS = [("head", 0.88, 1.01), ("torso", 0.60, 0.88), ("pelvis_thigh", 0.35, 0.60),
         ("shin", 0.12, 0.35), ("foot", 0.0, 0.12)]
# 사지 본 — 동작에서 크게 움직이는 팔다리 8관절. 머리·척추·쇄골은 강체에 가까워
# 폴백이 붙어도 티가 나지 않지만, 사지 본으로 간 폴백은 "먼 데서 빌린 웨이트로
# 팔다리를 따라 움직이는 조각" 이 된다. 2026-10-07 실측에서 이 비율이 두 표본을
# 갈랐다 — char_shuffle f60(불합격) 47.53% / f6+1536(합격) 1.84%. f60 은 L_Elbow
# 로만 7,050정점이 갔는데, 정렬이 어긋나 왼손 메쉬가 SMPL 에서 max_dist 밖에
# 놓였고 그 조각이 통째로 팔꿈치 웨이트를 빌린 것이다 (L_Hand·L_Wrist 지배 정점
# 0 의 직접 원인).
LIMB_JOINTS = ("Shoulder", "Elbow", "Wrist", "Hand", "Hip", "Knee", "Ankle", "Foot")


def fallback_detail(trellis, rig, records, name_by_idx):
    """직선거리 폴백 정점이 **어디에, 어느 본으로, 얼마나 멀리서** 붙었는지.

    폴백 총량(%)만으로는 품질을 가르지 못해서 넣었다 — G2r 이 총량과 무관하게
    이 분포를 판정한다 (gate_g2r.py ④). 측정 대상은 추정이 아니라 **실제로
    폴백 처리된 정점 집합**이다.

    판정에 쓰는 것은 `limb_pct` 와 `src_dist` 다. `bands`(높이 밴드)는 사람이
    읽기 위한 것이지 판정 축이 아니다 — 팔은 몸통과 같은 높이에 있어서 밴드로는
    "몸통에 붙은 장비" 와 "팔 조각" 이 구분되지 않는다.
    """
    me, mw = trellis.data, trellis.matrix_world
    zs = [(mw @ v.co).z for v in me.vertices]
    z0, z1 = min(zs), max(zs)
    span = (z1 - z0) or 1.0
    band_of = lambda z: next((n for n, lo, hi in BANDS if lo <= (z - z0) / span < hi),
                             "head")
    total = {n: 0 for n, _, _ in BANDS}
    for z in zs:
        total[band_of(z)] += 1

    rmw = rig.matrix_world
    head = {b.name: rmw @ b.head_local for b in rig.data.bones}
    mid_x = head["Pelvis"].x if "Pelvis" in head else 0.0

    n = len(records)
    bands = {name: 0 for name, _, _ in BANDS}
    by_bone, dists = {}, []
    cross = limb = 0
    for vi, dist, gi in records:
        p = mw @ me.vertices[vi].co
        bands[band_of(p.z)] += 1
        bone = name_by_idx[gi]
        by_bone[bone] = by_bone.get(bone, 0) + 1
        dists.append(dist)
        if bone.endswith(LIMB_JOINTS):
            limb += 1
        # 좌우 본인데 정점이 몸 정중선 반대편에 있으면 교차 배정이다
        if bone[:2] in ("L_", "R_") and bone in head:
            if (p.x - mid_x) * (head[bone].x - mid_x) < 0:
                cross += 1
    dists.sort()
    q = lambda f: round(dists[min(int(len(dists) * f), len(dists) - 1)], 5) if dists else None
    r = lambda k: round(100.0 * k / n, 3) if n else 0.0
    return {
        "verts": n,
        "bands": {name: {"verts": c, "pct_of_fallback": r(c),
                         "pct_of_band": round(100.0 * c / total[name], 3) if total[name] else 0.0}
                  for name, c in bands.items()},
        "by_bone": dict(sorted(by_bone.items(), key=lambda kv: -kv[1])),
        "limb_pct": r(limb),              # 사지 본으로 간 폴백 비율 (판정 축)
        "cross_side_pct": r(cross),       # 정중선 반대편 본으로 간 폴백 비율
        # 웨이트를 빌려 온 정점까지의 거리 (판정 축, 정렬 공간 단위 — 신장 약 1.0)
        "src_dist": {"median": q(0.5), "p90": q(0.9), "max": q(1.0)},
    }


def part_constraint(trellis, smpl, name_by_idx):
    """팔 메쉬 안에 박힌 "다리 본 지배" 조각 같은 **부위 섬**을 찾아 고친다.

    웨이트 전이는 메쉬 정점마다 "가장 가까운 SMPL 표면" 을 본다. 손이 허벅지 옆에 있으면
    손 정점에서 가장 가까운 SMPL 표면이 팔이 아니라 허벅지일 수 있다 — WHAM 이 추정한 팔이
    메쉬의 팔과 어긋났거나(walker_walk_02 f138), 어긋나지 않았어도 손이 허벅지의 전이 반경
    안에 있으면(f18) 그렇다. 그러면 손의 일부가 허벅지 본을 따라가 팔을 움직일 때 손과
    허벅지 사이가 판자처럼 늘어난다. 2026-10-12 실측으로 이 결함은 **한 방향**이다 — 팔 정점이
    다리 본을 받고(f18 에서 1,663정점), 반대는 0 이다. 메쉬가 붙은 것도 아니다.

    공간상 가깝다는 것은 같은 부위라는 뜻이 아니다. **메쉬가 이어진 방식**이 부위를 말해 준다
    — 손은 허벅지 옆에 있어도 메쉬로는 팔을 거쳐야 몸통에 닿는다. 그래서:

      1. 정점마다 지배 본의 부위(몸통 · 좌우 팔 · 좌우 다리)를 라벨로 붙인다.
      2. 같은 라벨끼리 메쉬 엣지로 이어진 덩어리를 구한다 (UV 심으로 갈라진 정점은 좌표가 같으면 이어진 것으로 본다).
      3. 부위마다 가장 큰 덩어리가 그 부위의 본체다. **본체가 아닌 작은 덩어리**가 "떨어져
         있어야 할 부위"(팔–다리, 팔–하부 몸통)의 더 큰 덩어리에 맞닿아 있으면 섬이다 — 그
         부위로 라벨을 바꾼다. 원래 이웃인 부위(어깨·골반)의 경계는 건드리지 않는다.
      4. 섬의 정점은 **새 부위의 SMPL 정점 중** 가장 가까운 셋에서 웨이트를 다시 받는다.

    전이 결과를 통째로 다시 계산하지 않고 섬만 고친다. 섬이 없는 메쉬는 한 정점도 바뀌지
    않는다 — 합격했던 샘플의 결과를 건드리지 않기 위해서다(2026-10-12: 합격 4건 재배정 0).

    **알려진 한계.** 메쉬가 실제로 붙은 곳(다리가 융합된 char_shuffle f60 등)에서는 두 부위가
    한 덩어리로 이어져 있어 섬이 생기지 않거나, 생겨도 경계가 임의로 잡힌다. 이 함수는
    "떨어져 있는 메쉬에 웨이트가 잘못 붙은 것" 만 고친다. 붙은 메쉬는 키프레임의 문제다.
    SMPL 본의 **위치**도 고치지 않는다 — 어긋난 팔의 본은 어긋난 채로 남고, 웨이트만 제 본으로
    돌아온다.
    """
    me = trellis.data
    n = len(me.vertices)
    dom = [None] * n
    for v in me.vertices:
        if v.groups:
            g = max(v.groups, key=lambda g: g.weight)
            if g.weight >= 1e-4:
                dom[v.index] = name_by_idx[g.group]
    # 메쉬 엣지 + **같은 좌표의 정점끼리 잇는 가상 엣지**로 그래프를 짠다. TRELLIS 메쉬는 UV
    # 심에서 정점이 갈라져 있어 엣지만 따라가면 심을 못 넘는다. 좌표로 묶어 하나로 치지 않고
    # 따로 둔 채 잇는 이유 — 같은 좌표라도 웨이트가 다를 수 있다(BFS·폴백이 정점별로 다른
    # 곳에서 가져온다). 하나로 치면 그 차이가 가려져 섬을 놓친다(처음 구현이 그랬다).
    adj = [[] for _ in range(n)]
    for e in me.edges:
        a, b = e.vertices
        adj[a].append(b)
        adj[b].append(a)
    first = {}
    for v in me.vertices:
        k = (round(v.co.x, 5), round(v.co.y, 5), round(v.co.z, 5))
        j = first.get(k)
        if j is None:
            first[k] = v.index
        else:
            adj[j].append(v.index)
            adj[v.index].append(j)
    relabel, islands = find_islands(dom, adj)
    if not relabel:
        return {"islands": 0, "verts": 0, "detail": []}

    # 새 부위의 SMPL 정점에서 웨이트를 다시 받는다
    smpl_idx = {vg.index: vg.name for vg in smpl.vertex_groups}
    tgt = {vg.name: vg for vg in trellis.vertex_groups}
    s_weights, by_region = {}, {}
    for v in smpl.data.vertices:
        w = {smpl_idx[g.group]: g.weight for g in v.groups if g.weight > 1e-5}
        if not w:
            continue
        s_weights[v.index] = w
        by_region.setdefault(region_of(max(w, key=w.get)), []).append(v.index)
    smw, tinv = smpl.matrix_world, trellis.matrix_world.inverted()
    trees = {}
    for reg, idxs in by_region.items():
        kd = kdtree.KDTree(len(idxs))
        for i in idxs:
            kd.insert(tinv @ (smw @ smpl.data.vertices[i].co), i)   # 메쉬의 로컬 좌표로
        kd.balance()
        trees[reg] = kd
    changed = 0
    for u, to in relabel.items():
        kd = trees.get(to)
        if kd is None:
            continue
        near = kd.find_n(me.vertices[u].co, 3)
        tot, acc = 0.0, {}
        for _, si, d in near:
            k = 1.0 / max(d, 1e-6)
            tot += k
            for b, w in s_weights[si].items():
                acc[b] = acc.get(b, 0.0) + k * w
        for vg in trellis.vertex_groups:
            vg.remove([u])
        for b, w in acc.items():
            if b in tgt and w / tot > 1e-4:
                tgt[b].add([u], w / tot, "REPLACE")
        changed += 1
    islands.sort(key=lambda d: -d["verts"])
    return {"islands": len(islands), "verts": changed, "detail": islands[:12]}


def rig_check(trellis, rig, name_by_idx):
    """리깅이 제대로 붙었는지 보는 세 지표의 원자료 (G2r ①②③). 판정은 gate_g2r.py 가 한다.

      bone_dist   본 머리 → 메쉬 최근접 정점 거리 (정렬 공간 단위, 신장 약 1.0)
      dominant    그 본이 최대 웨이트인 정점 수
      cross       좌우 본의 지배 정점 중 **쌍의 이등분면 반대편**에 있는 수
      limb_edges  서로 이웃하지 않는 부위의 본이 지배하는 두 정점을 잇는 엣지 수 (⑤).
                  arm_leg 팔(팔꿈치·손목·손)–다리, arm_lowtorso 팔–하부 몸통(골반·Spine1·2),
                  leg_leg 좌다리–우다리(좌우 Hip 쌍은 사타구니에서 원래 만나므로 뺀다)

    cross 의 기준면에 주의. 2026-10-01 첫 측정은 몸 정중선을 수직면(x=0)으로 잡았는데,
    기울어 선 자세에서 틀린다 — zombie1 은 상체가 기울어 R_Collar 가 70% 로 나왔다
    (결함이 아니다). 좌우 쌍(L_Knee·R_Knee 등)의 두 본 머리를 잇는 선분의 수직
    이등분면을 쓰면 자세와 무관하다. 그래서 10/1 의 "L_Ankle 38.3%" 는 이 정의로
    13.1% 이고, 같은 샘플의 최댓값은 R_Knee 28.3% 다.
    """
    me, mw = trellis.data, trellis.matrix_world
    rmw = rig.matrix_world
    head = {b.name: rmw @ b.head_local for b in rig.data.bones}
    kd = kdtree.KDTree(len(me.vertices))
    for i, v in enumerate(me.vertices):
        kd.insert(mw @ v.co, i)
    kd.balance()
    bone_dist = {b: round(kd.find(p)[2], 5) for b, p in head.items()}

    plane = {}
    for b in head:
        if b[:2] in ("L_", "R_"):
            other = ("R_" if b[0] == "L" else "L_") + b[2:]
            if other in head:
                n = head[b] - head[other]
                if n.length > 1e-9:
                    plane[b] = ((head[b] + head[other]) / 2, n.normalized())
    dominant = {b: 0 for b in head}
    cross = {b: 0 for b in plane}
    dom_of = [None] * len(me.vertices)
    for v in me.vertices:
        if not v.groups:
            continue
        g = max(v.groups, key=lambda g: g.weight)
        if g.weight < 1e-4:
            continue
        b = name_by_idx[g.group]
        dom_of[v.index] = b
        dominant[b] = dominant.get(b, 0) + 1
        if b in plane:
            mid, n = plane[b]
            if (mw @ v.co - mid).dot(n) < 0:
                cross[b] += 1
    # ⑤ 떨어져 있어야 할 부위가 메쉬 엣지로 이어져 있는가. 손 정점이 허벅지 본을 받거나
    # (정렬 불일치) 허벅지 정점이 손 본을 받으면(근접 번짐), 그 경계의 엣지는 팔이 움직일 때
    # 판자처럼 늘어난다. 정적 메쉬에서 셀 수 있다 — 동작을 돌려 볼 필요가 없다.
    arm, leg, low = ("Elbow", "Wrist", "Hand"), ("Hip", "Knee", "Ankle", "Foot"), ("Pelvis", "Spine1", "Spine2")
    pairs = {}
    for e in me.edges:
        a, b = dom_of[e.vertices[0]], dom_of[e.vertices[1]]
        if a and b and a != b:
            k = (a, b) if a < b else (b, a)
            pairs[k] = pairs.get(k, 0) + 1
    groups = {"arm_leg": 0, "arm_lowtorso": 0, "leg_leg": 0}
    top = {}
    for (a, b), c in pairs.items():
        aa, ab, la, lb = a.endswith(arm), b.endswith(arm), a.endswith(leg), b.endswith(leg)
        if (aa and lb) or (ab and la):
            g = "arm_leg"
        elif (aa and b in low) or (ab and a in low):
            g = "arm_lowtorso"
        elif la and lb and a[0] != b[0] and not (a.endswith("Hip") and b.endswith("Hip")):
            g = "leg_leg"
        else:
            continue
        groups[g] += c
        top[f"{a}|{b}"] = c
    limb_edges = dict(groups, edges=len(me.edges),
                      top=dict(sorted(top.items(), key=lambda kv: -kv[1])[:8]))
    return {"vertices": len(me.vertices), "bone_dist": bone_dist,
            "dominant": dominant, "cross": cross, "limb_edges": limb_edges}


def main():
    a = parse_args()
    bpy.ops.wm.open_mainfile(filepath=a.blend)

    smpl = bpy.data.objects.get(a.smpl_name)
    rig = bpy.data.objects.get(a.rig_name)
    if smpl is None or rig is None:
        raise RuntimeError(f"{a.smpl_name} 또는 {a.rig_name} 없음")
    trellis = find_trellis_mesh(a.smpl_name)
    me = trellis.data
    n_verts = len(me.vertices)
    print(f"[1/5] 대상: {trellis.name} (정점 {n_verts})")

    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.pose.transforms_clear()
    bpy.ops.object.mode_set(mode="OBJECT")

    print(f"[2/5] 1차 전이 (max_dist={a.max_dist})")
    bpy.context.view_layer.objects.active = trellis
    for vg in smpl.vertex_groups:
        if vg.name not in trellis.vertex_groups:
            trellis.vertex_groups.new(name=vg.name)
    mod = trellis.modifiers.new("WeightTransfer", "DATA_TRANSFER")
    mod.object = smpl
    mod.use_vert_data = True
    mod.data_types_verts = {"VGROUP_WEIGHTS"}
    mod.vert_mapping = "POLYINTERP_NEAREST"
    mod.layers_vgroup_select_src = "ALL"
    mod.layers_vgroup_select_dst = "NAME"
    mod.use_max_distance = True
    mod.max_distance = a.max_dist
    bpy.ops.object.datalayout_transfer(modifier=mod.name)
    bpy.ops.object.modifier_apply(modifier=mod.name)

    print("[3/5] 2차 전파 준비")
    weights = {}
    for v in me.vertices:
        g = {gr.group: gr.weight for gr in v.groups if gr.weight > 1e-5}
        if g:
            weights[v.index] = g
    n_direct = len(weights)
    n_missing = n_verts - n_direct
    print(f"  1차 수신 {n_direct}, 미수신 {n_missing} "
          f"({100*n_missing/n_verts:.1f}%)")

    filled_topo = 0
    filled_eucl = 0
    fb_records = []          # 폴백 정점별 (정점 번호, 소스까지 거리, 받은 지배 그룹)
    if n_missing:
        print("[4/5] 2차 전파: 엣지 연결(BFS) 기반")
        adj = [[] for _ in range(n_verts)]
        for e in me.edges:
            va, vb = e.vertices
            adj[va].append(vb)
            adj[vb].append(va)

        src = dict.fromkeys(weights.keys())
        for vi in weights:
            src[vi] = vi
        q = deque(weights.keys())
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v not in src:
                    src[v] = src[u]
                    q.append(v)

        vg_by_idx = {vg.index: vg for vg in trellis.vertex_groups}
        unreached = []
        for vi in range(n_verts):
            if vi in weights:
                continue
            if vi in src:
                for gi, w in weights[src[vi]].items():
                    vg_by_idx[gi].add([vi], w, "REPLACE")
                filled_topo += 1
            else:
                unreached.append(vi)

        if unreached:
            print(f"  엣지로 도달 불가(고립 조각) {len(unreached)}개 - 직선거리 폴백")
            kd = kdtree.KDTree(n_direct)
            for vi in weights:
                kd.insert(me.vertices[vi].co, vi)
            kd.balance()
            for vi in unreached:
                _, svi, dist = kd.find(me.vertices[vi].co)
                for gi, w in weights[svi].items():
                    vg_by_idx[gi].add([vi], w, "REPLACE")
                filled_eucl += 1
                dom = max(weights[svi].items(), key=lambda kv: kv[1])[0]
                fb_records.append((vi, dist, dom))
        print(f"  전파 완료: 표면 연결 {filled_topo}, 직선거리 폴백 {filled_eucl}")
    else:
        print("[4/5] 미수신 없음 - 전파 생략")

    name_by_idx = {vg.index: vg.name for vg in trellis.vertex_groups}
    if a.part_constraint == "on":
        pc = part_constraint(trellis, smpl, name_by_idx)
        print(f"  부위 제약: 섬 {pc['islands']}개, 정점 {pc['verts']} 재배정")
        for d in pc["detail"][:5]:
            print(f"    {d['from']} → {d['to']}  {d['verts']}정점 (맞닿은 엣지 {d['border']})")
    else:
        pc = {"islands": None, "verts": 0, "detail": [], "off": True}

    arm_mod = trellis.modifiers.new("Armature", "ARMATURE")
    arm_mod.object = rig
    trellis.parent = rig

    print("[5/5] 검증")
    remaining = sum(1 for v in me.vertices
                    if sum(g.weight for g in v.groups) < 1e-5)
    print(f"  최종 웨이트 없는 정점: {remaining}/{n_verts}")
    per_group = {}
    for v in me.vertices:
        for g in v.groups:
            if g.weight > 0.01:
                per_group[g.group] = per_group.get(g.group, 0) + 1
    name_by_idx = {vg.index: vg.name for vg in trellis.vertex_groups}
    top = sorted(per_group.items(), key=lambda x: -x[1])[:8]
    print("  본별 영향 정점 (상위 8):")
    for idx, cnt in top:
        print(f"    {name_by_idx[idx]:<12} {cnt}")

    # 기계 판독용 기록. 표준출력은 그대로 두고 JSON 을 추가한다 (무파괴).
    # 3단 비율은 G2r 과 보고서가 함께 쓰는 수치라 전부 남긴다 (1차 / BFS / 폴백 / 무배정).
    pct = lambda n: round(100.0 * n / n_verts, 4) if n_verts else 0.0
    params = {
        "stage": "5-4",
        "script": "transfer_weights.py",
        "version": 1,
        "name": Path(a.out).stem,
        "target_mesh": trellis.name,
        "vertices": n_verts,
        "max_dist": a.max_dist,          # 정렬 공간 단위 (미터 아님)
        "transfer": {
            "direct":     {"verts": n_direct,   "pct": pct(n_direct)},
            "bfs":        {"verts": filled_topo, "pct": pct(filled_topo)},
            "fallback":   {"verts": filled_eucl, "pct": pct(filled_eucl)},
            "unassigned": {"verts": remaining,   "pct": pct(remaining)},
        },
        "fallback_detail": fallback_detail(trellis, rig, fb_records, name_by_idx),
        "part_constraint": pc,
        "rig_check": rig_check(trellis, rig, name_by_idx),
        "fallback_pct":   pct(filled_eucl),   # G2r --fallback-pct 에 그대로 넣는 값
        "unassigned_pct": pct(remaining),     # G2r --unassigned-pct
        "inputs": {"blend": a.blend},
        "out": a.out,
    }
    out_json = a.out.rsplit(".", 1)[0] + "_params.json"
    with open(out_json, "w") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)

    bpy.ops.wm.save_as_mainfile(filepath=a.out)
    print(f"\n저장: {a.out}")
    print(f"파라미터: {out_json}")
    print("확인: Pose Mode 에서 L_Elbow/R_Elbow, Spine2, R_Hip 회전.")
    print("      자락이 팔에 붙지 않고 몸통을 따라오면 성공.")


if __name__ == "__main__":
    main()
