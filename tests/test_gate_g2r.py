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

    # f60 — 불합격이어야 한다. 사유는 L_Wrist (①∧③), ④ 를 근거로 인용.
    v, reasons, warns, fl = run("char_shuffle")
    check("f60: FAIL", v == "FAIL", v)
    check("f60: 사유는 L_Wrist 하나 (본이 메쉬 밖 + 지배 정점 0)",
          len(reasons) == 1 and reasons[0].startswith("L_Wrist:") and fl["fatal"] == ["L_Wrist"], reasons)
    check("f60: 사유에 ④ 인용 — 폴백 7,050정점이 L_Elbow 로", "7,050정점이 L_Elbow" in reasons[0])
    check("f60: ① 말단 거리 — L_Wrist 0.0642 · L_Hand 0.0852 만 초과",
          sorted(fl["far"]) == ["L_Hand", "L_Wrist"], fl["far"])
    check("f60: ② 교차 — R_Knee 28.3% · L_Ankle 13.1%",
          fl["crossed"] == {"R_Knee": 28.3, "L_Ankle": 13.1}, fl["crossed"])
    check("f60: ③ 지배 0 — L_Wrist · L_Hand", sorted(fl["empty"]) == ["L_Hand", "L_Wrist"], fl["empty"])
    check("f60: L_Hand 는 불합격 사유가 아니라 경고 (손 본)",
          any(w.startswith("L_Hand:") for w in warns) and "L_Hand" not in reasons[0])
    check("f60: ④ 는 여전히 독립 경고", any("분포 위험" in w for w in warns))

    # 합격 3건 — ①②③ 에서 아무것도 걸리지 않아야 한다.
    for name in ("char_shuffle_f6", "zombie1_1024", "zombie1_t2"):
        v, reasons, warns, fl = run(name)
        clean = v == "PASS" and not fl["far"] and not fl["empty"] and not fl["crossed"]
        check(f"{name}: PASS, ①②③⑤ 모두 무경고 (⑤ 엣지 {fl['limb_edges']})",
              clean and fl["limb_edges"] == 0, (v, fl) if not clean else "")
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
    check("거리만 초과 → 경고", not r and len(w) == 1 and "멀다" in w[0], w)
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
    # 파일럿 2건: ①②③ 은 무경고로 통과했고 육안 불합격이었다. ⑤ 가 잡아야 한다.
    for name, want in (("walker_walk_02", 561), ("walker_walk_02_f18", 1628)):
        v, reasons, warns, fl = run(name)
        w5 = [w for w in warns if "떨어져 있어야 할 부위" in w]
        check(f"{name}: PASS + ⑤ 경고 (엣지 {fl['limb_edges']}), ①②③ 은 무경고",
              v == "PASS" and len(w5) == 1 and fl["limb_edges"] == want
              and not fl["far"] and not fl["empty"] and not fl["crossed"], (v, fl, warns))
        check(f"{name}: 경고에 상위 쌍(L_Hip–L_Wrist)이 들어간다", "L_Hip–L_Wrist" in w5[0], w5[0][:120])
        cls, _ = classify_fallback(fx[name]["fallback_detail"])
        check(f"{name}: ④ 는 무해 (사지 본 100% 였지만 가까이서 빌림)", cls == "benign"
              and not any("분포 위험" in w for w in warns), cls)
    v, reasons, warns, fl = run("char_shuffle")
    check("f60: ⑤ 도 경고 (팔–다리 249 + 팔–하부몸통 84 = 333)",
          fl["limb_edges"] == 333 and any("떨어져 있어야 할 부위" in w for w in warns), fl["limb_edges"])
    vals = {n: fx[n]["rig_check"]["limb_edges"]["arm_leg"] + fx[n]["rig_check"]["limb_edges"]["arm_lowtorso"] for n in fx}
    check(f"합격 4건 전부 0, 불합격 3건 최소 333 — 임계 {LIMB_EDGES_MAX}",
          all(vals[n] == 0 for n in ("char_shuffle_f6", "zombie1_1024", "zombie1_t2", "zombie1"))
          and min(vals[n] for n in ("char_shuffle", "walker_walk_02", "walker_walk_02_f18")) == 333
          and LIMB_EDGES_MAX == 20, vals)
    b = json.loads(json.dumps(base)); b["limb_edges"] = {"arm_leg": 20, "arm_lowtorso": 0, "leg_leg": 500, "top": {}}
    r, w, fl = check_rig(b)
    check("경계: 20 은 통과, 좌다리–우다리는 세지 않는다", not r and not w and fl["limb_edges"] == 20, w)
    b["limb_edges"]["arm_lowtorso"] = 1
    r, w, fl = check_rig(b)
    check("경계: 21 은 경고 (불합격은 아니다)", not r and len(w) == 1, w)
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
