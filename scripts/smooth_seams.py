"""5-4 뒤 후처리: 지정한 본 쌍의 "딱 잘린" 웨이트 경계를 띠 모양으로 고르게 한다.

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background \\
      --python smooth_seams.py -- \\
      --blend ~/data/06_rig/<샘플>/transferred.blend \\
      --out   ~/data/06_rig/<샘플>/transferred.blend \\
      --pairs L_Hip:R_Hip --rings 10 --iters 40

무엇을 왜 하는지는 seam_smooth.py 독스트링. 가랑이(L_Hip:R_Hip)가 첫 대상이다(2026-10-21).
띠 밖의 웨이트는 바꾸지 않는다. 결과 옆에 <out>_smooth_params.json (띠 크기, 바뀐 정점, 스무딩 뒤
G2r 원자료 rig_check) 을 남긴다.
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seam_smooth import adjacency, coincident_pairs, dominant, ring_region, seam_seeds, smooth  # noqa: E402
from transfer_weights import find_trellis_mesh, rig_check  # noqa: E402


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pairs", required=True, help="본 쌍, 쉼표로 여럿. 예: L_Hip:R_Hip")
    ap.add_argument("--rings", type=int, required=True, help="경계에서 몇 겹까지 띠에 넣을지")
    ap.add_argument("--iters", type=int, required=True, help="스무딩 반복 횟수")
    ap.add_argument("--lam", type=float, default=0.5)
    ap.add_argument("--smpl-name", default="SMPL_body")
    ap.add_argument("--rig-name", default="SMPL_rig")
    return ap.parse_args(argv)


def main():
    a = parse_args()
    pairs = set()
    for p in a.pairs.split(","):
        x, y = p.split(":")
        pairs.add(frozenset((x.strip(), y.strip())))
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    rig = bpy.data.objects.get(a.rig_name)
    if rig is None:
        raise RuntimeError(f"{a.rig_name} 없음")
    tr = find_trellis_mesh(a.smpl_name)
    me = tr.data
    n = len(me.vertices)
    name_by_idx = {vg.index: vg.name for vg in tr.vertex_groups}
    known = {b for pr in pairs for b in pr}
    missing = known - set(name_by_idx.values())
    if missing:
        raise RuntimeError(f"버텍스 그룹에 없는 본: {sorted(missing)}")

    weights = [{name_by_idx[g.group]: g.weight for g in v.groups if g.weight > 1e-5} for v in me.vertices]
    edges = [tuple(e.vertices) for e in me.edges]
    adj = adjacency(n, edges, coincident_pairs([tuple(v.co) for v in me.vertices]))
    dom = dominant(weights)
    seeds = seam_seeds(dom, adj, pairs)
    if not seeds:
        raise RuntimeError(f"지정한 본 쌍 {a.pairs} 의 경계가 없다 — 고칠 것이 없거나 본 이름이 틀렸다")
    region = ring_region(seeds, adj, a.rings)
    print(f"[1/3] 정점 {n} · 경계 씨앗 {len(seeds)} · 띠 {len(region)} ({a.rings}겹)")

    new = smooth(weights, adj, region, a.iters, a.lam)
    changed = [u for u, w in new.items()
               if set(w) != set(weights[u]) or any(abs(w[b] - weights[u][b]) > 1e-4 for b in w)]
    print(f"[2/3] 스무딩 {a.iters}회 (lam {a.lam}) — 웨이트가 바뀐 정점 {len(changed)}")

    vgs = {vg.name: vg for vg in tr.vertex_groups}
    for vg in tr.vertex_groups:
        vg.remove(changed)
    for u in changed:
        for b, w in new[u].items():
            vgs[b].add([u], w, "REPLACE")

    co = [v.co for v in me.vertices]
    rest = [(co[i] - co[j]).length for i, j in edges if i in region and j in region]
    mw = tr.matrix_world
    zs = [(mw @ c).z for c in co]
    z0, z1 = min(zs), max(zs)
    zr = sorted(((mw @ co[u]).z - z0) / (z1 - z0) for u in region)
    out = {
        "stage": "5-4b", "script": "smooth_seams.py", "version": 1,
        "inputs": {"blend": a.blend}, "out": a.out,
        "pairs": sorted("|".join(sorted(p)) for p in pairs),
        "rings": a.rings, "iters": a.iters, "lam": a.lam,
        "seeds": len(seeds), "region": len(region), "changed": len(changed),
        "region_z_rel": [round(zr[0], 3), round(zr[len(zr) // 2], 3), round(zr[-1], 3)],
        "region_rest_edge_median": round(statistics.median(rest), 5) if rest else None,
        "rig_check": rig_check(tr, rig, name_by_idx),
    }
    bpy.ops.wm.save_as_mainfile(filepath=a.out)
    pj = a.out.rsplit(".", 1)[0] + "_smooth_params.json"
    with open(pj, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"[3/3] 저장: {a.out}\n파라미터: {pj}")


if __name__ == "__main__":
    main()
