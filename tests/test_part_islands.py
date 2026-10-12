"""부위 섬 찾기(part_islands.find_islands) 단위 시험 — Blender 없이 돈다.

작은 가짜 메쉬(정점을 일렬·덩어리로 이은 그래프)로 규칙을 하나씩 확인한다. 실제 메쉬
7건의 전·후 수치는 test_gate_g2r.py D 절이 고정한다.

2026-10-12 구현 중에 틀렸다가 고친 세 가지를 그대로 시험으로 남긴다:
  - 작은 덩어리끼리 서로 넘어가던 것   (자기보다 큰 이웃으로만 흡수)
  - UV 심의 중복 정점을 놓치던 것      (같은 좌표라도 따로 두고 잇는다)
  - 원래 이웃인 부위의 경계까지 고치던 것 (팔–다리, 팔–하부 몸통만)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from part_islands import ISLAND_MAX_RATIO, find_islands, limb_conflict, region_of


def chain(blocks):
    """[(본, 개수), …] 를 일렬로 이은 그래프. (dom, adj, 블록별 정점 범위) 를 돌려준다."""
    dom, spans = [], []
    for bone, k in blocks:
        spans.append(range(len(dom), len(dom) + k))
        dom += [bone] * k
    adj = [[] for _ in dom]
    for i in range(len(dom) - 1):
        adj[i].append(i + 1)
        adj[i + 1].append(i)
    return dom, adj, spans


def link(adj, a, b):
    adj[a].append(b)
    adj[b].append(a)


def main():
    ok = True

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")

    print("── 부위 묶음과 충돌 정의")
    check("region_of", (region_of("L_Wrist"), region_of("R_Knee"), region_of("Spine2"), region_of("L_Collar"))
          == ("L_arm", "R_leg", "torso", "torso"))
    check("팔–다리, 팔–하부 몸통은 충돌", limb_conflict("L_Wrist", "L_Hip") and limb_conflict("Spine1", "R_Elbow"))
    check("어깨–몸통, 다리–골반, 좌다리–우다리는 충돌이 아니다",
          not limb_conflict("L_Shoulder", "Spine3") and not limb_conflict("L_Hip", "Pelvis")
          and not limb_conflict("L_Knee", "R_Knee") and not limb_conflict("L_Elbow", "Spine3"))

    print("\n── 기본: 팔 안에 박힌 다리 라벨 섬은 팔로 돌아온다 (walker_walk_02 f138 의 경우)")
    # 다리 본체 400 … (떨어져 있음) … 팔 200 [그 안에 다리 섬 20] 팔 100
    dom, adj, sp = chain([("L_Hip", 400)])
    d2, a2, sp2 = chain([("L_Elbow", 200), ("L_Hip", 20), ("L_Wrist", 100)])
    off = len(dom)
    dom += d2
    adj += [[j + off for j in nb] for nb in a2]
    island = [i + off for i in sp2[1]]
    relabel, islands = find_islands(dom, adj)
    check("섬 20정점이 전부 L_arm 으로", sorted(relabel) == island and set(relabel.values()) == {"L_arm"},
          (len(relabel), set(relabel.values())))
    check("섬 기록: from L_leg → to L_arm, 20정점", len(islands) == 1
          and (islands[0]["from"], islands[0]["to"], islands[0]["verts"]) == ("L_leg", "L_arm", 20), islands)

    print("\n── 섬이 없으면 아무것도 바꾸지 않는다 (합격 샘플의 불변 조건)")
    dom, adj, _ = chain([("L_Hand", 30), ("L_Wrist", 60), ("L_Elbow", 100), ("L_Shoulder", 100),
                         ("L_Collar", 50), ("Spine3", 200), ("Spine1", 200), ("Pelvis", 80), ("L_Hip", 300)])
    relabel, islands = find_islands(dom, adj)
    check("정상 사슬(손 → 팔 → 몸통 → 다리): 재배정 0", relabel == {} and islands == [], len(relabel))

    print("\n── 원래 이웃인 부위의 경계는 건드리지 않는다 (f6+1536 에서 6,614정점이 바뀌던 것)")
    # 몸통 본체 안에 다리(Hip) 라벨 조각 — 골반 주변에서 흔하다. 결함이 아니다.
    dom, adj, sp = chain([("L_Hip", 400)])
    d2, a2, sp2 = chain([("Spine1", 300), ("L_Hip", 15), ("Pelvis", 300)])
    off = len(dom)
    dom += d2
    adj += [[j + off for j in nb] for nb in a2]
    relabel, _ = find_islands(dom, adj)
    check("몸통 안의 Hip 조각: 그대로", relabel == {}, len(relabel))
    # 어깨의 팔–상부 몸통도 마찬가지
    dom, adj, _ = chain([("Spine3", 300), ("L_Shoulder", 10), ("L_Collar", 50), ("L_Shoulder", 200)])
    relabel, _ = find_islands(dom, adj)
    check("상부 몸통 안의 Shoulder 조각: 그대로", relabel == {}, len(relabel))
    # 좌다리–우다리 (다리 융합은 키프레임의 문제이고 ② 가 본다)
    dom, adj, _ = chain([("L_Knee", 300), ("R_Knee", 20), ("L_Ankle", 100)])
    d2, a2, _ = chain([("R_Knee", 400)])
    off = len(dom)
    dom += d2
    adj += [[j + off for j in nb] for nb in a2]
    relabel, _ = find_islands(dom, adj)
    check("왼다리 안의 오른다리 조각: 그대로", relabel == {}, len(relabel))

    print("\n── 자기보다 큰 이웃으로만 흡수된다 (손이 소매와 떨어진 별개 조각일 때)")
    # 팔 본체 500 (따로) / 다리 본체 500 (따로) / 손 조각: 팔 라벨 60 + 다리 라벨 섬 15
    # 손 조각의 팔 덩어리(60)는 팔 본체(500)에 비해 작지만, 옆의 섬(15)으로 넘어가면 안 된다.
    dom, adj, _ = chain([("L_Elbow", 500)])
    for blocks in ([("L_Hip", 500)], [("L_Wrist", 60), ("L_Hip", 15)]):
        d2, a2, sp2 = chain(blocks)
        off = len(dom)
        dom += d2
        adj += [[j + off for j in nb] for nb in a2]
    hand = list(range(1000, 1060))
    isl = list(range(1060, 1075))
    relabel, islands = find_islands(dom, adj)
    check("섬 15정점 → L_arm, 손 조각의 팔 60정점은 그대로",
          sorted(relabel) == isl and set(relabel.values()) == {"L_arm"} and not set(hand) & set(relabel),
          (sorted(relabel)[:3], len(relabel)))

    print("\n── UV 심의 중복 정점 (같은 좌표, 다른 웨이트)")
    # 팔 100정점. 그중 한 자리에 중복 정점이 하나 있고 그것만 다리 본을 받았다.
    # 호출하는 쪽이 같은 좌표끼리 가상 엣지로 잇는다 — 여기서는 그 엣지를 직접 넣는다.
    dom, adj, _ = chain([("L_Wrist", 100)])
    d2, a2, _ = chain([("L_Hip", 300)])
    off = len(dom)
    dom += d2
    adj += [[j + off for j in nb] for nb in a2]
    dup = len(dom)
    dom.append("L_Hip")           # 정점 40 과 같은 좌표의 중복
    adj.append([])
    link(adj, 40, dup)
    relabel, _ = find_islands(dom, adj)
    check("중복 정점 하나짜리 섬도 잡는다", relabel == {dup: "L_arm"}, relabel)

    print("\n── 크기와 연결")
    # 섬이 그 부위 본체의 25% 이상이면 섬이 아니다 (본체가 둘로 나뉜 것일 수 있다)
    big = int(400 * ISLAND_MAX_RATIO)
    dom, adj, _ = chain([("L_Hip", 400)])
    d2, a2, _ = chain([("L_Elbow", 600), ("L_Hip", big), ("L_Wrist", 600)])
    off = len(dom)
    dom += d2
    adj += [[j + off for j in nb] for nb in a2]
    relabel, _ = find_islands(dom, adj)
    check(f"본체의 {int(ISLAND_MAX_RATIO * 100)}% 크기({big}정점)는 건드리지 않는다", relabel == {}, len(relabel))
    # 다른 부위와 맞닿지 않은 조각(떨어진 장식)은 건드리지 않는다
    dom, adj, _ = chain([("L_Hip", 400)])
    d2, a2, _ = chain([("L_Wrist", 30)])
    dom += d2
    adj += [[j + 400 for j in nb] for nb in a2]
    relabel, _ = find_islands(dom, adj)
    check("어디에도 맞닿지 않은 조각: 그대로", relabel == {}, len(relabel))
    # 웨이트가 없는 정점(None)은 경계를 만들지 않는다
    dom, adj, _ = chain([("L_Elbow", 200), (None, 5), ("L_Hip", 20)])
    d2, a2, _ = chain([("L_Hip", 400)])
    dom += d2
    adj += [[j + 225 for j in nb] for nb in a2]
    relabel, _ = find_islands(dom, adj)
    check("웨이트 없는 정점 너머의 조각: 그대로", relabel == {}, len(relabel))

    print("\n── 붙은 메쉬는 못 고친다 (알려진 한계 — 파일럿 f18)")
    # 팔 본체와 다리 본체가 직접 이어져 있다. 어느 쪽도 섬이 아니다.
    dom, adj, _ = chain([("L_Wrist", 300), ("L_Hip", 400)])
    relabel, islands = find_islands(dom, adj)
    check("팔 본체–다리 본체가 맞닿음: 재배정 0 (경계는 그대로 남는다)", relabel == {} and islands == [])

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
