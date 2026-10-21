"""웨이트 경계 스무딩 · 이음매 용접 — transfer_weights(5-4) 와 smooth_seams(5-4 뒤 후처리)가 쓰는 순수 로직.

Blender 없이 돈다 (bpy 를 쓰지 않는다). 그래서 tests/ 에서 그대로 시험할 수 있다.

두 가지를 한다.

1. **이음매 용접** (`coincident_pairs`) — TRELLIS 메쉬는 UV 이음매에서 정점이 갈라져 있어 메쉬
   엣지만 따라가면 이음매를 넘지 못한다. 같은 좌표의 정점끼리 가상 엣지로 잇는다. 부위 제약
   (transfer_weights.part_constraint)이 2026-10-12 부터 쓰던 규칙과 같다(소수 5자리 반올림).
   2026-10-19 실측: listener_apose_06 은 엣지만으로는 가장 큰 조각이 3,707정점이었고, 용접하면
   본체 한 덩어리(738,876 / 747,813)가 된다. 5-4 의 BFS 전파가 이걸 몰라서 몸에 붙은 정점
   87,076개(11.64%)를 고립 조각으로 보고 직선거리 폴백을 줬다 — 용접하면 4,950개(0.66%).
   단 5-4 BFS 에서는 기본 off 로 둔다 — 같은 날 실측에서 늘어남이 늘었다(transfer_weights 독스트링).

   2026-10-21 가랑이(L_Hip:R_Hip, 10겹 · 40회) 실측: 04b 가랑이 0.10 초과 471 → 0(f34),
   전체 579 → 72, 최장 0.179 → 0.119. 납품 10편을 다시 구워도 0.10 초과는 한 편도 늘지 않았고
   대기 · 걷기 6편은 수치가 같았다(띠 밖 불변).

2. **경계 스무딩** (`seam_seeds` · `ring_region` · `smooth`) — 지정한 본 쌍(예: 왼다리–오른다리)이
   지배하는 두 정점을 잇는 엣지가 "딱 잘린 경계" 다. 2026-10-19 진단: listener 04b f34 에서
   늘어난 가랑이 엣지 666개 중 580개가 1차 전이끼리의 경계이고, 양 끝 지배 웨이트 중앙값이
   0.974 — 한 정점은 왼다리만, 옆 정점은 오른다리만 따른다. 다리가 벌어지면 그 한 줄이 찢어지듯
   늘어난다. 경계에서 몇 겹 안의 정점만 이웃 평균으로 웨이트를 고르게 해, 벌어짐을 띠 전체가
   나눠 받게 한다. 띠 밖의 정점은 고정(경계 조건)이라 띠 밖 웨이트는 한 정점도 바뀌지 않는다.
"""

WELD_DIGITS = 5          # 같은 좌표로 볼 반올림 자릿수 — part_constraint 와 같은 값
PRUNE = 1e-4             # 이보다 작은 웨이트는 버리고 다시 정규화


def coincident_pairs(coords, digits=WELD_DIGITS):
    """같은 좌표(반올림)의 정점 쌍 [(첫 정점, 나중 정점), …]. coords: [(x, y, z), …]."""
    first, pairs = {}, []
    for i, (x, y, z) in enumerate(coords):
        k = (round(x, digits), round(y, digits), round(z, digits))
        j = first.get(k)
        if j is None:
            first[k] = i
        else:
            pairs.append((j, i))
    return pairs


def adjacency(n, edges, extra=()):
    """정점별 이웃 목록. edges · extra: [(a, b), …]."""
    adj = [[] for _ in range(n)]
    for a, b in edges:
        adj[a].append(b)
        adj[b].append(a)
    for a, b in extra:
        adj[a].append(b)
        adj[b].append(a)
    return adj


def dominant(weights):
    """정점별 지배 본 (웨이트 없으면 None). weights: [{본: w}, …]."""
    return [max(w, key=w.get) if w else None for w in weights]


def seam_seeds(dom, adj, pairs):
    """지정한 본 쌍이 지배하는 두 정점을 잇는 엣지의 양 끝 정점 집합.

    pairs: {frozenset({"L_Hip", "R_Hip"}), …}
    """
    seeds = set()
    for u, nb in enumerate(adj):
        a = dom[u]
        if a is None:
            continue
        for v in nb:
            b = dom[v]
            if b is not None and a != b and frozenset((a, b)) in pairs:
                seeds.add(u)
                seeds.add(v)
    return seeds


def ring_region(seeds, adj, rings):
    """씨앗에서 엣지로 rings 겹 안의 정점 집합 (씨앗 포함)."""
    region, frontier = set(seeds), list(seeds)
    for _ in range(rings):
        nxt = []
        for u in frontier:
            for v in adj[u]:
                if v not in region:
                    region.add(v)
                    nxt.append(v)
        frontier = nxt
    return region


def _normalize(w):
    w = {b: x for b, x in w.items() if x > PRUNE}
    t = sum(w.values())
    return {b: x / t for b, x in w.items()} if t > 0 else {}


def smooth(weights, adj, region, iters, lam=0.5):
    """region 안의 정점만 이웃 평균 쪽으로 iters 번 끌어당긴다 (야코비 방식 — 한 바퀴 안에서는
    이전 값만 읽는다). region 밖의 정점은 읽기만 한다(고정). 돌려주는 것: {정점: 새 웨이트}.

    w_i ← (1 - lam) · w_i + lam · 평균(w_이웃)
    """
    cur = {u: dict(weights[u]) for u in region}
    get = lambda v: cur[v] if v in cur else weights[v]
    order = sorted(region)
    for _ in range(iters):
        nxt = {}
        for u in order:
            nb = adj[u]
            if not nb:
                nxt[u] = cur[u]
                continue
            avg = {}
            for v in nb:
                for b, x in get(v).items():
                    avg[b] = avg.get(b, 0.0) + x
            k = 1.0 / len(nb)
            w = {b: (1 - lam) * x for b, x in cur[u].items()}
            for b, x in avg.items():
                w[b] = w.get(b, 0.0) + lam * x * k
            nxt[u] = _normalize(w)
        cur = nxt
    return cur
