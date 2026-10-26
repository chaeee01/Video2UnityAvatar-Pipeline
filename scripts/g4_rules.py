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

**바닥** — 메쉬 최저점 − 바닥(rest 메쉬 최저점), 키 약 1.0 단위. 처음 · 끝은 0.25초(6프레임) 안의 최저점이다
(달리기의 공중 프레임에 흔들리지 않게 — ground_align.py 와 같은 창).
  PASS  처음 · 끝 모두 |값| ≤ 0.03 그리고 −0.05 보다 깊이 묻힌 프레임이 없거나, 있어도 연속 0.25초(6프레임)
        이하 · −0.08 까지인 **순간 침하**(값을 사유에 "허용" 으로 남긴다)
  CHECK 그 밖 — 떠 있음(+) / 묻힘(−) / 지속 침하(6프레임 넘게 −0.05 아래) / −0.08 보다 깊음
근거(2026-10-26 실측): 서서 시작하는 클립의 첫 프레임은 ±0.01 안, 누워서 시작하는 get_up 은 +0.36~0.45,
fall_back 의 누운 끝 +0.08~0.12, fall_front 의 엎드린 끝 −0.13. 바닥 정렬(apply_wham_pose --ground-align) 뒤
다시 잰다. 늘어남 · 발 쓸기와 달리 역할과 무관하게 모든 클립에 적용한다.
순간 침하 완화(2026-10-26 사용자 결정): 납품 86편에서 −0.05 를 넘긴 18편이 달리기 · 덤벼들기의 발 · 무릎이 한 순간
묻히는 −0.04~−0.08 이었다. 실결함(stalker crawl_loop +0.16 뜸, walker idle_lurch −0.14)만 CHECK 에 남기려는 조정이다.

**수용 기록** — 사람이 보고 받아들인 CHECK/FAIL 은 clip_roles.json 의 accepted 에 사유 · 날짜 · 그때의 수치와
함께 적는다. 다시 돌렸을 때 수치가 기록보다 나빠지지 않았으면 ACCEPTED 로, 나빠졌으면 원래 판정으로 돌아간다.
"""

EDGE_MAX10 = 10          # 0.10 초과 엣지 수 (프레임별 최대) 상한
LONGEST_MAX = 0.11       # 최장 늘어난 엣지 길이 상한 (정규화 공간, 키 약 1.0)
SWEEP_PASS = -0.45       # 이하면 PASS
SWEEP_FAIL = -0.20       # 초과면 FAIL
GROUND_END = 0.03        # 처음 · 끝 최저점이 바닥에서 이만큼 넘게 떨어지면 CHECK
GROUND_SINK = 0.05       # 이만큼 넘게 바닥 아래인 프레임이 연속 MOMENT 를 넘으면 CHECK (지속 침하)
GROUND_SINK_MOMENT = 0.08  # 순간 침하 허용 한도 — 이보다 깊으면 길이와 무관하게 CHECK
MOMENT = 6               # 순간 = 연속 0.25초 (24fps) 이하
WORSEN_TOL = {"max10": 0, "longest": 0.005, "sweep_worst": 0.02,
              "float_first": 0.01, "float_last": 0.01, "sink_depth": 0.01}   # 수용 기록 대비 "나빠짐" 여유

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


def judge_ground(ground):
    """ground: {"first", "last", "sink", "f_sink", "deep_run"} (없으면 None → N/A).
    deep_run: −GROUND_SINK 아래 연속 프레임의 최장 길이 (없으면 지속으로 본다 — G4 v2 결과)."""
    if ground is None:
        return "N/A", []
    reasons = []
    for k, label in (("first", "시작"), ("last", "끝")):
        v = ground[k]
        if abs(v) > GROUND_END:
            reasons.append(f"{label} {'떠 있음' if v > 0 else '묻힘'} {v:+.3f} (|값| ≤ {GROUND_END})")
    note = []
    sink, run = ground["sink"], ground.get("deep_run")
    if sink < -GROUND_SINK_MOMENT:
        reasons.append(f"f{ground.get('f_sink')} 바닥 아래 {sink:+.3f} (≥ −{GROUND_SINK_MOMENT})")
    elif sink < -GROUND_SINK:
        if run is None or run > MOMENT:
            reasons.append(f"지속 침하 — f{ground.get('f_sink')} 바닥 아래 {sink:+.3f}, −{GROUND_SINK} 아래 연속 {run}프레임 (> {MOMENT})")
        else:
            note.append(f"순간 침하 허용 — f{ground.get('f_sink')} {sink:+.3f}, 연속 {run}프레임 (≤ {MOMENT}, ≥ −{GROUND_SINK_MOMENT})")
    return ("CHECK" if reasons else "PASS"), reasons + note


def ground_metrics(ground):
    """수용 기록용 — 모두 클수록 나쁜 값으로."""
    return {"float_first": round(abs(ground["first"]), 4), "float_last": round(abs(ground["last"]), 4),
            "sink_depth": round(max(0.0, -ground["sink"]), 4)}


def worsened(key, now, recorded):
    if recorded is None or now is None:
        return False
    tol = WORSEN_TOL[key]
    # max10 · longest 는 클수록 나쁘고, sweep_worst 는 클수록(0 에 가까울수록) 나쁘다
    return now > recorded + tol


def apply_acceptance(part, verdict, reasons, metrics, accepted):
    """part: "edges" | "sweep" | "ground". accepted: clip_roles.json 의 그 클립 accepted 목록(없으면 None)."""
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


def judge(name, edges, sweep, roles=None, ground=None):
    """edges: {"max10", "max05", "longest"}; sweep: {"L", "R"} (없으면 None);
    ground: {"first", "last", "sink", "f_sink"} (없으면 None — 바닥 판정 N/A). 결과 dict."""
    key, entry = resolve(roles, name)
    role = entry.get("role")
    accepted = entry.get("accepted")
    ev, er = judge_edges(edges["max10"], edges["longest"])
    ev, er, ea = apply_acceptance("edges", ev, er, {"max10": edges["max10"], "longest": edges["longest"]}, accepted)
    sv, sr, worst = judge_sweep((sweep or {}).get("L"), (sweep or {}).get("R"), role, key)
    sv, sr, sa = apply_acceptance("sweep", sv, sr, {"sweep_worst": worst}, accepted)
    gv, gr = judge_ground(ground)
    if ground is not None:
        gv, gr, ga = apply_acceptance("ground", gv, gr, ground_metrics(ground), accepted)
    overall = max((ev, sv, gv), key=lambda v: ORDER[v])
    if overall in ("EXEMPT", "N/A"):
        overall = "PASS"
    return {"clip": key, "role": role, "verdict": overall,
            "edges": {"verdict": ev, "reasons": er, **edges},
            "sweep": {"verdict": sv, "reasons": sr, "worst": worst, **(sweep or {})},
            "ground": {"verdict": gv, "reasons": gr, **(ground or {})}}
