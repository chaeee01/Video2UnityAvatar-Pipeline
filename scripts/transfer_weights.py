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


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--smpl-name", default="SMPL_body")
    ap.add_argument("--rig-name", default="SMPL_rig")
    ap.add_argument("--max-dist", type=float, default=0.08)
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
