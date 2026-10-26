"""G4 게이트: 5-5 로 구운 클립의 "늘어남" · "발 쓸기" · "바닥" 을 재고 판정한다 (판정 규칙은 g4_rules.py).

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background --python gate_g4.py -- \\
      --blend ~/data/06_rig/<리그>/motions/<클립>/animated.blend \\
      --clip <클립 이름> [--roles ~/data/06_rig/<캐릭터>/clip_roles.json] --out <폴더>

출력: <out>/g4_<클립>.json + 표준출력 한 줄 ("G4 <판정> <클립> …"). 판정과 무관하게 종료 코드 0 —
CHECK/FAIL 은 사람이 본다(일괄 표는 tools/review/g4_report.py). 측정 실패만 1.

측정은 2026-10-19~22 수작업 측정(tools/review 의 dump2 · edge_stats, footslide)을 한 번에 옮긴 것이다.
  늘어남  rest 메쉬 대비 엣지 길이가 4배 넘고 0.05 / 0.10 넘는 엣지 수를 프레임마다 세서 최대값, 최장 길이.
          최악 프레임의 상위 본 쌍(양 끝 정점의 지배 본)을 함께 남긴다 — 어디가 늘었는지 보려고.
  발 쓸기 SMPL 발 본(L/R_Foot · Ankle)의 월드 위치. 접지 = 발 높이가 최저 5% 분위 + 키의 3% 안, 첫 1초 제외.
          접지 프레임에서 발의 골반 기준 수평 속도를 전방(발끝 방향 평균)으로 투영한 중앙값을 H/초 로.
  바닥    프레임별 메쉬 최저점 − rest 메쉬 최저점. 처음 · 끝 6프레임 안의 최저값과 전체 최저값(가장 깊이 묻힌 곳).
"""
import argparse
import json
import sys
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from g4_rules import judge  # noqa: E402
from ground_align import WINDOW  # noqa: E402

STRETCH = 4.0


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--clip", required=True, help="클립 이름 (납품 이름 또는 굽기 폴더 이름 — clip_roles 의 source)")
    ap.add_argument("--roles", default=None, help="clip_roles.json (없으면 역할 미지정으로 판정)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--rig-name", default="SMPL_rig")
    return ap.parse_args(argv)


def world_co(mesh_data, mw):
    a = np.empty(len(mesh_data.vertices) * 3, np.float32)
    mesh_data.vertices.foreach_get("co", a)
    a = a.reshape(-1, 3)
    M = np.array(mw)
    return a @ M[:3, :3].T + M[:3, 3]


def measure(rig, mesh, sc, fps):
    name = {vg.index: vg.name for vg in mesh.vertex_groups}
    n = len(mesh.data.vertices)
    dom = np.full(n, -1, np.int32)
    names = sorted(set(name.values()))
    nid = {b: i for i, b in enumerate(names)}
    for v in mesh.data.vertices:
        if v.groups:
            g = max(v.groups, key=lambda g: g.weight)
            if g.weight >= 1e-4:
                dom[v.index] = nid[name[g.group]]
    E = np.empty(len(mesh.data.edges) * 2, np.int32)
    mesh.data.edges.foreach_get("vertices", E)
    E = E.reshape(-1, 2)
    rest = world_co(mesh.data, mesh.matrix_world)
    rl = np.linalg.norm(rest[E[:, 0]] - rest[E[:, 1]], axis=1)
    ok = rl > 1e-6
    a, b = dom[E[:, 0]], dom[E[:, 1]]
    lo, hi = np.minimum(a, b), np.maximum(a, b)

    bones = ["Pelvis", "L_Ankle", "R_Ankle", "L_Foot", "R_Foot", "Head"]
    missing = [x for x in bones if x not in rig.pose.bones]
    P = {x: [] for x in bones if x not in missing}
    per = []
    lows = []
    worst = (-1, None, None)
    frames = list(range(sc.frame_start, sc.frame_end + 1))
    for f in frames:
        sc.frame_set(f)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = mesh.evaluated_get(dg)
        me = ev.to_mesh()
        c = world_co(me, ev.matrix_world)
        ev.to_mesh_clear()
        lows.append(float(c[:, 2].min()))
        ln = np.linalg.norm(c[E[:, 0]] - c[E[:, 1]], axis=1)
        st = ok & (ln > STRETCH * np.where(ok, rl, 1))
        s5, s10 = st & (ln > 0.05), st & (ln > 0.10)
        per.append((int(s5.sum()), int(s10.sum()), float(ln[st].max()) if st.any() else 0.0))
        if s10.sum() > worst[0]:
            worst = (int(s10.sum()), f, s10.copy())
        for x in P:
            P[x].append(list(rig.matrix_world @ rig.pose.bones[x].head))
    top = {}
    if worst[2] is not None and worst[0] > 0:
        k = (lo[worst[2]] + 1) * 1000 + (hi[worst[2]] + 1)      # -1(웨이트 없음)도 담도록 +1
        u, cnt = np.unique(k, return_counts=True)
        lab = lambda i: names[i - 1] if i > 0 else "-"
        top = {f"{lab(int(x) // 1000)}|{lab(int(x) % 1000)}": int(m) for x, m in sorted(zip(u, cnt), key=lambda t: -t[1])[:5]}
    edges = {"max05": max(p[0] for p in per), "max10": max(p[1] for p in per),
             "longest": round(max(p[2] for p in per), 4), "f_max10": worst[1] if worst[0] > 0 else None, "top_pairs": top}

    sweep = None
    if not missing:
        P = {x: np.array(v) for x, v in P.items()}
        H = float(np.median(P["Head"][:, 2] - np.minimum(P["L_Ankle"][:, 2], P["R_Ankle"][:, 2])))
        fw = np.concatenate([P["L_Foot"] - P["L_Ankle"], P["R_Foot"] - P["R_Ankle"]])[:, :2].mean(0)
        fw = fw / np.linalg.norm(fw)
        hv = lambda x: np.gradient(x[:, :2], axis=0) * fps
        pel = hv(P["Pelvis"])
        skip = int(round(fps))
        sweep = {"H": round(H, 4)}
        for s in ("L", "R"):
            foot = P[f"{s}_Foot"]
            z = np.minimum(P[f"{s}_Ankle"][:, 2], foot[:, 2])
            contact = z < np.percentile(z, 5) + 0.03 * H
            contact[:skip] = False
            rel = hv(foot) - pel
            sweep[s] = round(float(np.median(rel[contact] @ fw)) / H, 3) if contact.any() else None
            sweep[f"{s}_contact_frac"] = round(float(contact.sum()) / max(1, len(frames) - skip), 3)
        d = P["Pelvis"][-1, :2] - P["Pelvis"][0, :2]
        sweep["root_disp_fwd_H"] = round(float(d @ fw) / H, 3)
    d = np.array(lows) - float(rest[:, 2].min())
    k = min(WINDOW, len(d))
    ground = {"floor": round(float(rest[:, 2].min()), 4), "first": round(float(d[:k].min()), 4),
              "last": round(float(d[-k:].min()), 4), "sink": round(float(d.min()), 4), "f_sink": frames[int(np.argmin(d))]}
    return edges, sweep, ground, len(frames), missing


def main():
    a = parse_args()
    bpy.ops.wm.open_mainfile(filepath=a.blend)
    sc = bpy.context.scene
    rig = bpy.data.objects.get(a.rig_name)
    if rig is None:
        raise RuntimeError(f"{a.rig_name} 없음")
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.name != "SMPL_body"]
    if not meshes:
        raise RuntimeError("메쉬 없음")
    mesh = max(meshes, key=lambda o: len(o.data.vertices))
    fps = sc.render.fps / sc.render.fps_base
    edges, sweep, ground, nframes, missing = measure(rig, mesh, sc, fps)
    roles = json.load(open(a.roles)) if a.roles else None
    res = judge(a.clip, edges, sweep, roles, ground)
    res.update(gate="G4", version=2, blend=a.blend, frames=nframes, roles_file=a.roles,
               missing_bones=missing)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"g4_{res['clip']}.json"
    p.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    sw = res["sweep"]
    print(f"G4 {res['verdict']} {res['clip']}  늘어남 {res['edges']['verdict']} (0.10 초과 {edges['max10']}, 최장 {edges['longest']})"
          f"  발 쓸기 {sw['verdict']} (나쁜 발 {sw['worst']})"
          f"  바닥 {res['ground']['verdict']} (시작 {ground['first']:+.3f} · 끝 {ground['last']:+.3f} · 최저 {ground['sink']:+.3f})  → {p}")


if __name__ == "__main__":
    main()
