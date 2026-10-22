"""G4 판정 로직 — 5-5 베이킹 뒤 클립마다 "늘어남" 과 "발 쓸기" 를 판정한다 (gate_g4.py 가 쓴다).

Blender 없이 돈다 (bpy 를 쓰지 않는다). 그래서 tests/ 에서 그대로 시험할 수 있다.

**늘어남** — 엣지가 기준 자세 길이의 4배를 넘으면서 길이 0.10(키 약 1 단위)을 넘으면 "늘어난 엣지" 다.
프레임마다 세서 그 최대값과, 늘어난 엣지 중 가장 긴 것(최장)으로 판정한다.
  PASS  0.10 초과 ≤ 10 그리고 최장 ≤ 0.11
  CHECK 그 밖 — 사람이 본다
근거(2026-10-22, 납품 86편 실측): 웨이트 수리 뒤 77편이 0.10 초과 0. 문제 삼지 않은 stalker `run_03`
(6, 0.105) · listener `run_stop`(1, 0.100) 은 통과하고, 격리 이력의 최소값(listener alert 74)과 주석을 달아
수용한 클립(24~416)은 모두 CHECK 로 간다. 0.05 초과 수는 참고로만 남긴다(수리 뒤에도 0~540 로 넓다).

**발 쓸기** — 땅에 닿은 발이 골반 기준으로 뒤로 쓸려 가는 속도(머리–발목 높이 H/초, 음수가 뒤). 제자리 달리기
클립을 게임이 앞으로 옮길 때 이 속도가 이동 속도를 받쳐 주지 못하면 발이 미끄러져 보인다(2026-10-19 listener
`run` 04b: −0.003 / −0.051 → 게임팀 "미끄러짐"). **양발 중 나쁜 쪽(0 에 가까운 쪽)으로** 판정한다.
  PASS  ≤ −0.45      (stalker run_fwd −0.80, listener run_slow −0.469 통과)
  CHECK −0.45 ~ −0.20
  FAIL  > −0.20      (04b 불합격)
클립 역할(clip_roles.json)이 move 일 때만 판정한다. inplace(제자리 연출용)는 면제하고 수치만 남긴다. 역할이
없는데 이름에 run 이 들어가면 CHECK("역할 미지정") — 새 달리기 클립이 조용히 면제되지 않게 하기 위해서다.

**수용 기록** — 사람이 보고 받아들인 CHECK/FAIL 은 clip_roles.json 의 accepted 에 사유 · 날짜 · 그때의 수치와
함께 적는다. 다시 돌렸을 때 수치가 기록보다 나빠지지 않았으면 ACCEPTED 로, 나빠졌으면 원래 판정으로 돌아간다.
"""

EDGE_MAX10 = 10          # 0.10 초과 엣지 수 (프레임별 최대) 상한
LONGEST_MAX = 0.11       # 최장 늘어난 엣지 길이 상한 (정규화 공간, 키 약 1.0)
SWEEP_PASS = -0.45       # 이하면 PASS
SWEEP_FAIL = -0.20       # 초과면 FAIL
WORSEN_TOL = {"max10": 0, "longest": 0.005, "sweep_worst": 0.02}   # 수용 기록 대비 "나빠짐" 여유

ORDER = {"PASS": 0, "EXEMPT": 0, "N/A": 0, "ACCEPTED": 1, "CHECK": 2, "FAIL": 3}


def judge_edges(max10, longest):
    reasons = []
    if max10 > EDGE_MAX10:
        reasons.append(f"0.10 초과 {max10} > {EDGE_MAX10}")
    if longest > LONGEST_MAX:
        reasons.append(f"최장 {longest:.3f} > {LONGEST_MAX}")
    return ("CHECK" if reasons else "PASS"), reasons


def sweep_worst(left, right):
    """양발 중 나쁜 쪽 = 0 에 가까운(큰) 값. 한쪽이 없으면 있는 쪽."""
    vals = [v for v in (left, right) if v is not None]
    return max(vals) if vals else None


def judge_sweep(left, right, role, name):
    worst = sweep_worst(left, right)
    if role == "inplace":
        return "EXEMPT", ["제자리 연출용 — 면제"], worst
    if role != "move":
        if "run" in name:
            return "CHECK", ["역할 미지정 — 이름에 run 이 있다 (clip_roles.json 에 move/inplace 를 적을 것)"], worst
        return "N/A", [], worst
    if worst is None:
        return "CHECK", ["접지 구간을 찾지 못함"], worst
    if worst <= SWEEP_PASS:
        return "PASS", [], worst
    if worst <= SWEEP_FAIL:
        return "CHECK", [f"발 쓸기 {worst:.3f} (PASS ≤ {SWEEP_PASS})"], worst
    return "FAIL", [f"발 쓸기 {worst:.3f} > {SWEEP_FAIL} — 게임 이동 시 미끄러짐"], worst


def worsened(key, now, recorded):
    if recorded is None or now is None:
        return False
    tol = WORSEN_TOL[key]
    # max10 · longest 는 클수록 나쁘고, sweep_worst 는 클수록(0 에 가까울수록) 나쁘다
    return now > recorded + tol


def apply_acceptance(part, verdict, reasons, metrics, accepted):
    """part: "edges" | "sweep". accepted: clip_roles.json 의 그 클립 accepted 목록(없으면 None)."""
    if verdict not in ("CHECK", "FAIL") or not accepted:
        return verdict, reasons, None
    for a in accepted:
        if a.get("gate") != part:
            continue
        rec = a.get("metrics", {})
        worse = [k for k in rec if worsened(k, metrics.get(k), rec[k])]
        if worse:
            return verdict, reasons + [f"수용 기록({a.get('date')})보다 나빠짐: " + ", ".join(f"{k} {metrics.get(k)} > {rec[k]}" for k in worse)], a
        return "ACCEPTED", reasons + [f"수용: {a.get('reason')} ({a.get('date')})"], a
    return verdict, reasons, None


def resolve(roles, name):
    """clip_roles.json 에서 클립 항목을 찾는다 — 납품 이름(키) 또는 source(굽기 폴더 이름)로."""
    clips = (roles or {}).get("clips", {})
    if name in clips:
        return name, clips[name]
    for k, v in clips.items():
        if v.get("source") == name:
            return k, v
    return name, {}


def judge(name, edges, sweep, roles=None):
    """edges: {"max10", "max05", "longest"}; sweep: {"L", "R"} (없으면 None). 결과 dict."""
    key, entry = resolve(roles, name)
    role = entry.get("role")
    accepted = entry.get("accepted")
    ev, er = judge_edges(edges["max10"], edges["longest"])
    ev, er, ea = apply_acceptance("edges", ev, er, {"max10": edges["max10"], "longest": edges["longest"]}, accepted)
    sv, sr, worst = judge_sweep((sweep or {}).get("L"), (sweep or {}).get("R"), role, key)
    sv, sr, sa = apply_acceptance("sweep", sv, sr, {"sweep_worst": worst}, accepted)
    overall = max((ev, sv), key=lambda v: ORDER[v])
    if overall in ("EXEMPT", "N/A"):
        overall = "PASS"
    return {"clip": key, "role": role, "verdict": overall,
            "edges": {"verdict": ev, "reasons": er, **edges},
            "sweep": {"verdict": sv, "reasons": sr, "worst": worst, **(sweep or {})}}
