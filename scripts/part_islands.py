"""부위 섬 찾기 — 웨이트 전이의 부위 제약(transfer_weights.part_constraint)이 쓰는 순수 로직.

Blender 없이 돈다 (bpy 를 쓰지 않는다). 그래서 tests/ 에서 그대로 시험할 수 있다.
무엇을 왜 하는지는 transfer_weights.part_constraint 의 독스트링에 있다.
"""

# 부위 — 본을 다섯 덩어리로 묶는다.
def region_of(bone):
    if bone.endswith(("Shoulder", "Elbow", "Wrist", "Hand")):
        return bone[0] + "_arm"
    if bone.endswith(("Hip", "Knee", "Ankle", "Foot")):
        return bone[0] + "_leg"
    return "torso"


# 팔에는 위팔(Shoulder)도 든다 — 2026-10-12 에 넣었다. 그 전에는 팔꿈치 아래만 팔로 봐서,
# walker f138 의 위팔–Spine1 엣지 961개를 ⑤ 가 0 으로 기록했고 섬 고치기도 손대지 않았다
# (roar_02 에서 팔을 들자 그 엣지가 막처럼 늘어났다). 위팔과 **상부** 몸통(Spine3 · Collar ·
# Neck)은 원래 이웃이라 충돌이 아니다 — _LOW 에 없다.
_ARM, _LEG, _LOW = ("Shoulder", "Elbow", "Wrist", "Hand"), ("Hip", "Knee", "Ankle", "Foot"), ("Pelvis", "Spine1", "Spine2")


def limb_conflict(a, b):
    """두 본이 "떨어져 있어야 할 부위" 사이인가 — 팔–다리, 팔–하부 몸통 (G2r ⑤ 의 정의)."""
    aa, ab = a.endswith(_ARM), b.endswith(_ARM)
    return (aa and (b.endswith(_LEG) or b in _LOW)) or (ab and (a.endswith(_LEG) or a in _LOW))


# 섬으로 보는 크기 상한 — 그 부위의 가장 큰 덩어리에 대한 비율. 2026-10-12 실측에서
# 오배정 섬은 f138 1,806정점 · f18 9,671정점이었고 다리 본체는 12만~15만 정점이다
# (1.5% · 6.4%). 25% 는 그 위로 넉넉히 잡은 값이다.
ISLAND_MAX_RATIO = 0.25



def find_islands(dom, adj):
    """섬을 찾아 (정점 → 새 부위, 섬 목록) 을 돌려준다.

    dom  정점별 지배 본 이름 (없으면 None)
    adj  정점별 이웃 목록 — 메쉬 엣지 + 같은 좌표 정점끼리의 가상 엣지
    """
    n = len(dom)
    members = range(n)
    label = [region_of(b) if b else None for b in dom]
    lab = list(label)

    def components():
        """같은 라벨끼리 이어진 덩어리. (덩어리 목록, 정점→덩어리 번호) 를 돌려준다."""
        comp_of, comps = {}, []
        for r in members:
            if r in comp_of or lab[r] is None:
                continue
            cid, stack, grp = len(comps), [r], []
            comp_of[r] = cid
            while stack:
                u = stack.pop()
                grp.append(u)
                for w in adj[u]:
                    if w not in comp_of and lab[w] == lab[r]:
                        comp_of[w] = cid
                        stack.append(w)
            comps.append((lab[r], grp))
        return comps, comp_of

    # 섬 찾기 → **자기보다 큰 이웃 덩어리** 중 가장 길게 맞닿은 쪽으로.
    # "자기보다 큰" 이 중요하다. 손이 소매와 떨어진 별개 메쉬 조각일 때, 그 조각 안의 팔 라벨
    # 덩어리도 팔 본체에 비하면 작다. 맞닿은 길이만 보면 그것이 옆의 다리 라벨 섬으로 넘어가
    # 버린다(처음 구현이 그랬다). 큰 쪽이 작은 쪽을 흡수하게 하면 손 조각은 팔로 남는다.
    # 흡수하면 덩어리가 다시 짜이므로 바뀌는 것이 없을 때까지 되풀이한다.
    relabel, islands = {}, []
    for _ in range(8):
        comps, comp_of = components()
        biggest = {}
        for reg, grp in comps:
            biggest[reg] = max(biggest.get(reg, 0), len(grp))
        moved = 0
        for cid, (reg, grp) in sorted(enumerate(comps), key=lambda t: len(t[1][1])):
            if len(grp) >= biggest[reg] * ISLAND_MAX_RATIO:
                continue
            # **떨어져 있어야 할 부위끼리 맞닿은 엣지**만 센다 (G2r ⑤ 와 같은 정의 — 팔–다리,
            # 팔–하부 몸통). 어깨의 팔–몸통, 골반의 다리–몸통처럼 원래 이웃인 부위의 경계는
            # 들쭉날쭉한 것이 정상이라 건드리지 않는다. 처음에는 모든 섬을 고쳤는데, 합격 샘플
            # f6+1536 에서 골반 주변의 다리 라벨 조각 6,614정점(0.79%)이 몸통으로 넘어갔다 —
            # 결함이 아닌 것을 바꾼 것이다. 좌다리–우다리도 뺐다(다리 융합은 키프레임의 문제이고
            # 걷는 자세의 zombie1 이 여기서 바뀐다).
            border = {}
            for u in grp:
                for w in adj[u]:
                    if lab[w] is not None and lab[w] != reg and limb_conflict(dom[u], dom[w]):
                        c = comp_of[w]
                        border[c] = border.get(c, 0) + 1
            bigger = {c: k for c, k in border.items() if len(comps[c][1]) > len(grp)}
            if not bigger:
                continue                       # 고칠 경계가 없다
            to_c = max(bigger, key=bigger.get)
            to = comps[to_c][0]
            if lab[grp[0]] != reg:
                continue                       # 이번 바퀴에서 이미 바뀐 덩어리
            islands.append({"from": reg, "to": to, "verts": len(grp), "border": bigger[to_c]})
            for u in grp:
                lab[u] = to
                relabel[u] = to
            moved += 1
        if not moved:
            break
    # 원래 라벨로 돌아온 것은 건드리지 않는다
    relabel = {u: to for u, to in relabel.items() if to != label[u]}
    return relabel, islands
