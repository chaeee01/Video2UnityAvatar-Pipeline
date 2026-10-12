"""G2r ④ 폴백 분포 판정 시험 — 확보된 표본 2건을 올바로 가르는지.

시험지는 2026-10-07 에 transfer_weights.py 를 두 rigged.blend 에 다시 돌려 얻은
fallback_detail 실측이다 (Blender 없이 돌도록 판정에 쓰는 값만 옮겨 적었다).

    char_shuffle f60       폴백 3.7075%   육안 불합격 (10/1)
    char_shuffle f6+1536   폴백 8.9206%   육안 합격   (10/6)

C 절은 ①②③(본→메쉬 거리 · 좌우 교차 배정 · 지배 정점 0)을, D 절은 ⑤(떨어져 있어야 할
부위를 잇는 엣지)를 7샘플 실측으로 고정한다.

확인하는 것:
  A. 분류기 자체가 둘을 가르는가 (f60 위험 / f6 무해) + 잡음 가드
  B. 게이트 — **상시 평가**다. 위험 분류면 폴백 총량이 경고선 아래여도 경고한다.
     f60 이 "경고", f6+1536 이 "무해" 로 갈리는 것이 이 시험의 핵심이다.
     어느 쪽도 불합격(FAIL)을 만들지는 않는다.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from gate_g2r import FALLBACK_WARN_PCT, FB_MIN_VERTS, classify_fallback, judge

F60 = {   # 불합격 표본. L_Elbow 한 본으로 26.8% 가 갔다.
    "verts": 26315, "limb_pct": 47.528, "cross_side_pct": 0.034,
    "src_dist": {"median": 0.02518, "p90": 0.06064, "max": 0.08842},
    "by_bone": {"Spine3": 8245, "L_Elbow": 7050, "Spine1": 5409, "L_Hip": 3497},
}
F6 = {    # 합격 표본. Head 58.9% + Collar 27.2% — 강체 본에 집중.
    "verts": 74357, "limb_pct": 1.844, "cross_side_pct": 0.042,
    "src_dist": {"median": 0.00849, "p90": 0.02289, "max": 0.03818},
    "by_bone": {"Head": 43774, "L_Collar": 11782, "R_Collar": 8449, "Spine3": 3522},
}


def metrics(scale, iou, jd, fb, detail):
    return {"scale": scale, "bbox_iou": iou, "joint_dist": jd, "fallback_pct": fb,
            "unassigned_pct": 0.0, "fallback_detail": detail}


def main():
    ok = True

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")

    print("── A. 분류기가 표본 2건을 가르는가")
    c60, why60 = classify_fallback(F60)
    c6, why6 = classify_fallback(F6)
    check("f60 (불합격) → 위험", c60 == "risky", f"{c60} {why60}")
    check("f6+1536 (합격) → 무해", c6 == "benign", c6)
    check("f60 은 소스거리(p90 0.0606 > 0.04)로 걸린다", len(why60) == 1 and "소스거리" in why60[0], why60)
    # 사지 본 비율 축은 2026-10-12 에 뺐다 — 사지 본 100% 라도 가까이서 빌렸으면 무해다.
    near = dict(F6, limb_pct=100.0)
    check("사지 본 100% + 소스거리 가까움 → 무해 (파일럿 오탐의 경우)", classify_fallback(near)[0] == "benign")
    check("자료 없음 → None", classify_fallback(None)[0] is None)
    few = dict(F60, verts=FB_MIN_VERTS - 1)
    check(f"잡음 가드: 폴백 {FB_MIN_VERTS - 1}정점 → too_few (f60 분포여도 분류 안 함)",
          classify_fallback(few)[0] == "too_few")
    check(f"잡음 가드 경계: {FB_MIN_VERTS}정점부터 분류",
          classify_fallback(dict(F60, verts=FB_MIN_VERTS))[0] == "risky")

    print("\n── B. 게이트 — 상시 평가 (총량과 무관하게 분포로 경고)")
    # f60 실측: 총량은 경고선 아래(3.7075%)지만 분포가 위험하다 → 경고가 떠야 한다.
    m = metrics(0.62039, 0.9762, 0.028714, 3.7075, F60)
    v, reasons, warns = judge(m)
    check("f60: 판정은 PASS 유지 (불합격으로 바꾸지 않는다)", v == "PASS" and not reasons, v)
    check("f60: 총량 3.7075% < 8% 인데도 '분포 위험' 경고",
          len(warns) == 1 and "분포 위험" in warns[0] and "아래다" in warns[0], warns)
    check("f60: 기록 (class risky, over_warn_pct False)",
          m["fallback_check"] == {"class": "risky", "why": why60, "over_warn_pct": False})

    # f6+1536 실측: 총량은 경고선 위(8.9206%)지만 분포가 무해하다.
    m = metrics(0.566748, 0.8828, 0.025636, 8.9206, F6)
    v, reasons, warns = judge(m)
    check("f6: PASS", v == "PASS" and not reasons, v)
    check("f6: '분포 무해' + 상위 본", len(warns) == 1 and "분포 무해" in warns[0]
          and "Head 43774" in warns[0] and "위험" not in warns[0] and "사지 본" not in warns[0], warns)
    check("f6: 기록 (class benign, over_warn_pct True)",
          m["fallback_check"]["class"] == "benign" and m["fallback_check"]["over_warn_pct"])

    # 네 칸의 나머지 둘
    m = metrics(0.6, 0.9, 0.03, 3.0, F6)
    v, _, warns = judge(m)
    check("총량 낮음 + 분포 무해 → 경고 없음", v == "PASS" and not warns, warns)
    m = metrics(0.6, 0.9, 0.03, 9.5, F60)
    v, _, warns = judge(m)
    check("총량 높음 + 분포 위험 → '분포 위험' 경고, 판정은 PASS",
          v == "PASS" and len(warns) == 1 and "분포 위험" in warns[0] and "넘는다" in warns[0], warns)

    # 분포를 판정하지 못한 채 경고선을 넘으면 조용히 넘기지 않는다.
    for label, det in (("자료 없음", None), ("정점 부족", few)):
        v, _, warns = judge(metrics(0.6, 0.9, 0.03, 9.5, det))
        check(f"{label}(9.5%): '분포를 판정하지 못했다' 경고",
              v == "PASS" and len(warns) == 1 and "분포를 판정하지 못했다" in warns[0], warns)
    # 자료 없이 총량도 낮으면 종전과 같다 (경고 없음) — 구버전 JSON 호환.
    v, _, warns = judge(metrics(0.6, 0.9, 0.03, 3.0, None))
    check("자료 없음(3.0%): 종전대로 경고 없음", v == "PASS" and not warns, warns)

    print("\n── C. ①②③ 리깅 지표 — 5샘플 실측 고정 (tests/fixtures/g2r_rig_check.json)")
    import json
    fx = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "g2r_rig_check.json")))

    def run(name):
        d = fx[name]
        m = metrics(0.6, 0.9, 0.03, d["fallback_pct"], d["fallback_detail"])
        m["rig_check"] = d["rig_check"]
        v, reasons, warns = judge(m)
        return v, reasons, warns, m["rig_flags"]

    # 고정 자료는 **부위 제약을 거친 뒤**의 rig_check 다 (2026-10-12~). 판정도 그 값으로 한다.
    # f60 — 불합격이어야 한다. 제약이 왼손목의 정점을 되돌려 ③ 은 풀렸지만(0 → 3,445),
    # 손목 본이 메쉬에서 0.064 떨어져 있어 거리만으로 불합격이다.
    v, reasons, warns, fl = run("char_shuffle")
    check("f60: FAIL", v == "FAIL", v)
    check("f60: 사유는 L_Wrist 하나 (본이 메쉬에서 너무 멀다 0.064 > 0.05)",
          len(reasons) == 1 and reasons[0].startswith("L_Wrist:") and "너무 멀다" in reasons[0]
          and fl["fatal"] == ["L_Wrist"], reasons)
    check("f60: ① 말단 거리 — L_Wrist 0.0642 · L_Hand 0.0852 만 초과",
          sorted(fl["far"]) == ["L_Hand", "L_Wrist"], fl["far"])
    check("f60: ② 교차 — R_Knee 28.3% · L_Ankle 13.1%",
          fl["crossed"] == {"R_Knee": 28.3, "L_Ankle": 13.1}, fl["crossed"])
    check("f60: ③ 제약 뒤 지배 0 은 L_Hand 뿐 (L_Wrist 는 3,445정점을 되찾았다)",
          fl["empty"] == ["L_Hand"] and fx["char_shuffle"]["rig_check"]["dominant"]["L_Wrist"] == 3445
          and fx["char_shuffle"]["before"]["dominant"]["L_Wrist"] == 0, fl["empty"])
    check("f60: L_Hand 는 불합격 사유가 아니라 경고 (손 본)",
          any(w.startswith("L_Hand:") for w in warns) and "L_Hand" not in reasons[0])
    check("f60: ④ 는 여전히 독립 경고", any("분포 위험" in w for w in warns))
    # 제약이 게이트를 무르게 만들지 않는가 — 거리 불합격 조건이 없으면 f60 은 PASS 가 된다
    import gate_g2r as _g
    keep = _g.DISTAL_DIST_FAIL
    _g.DISTAL_DIST_FAIL = 9.9
    v2, _, _, _ = run("char_shuffle")
    _g.DISTAL_DIST_FAIL = keep
    check("f60: 거리 불합격 조건이 없으면 PASS 로 빠진다 (이 조건이 필요한 이유)", v2 == "PASS", v2)
    # ①∧③ 불합격 조건 자체는 그대로다 (아래 경계 시험의 '발목: 거리 + 지배 0')

    # 합격 3건 — ①②③ 에서 아무것도 걸리지 않아야 한다.
    for name in ("char_shuffle_f6", "zombie1_1024", "zombie1_t2"):
        v, reasons, warns, fl = run(name)
        clean = v == "PASS" and not fl["far"] and not fl["empty"] and not fl["crossed"]
        check(f"{name}: PASS, ①②③⑤ 모두 무경고 (⑤ 엣지 {fl['limb_edges']})",
              clean and fl["limb_edges"] <= _g.LIMB_EDGES_MAX
              and not any("떨어져 있어야 할 부위" in w for w in warns), (v, fl) if not clean else "")
        # 합격 샘플은 "분포 위험" 을 받지 않아야 한다. 사지 본 비율 축이 있던 때는
        # zombie1 1024(21.0%)·512(26.5%)가 오탐 경고였다 (축은 10/12 에 뺐다).
        cls, _ = classify_fallback(fx[name]["fallback_detail"])
        check(f"{name}: ④ 분포 무해 (사지 본 {fx[name]['fallback_detail']['limb_pct']}%)",
              cls == "benign" and not any("분포 위험" in w for w in warns), cls)

    # zombie1 1세대 — 손 메쉬는 온전하고 R_Hand 본만 메쉬 밖이다 (10/9 렌더 확인).
    # WHAM 은 손 관절을 거의 움직이지 않으므로 불합격이 아니라 경고여야 한다.
    v, reasons, warns, fl = run("zombie1")
    check("zombie1 1세대: PASS (R_Hand 의 ①∧③ 은 경고)", v == "PASS" and not reasons
          and fl["fatal"] == [] and any(w.startswith("R_Hand:") for w in warns), (v, reasons))
    check("zombie1 1세대: ② R_Knee 26.1% 경고", fl["crossed"] == {"R_Knee": 26.1}, fl["crossed"])

    # 경계와 가드
    from gate_g2r import check_rig, DISTAL_DIST_MAX, CROSS_MAX_PCT
    base = {"vertices": 100000,
            "bone_dist": {"L_Wrist": 0.01, "L_Ankle": 0.01, "L_Hip": 0.09, "Spine2": 0.09},
            "dominant": {"L_Wrist": 500, "L_Ankle": 500, "L_Hip": 5000, "Spine2": 5000,
                         "R_Ankle": 500},
            "cross": {"L_Ankle": 0, "R_Ankle": 0, "L_Hip": 0}}
    r, w, fl = check_rig(base)
    check("몸 안쪽 본(Hip·Spine 0.09)은 ① 대상이 아니다", not r and not w, (r, w))
    b = json.loads(json.dumps(base)); b["bone_dist"]["L_Ankle"] = 0.031; b["dominant"]["L_Ankle"] = 0
    r, w, fl = check_rig(b)
    check("발목: 거리 0.031 + 지배 0 → 불합격", len(r) == 1 and r[0].startswith("L_Ankle:"), r)
    b = json.loads(json.dumps(base)); b["bone_dist"]["L_Ankle"] = 0.031
    r, w, fl = check_rig(b)
    check("거리만 초과(0.031) → 경고", not r and len(w) == 1 and "멀다" in w[0], w)
    b["bone_dist"]["L_Ankle"] = 0.051
    r, w, fl = check_rig(b)
    check("거리가 0.05 를 넘으면 그것만으로 불합격 (지배 정점이 있어도)",
          len(r) == 1 and "너무 멀다" in r[0] and not w, (r, w))
    b = json.loads(json.dumps(base)); b["bone_dist"]["L_Hand"] = 0.09; b["dominant"]["L_Hand"] = 500
    r, w, fl = check_rig(b)
    check("손(Hand)은 0.09 떨어져도 불합격이 아니다 (경고)", not r and len(w) == 1, (r, w))
    b = json.loads(json.dumps(base)); b["dominant"]["L_Ankle"] = 0
    r, w, fl = check_rig(b)
    check("지배 0 만 → 경고", not r and len(w) == 1 and "지배 정점이 없는" in w[0], w)
    b = json.loads(json.dumps(base)); b["cross"]["R_Ankle"] = 60        # 12%
    r, w, fl = check_rig(b)
    check("교차 12% → 경고 (단독으로는 불합격이 아니다)", not r and fl["crossed"] == {"R_Ankle": 12.0}, w)
    b = json.loads(json.dumps(base)); b["dominant"]["R_Ankle"] = 99; b["cross"]["R_Ankle"] = 90
    r, w, fl = check_rig(b)
    check("지배 99정점인 본은 교차를 보지 않는다 (잡음 가드)", not fl["crossed"], fl["crossed"])
    check("rig_check 없음 → 판정하지 않는다 (구버전 JSON 호환)", check_rig(None) == ([], [], None))
    check(f"임계 상수 {DISTAL_DIST_MAX} / {CROSS_MAX_PCT}", DISTAL_DIST_MAX == 0.03 and CROSS_MAX_PCT == 10.0)
    from gate_g2r import FAIL_BONES, FB_SRC_P90_MAX, LIMB_EDGES_MAX
    check("불합격 대상 본: 손목·발목·발 (손 제외)", FAIL_BONES == ("Wrist", "Ankle", "Foot"), FAIL_BONES)
    check("④ 임계: 소스거리 0.04 (사지 본 비율 축 없음)", FB_SRC_P90_MAX == 0.04)
    p90 = {n: fx[n]["fallback_detail"]["src_dist"]["p90"] for n in fx if fx[n]["fallback_detail"]["verts"] >= 1000}
    good = [p90[n] for n in ("char_shuffle_f6", "zombie1_1024", "zombie1_t2")]
    check("④ 소스거리 p90: 합격 최대 0.0336 < 0.04 < f60 0.0606",
          max(good) < FB_SRC_P90_MAX < p90["char_shuffle"], p90)

    print("\n── D. ⑤ 떨어져 있어야 할 부위를 잇는 엣지 — 7샘플")
    # 전(제약 없음) → 후(제약 적용). 고정 자료의 before 는 10/12 오전의 실측이다.
    want = {  # 이름: (전, 후, 재배정 정점)
        # 2026-10-12 저녁: 팔 정의에 위팔(Shoulder)을 넣은 뒤 다시 잰 값이다.
        # 옛 정의에서는 f60 (333, 65, 3500) · f138 (561, 0, 4379) · f18 (1628, 737, 1761) · 합격 4건 (0, 0, 0).
        "char_shuffle": (829, 533, 3667), "walker_walk_02": (1824, 1181, 4536),
        "walker_walk_02_f18": (2690, 1768, 1801),
        "char_shuffle_f6": (0, 0, 0), "zombie1_1024": (45, 45, 0), "zombie1_t2": (16, 16, 0), "zombie1": (3, 3, 0)}
    for name, (w_before, w_after, w_moved) in want.items():
        o = fx[name]
        before = o["before"]["limb_edges"]["arm_leg"] + o["before"]["limb_edges"]["arm_lowtorso"]
        after = o["rig_check"]["limb_edges"]["arm_leg"] + o["rig_check"]["limb_edges"]["arm_lowtorso"]
        check(f"{name}: ⑤ {before} → {after}, 재배정 {o['part_constraint']['verts']}정점",
              (before, after, o["part_constraint"]["verts"]) == (w_before, w_after, w_moved))
    # 파일럿 f138 — 손–허벅지 오배정은 제약이 고쳤다. 그러나 위팔–옆구리가 메쉬로 붙어 있어
    # (roar_02 웨빙의 원인) 위팔을 팔에 넣은 ⑤ 는 경고한다. 옛 정의에서는 무경고였다.
    v, reasons, warns, fl = run("walker_walk_02")
    w5 = [w for w in warns if "떨어져 있어야 할 부위" in w]
    check("파일럿 f138: PASS + ⑤ 경고 (1,824 → 1,181, 위팔–Spine1 이 남는다)",
          v == "PASS" and len(w5) == 1 and fl["limb_edges"] == 1181 and "Shoulder" in w5[0], (v, fl["limb_edges"], warns))
    d0, d1 = fx["walker_walk_02"]["before"]["dominant"], fx["walker_walk_02"]["rig_check"]["dominant"]
    check("파일럿 f138: 왼손목·왼손 지배 정점 8,025 · 741 → 10,325 · 2,625",
          (d0["L_Wrist"], d0["L_Hand"], d1["L_Wrist"], d1["L_Hand"]) == (8025, 741, 10325, 2625))
    # 파일럿 f18 — 메쉬가 실제로 붙어 있다. 제약으로 못 고친 몫이 ⑤ 에 남아 경고가 뜬다.
    v, reasons, warns, fl = run("walker_walk_02_f18")
    w5 = [w for w in warns if "떨어져 있어야 할 부위" in w]
    check("파일럿 f18: PASS + ⑤ 경고 (2,690 → 1,768, 붙은 메쉬는 남는다)",
          v == "PASS" and len(w5) == 1 and fl["limb_edges"] == 1768, (v, fl["limb_edges"]))
    check("파일럿 f18: 경고에 상위 쌍이 들어간다", "R_Elbow–Spine1" in w5[0] and "L_Hip–L_Wrist" in w5[0], w5[0][:150])
    for name in ("walker_walk_02", "walker_walk_02_f18"):
        cls, _ = classify_fallback(fx[name]["fallback_detail"])
        check(f"{name}: ④ 는 무해 (사지 본 100% 였지만 가까이서 빌림)", cls == "benign")
    v, reasons, warns, fl = run("char_shuffle")
    check("f60: ⑤ 는 제약 뒤에도 경고 (829 → 533 > 100)",
          fl["limb_edges"] == 533 and any("떨어져 있어야 할 부위" in w for w in warns), fl["limb_edges"])
    goods = ("char_shuffle_f6", "zombie1_1024", "zombie1_t2", "zombie1")
    check(f"합격 4건은 한 정점도 안 바뀌고(전 = 후) 최대 45 < 임계 {LIMB_EDGES_MAX}",
          all(want[n][0] == want[n][1] and want[n][2] == 0 for n in goods)
          and max(want[n][1] for n in goods) == 45 and LIMB_EDGES_MAX == 100)
    for name in goods:
        v, reasons, warns, fl = run(name)
        check(f"{name}: ⑤ 경고 없음 ({fl['limb_edges']})", not any("떨어져 있어야 할 부위" in w for w in warns), warns)
    b = json.loads(json.dumps(base)); b["limb_edges"] = {"arm_leg": 100, "arm_lowtorso": 0, "leg_leg": 500, "top": {}}
    r, w, fl = check_rig(b)
    check("경계: 100 은 통과, 좌다리–우다리는 세지 않는다", not r and not w and fl["limb_edges"] == 100, w)
    b["limb_edges"]["arm_lowtorso"] = 1
    r, w, fl = check_rig(b)
    check("경계: 101 은 경고 (불합격은 아니다)", not r and len(w) == 1, w)
    r, w, fl = check_rig(base)
    check("limb_edges 없음 → ⑤ 를 보지 않는다 (구버전 JSON 호환)", fl["limb_edges"] is None and not w)

    # 기존 불합격 조건은 건드리지 않았다.
    v, reasons, _ = judge(metrics(0.70, 0.9, 0.03, 3.0, None))
    check("스케일 범위 밖 → FAIL (종전 동작)", v == "FAIL" and len(reasons) == 1)
    check(f"경고선 상수는 그대로 {FALLBACK_WARN_PCT}", FALLBACK_WARN_PCT == 8.0)

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
