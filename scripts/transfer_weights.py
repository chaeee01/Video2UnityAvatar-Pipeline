"""
SMPL 리깅 3단계-③ (v3): SMPL 웨이트를 TRELLIS 메쉬로 2단계 전이.

1차 — Data Transfer, max-dist 내 정점만 정밀 전이 (기본 0.08m)
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
import sys
from collections import deque

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
                _, svi, _ = kd.find(me.vertices[vi].co)
                for gi, w in weights[svi].items():
                    vg_by_idx[gi].add([vi], w, "REPLACE")
                filled_eucl += 1
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

    bpy.ops.wm.save_as_mainfile(filepath=a.out)
    print(f"\n저장: {a.out}")
    print("확인: Pose Mode 에서 L_Elbow/R_Elbow, Spine2, R_Hip 회전.")
    print("      자락이 팔에 붙지 않고 몸통을 따라오면 성공.")


if __name__ == "__main__":
    main()
