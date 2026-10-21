"""웨이트 경계 스무딩 · 이음매 용접(seam_smooth) 단위 시험 — Blender 없이 돈다.

작은 가짜 메쉬로 규칙을 하나씩 확인한다:
  - 같은 좌표 정점이 용접되고, 다른 좌표는 용접되지 않는다
  - 지정한 본 쌍의 경계만 씨앗이 된다 (원래 이웃인 경계는 아님)
  - 띠 밖의 정점은 한 정점도 바뀌지 않는다
  - 띠 안의 딱 잘린 경계가 완만해지고, 웨이트 합은 1 을 유지한다
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from seam_smooth import adjacency, coincident_pairs, dominant, ring_region, seam_seeds, smooth

ok = True


def check(msg, cond):
    global ok
    print(("   ✅ " if cond else "   ❌ ") + msg)
    ok = ok and cond


def strip(blocks):
    """[(본, 개수), …] 를 일렬로 이은 띠. (weights, adj)"""
    w = []
    for bone, k in blocks:
        w += [{bone: 1.0} for _ in range(k)]
    edges = [(i, i + 1) for i in range(len(w) - 1)]
    return w, adjacency(len(w), edges)


def main():
    print("── 이음매 용접")
    coords = [(0, 0, 0), (1, 0, 0), (0, 0, 0.000001), (1.00001, 0, 0)]
    p = coincident_pairs(coords)
    check("반올림 5자리 안의 같은 좌표만 잇는다: [(0, 2)]", p == [(0, 2)])
    # 엣지만으로는 0-1, 2-3 두 조각. 용접하면 한 조각.
    adj = adjacency(4, [(0, 1), (2, 3)], p)
    check("용접 뒤 0 → 3 으로 갈 수 있다", 3 in ring_region({0}, adj, 3))
    adj0 = adjacency(4, [(0, 1), (2, 3)])
    check("용접 없이는 0 → 3 으로 못 간다", 3 not in ring_region({0}, adj0, 3))

    print("\n── 씨앗 = 지정한 본 쌍의 경계만")
    w, adj = strip([("L_Hip", 10), ("R_Hip", 10), ("Pelvis", 10)])
    dom = dominant(w)
    seeds = seam_seeds(dom, adj, {frozenset(("L_Hip", "R_Hip"))})
    check("L_Hip|R_Hip 경계의 양 끝 두 정점만", seeds == {9, 10})
    check("R_Hip|Pelvis 경계(원래 이웃)는 씨앗이 아니다", 19 not in seeds and 20 not in seeds)

    print("\n── 띠 안만 스무딩, 띠 밖은 고정")
    region = ring_region(seeds, adj, 3)
    check("3 겹 띠 = 정점 6..13", region == set(range(6, 14)))
    new = smooth(w, adj, region, iters=20)
    check("바뀐 정점은 띠 안의 것뿐", set(new) <= region)
    outside_same = all(w[i] == {"L_Hip": 1.0} for i in range(6)) and all(w[i] == {"R_Hip": 1.0} for i in range(14, 20))
    check("원본 웨이트 목록(띠 밖)은 그대로", outside_same)
    check("모든 새 웨이트의 합이 1", all(abs(sum(x.values()) - 1) < 1e-9 for x in new.values()))
    lo, hi = new[9]["L_Hip"], new[10]["L_Hip"]
    check(f"경계 바로 양쪽이 섞였다 (f9 L_Hip {lo:.2f}, f10 L_Hip {hi:.2f}, 원래 1 · 0)", 0.2 < hi < lo < 0.8)
    mono = all(new[i].get("L_Hip", 0) >= new[i + 1].get("L_Hip", 0) - 1e-12 for i in range(6, 13))
    check("띠 안에서 L_Hip 비중이 한 방향으로 줄어든다 (완만한 경사)", mono)

    print("\n── 경계가 없으면 아무것도 바뀌지 않는다")
    w2, adj2 = strip([("L_Hip", 10), ("Pelvis", 10)])
    s2 = seam_seeds(dominant(w2), adj2, {frozenset(("L_Hip", "R_Hip"))})
    check("씨앗 0", s2 == set())
    check("스무딩 결과 0 정점", smooth(w2, adj2, ring_region(s2, adj2, 5), iters=10) == {})

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
