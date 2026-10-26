"""G4 판정 로직(g4_rules) 단위 시험 — Blender 없이 돈다.

고정하는 것 (2026-10-22 실측 · 사용자 승인값):
  - 늘어남: 0.10 초과 ≤ 10 그리고 최장 ≤ 0.11 이면 PASS — stalker run_03(6, 0.105) 통과, oiler run_fwd(24) CHECK
  - 발 쓸기: 나쁜 발 기준 PASS ≤ −0.45 / FAIL > −0.20 — stalker −0.8 · run_slow −0.469 통과, 04b 불합격
  - inplace 면제, 역할 없는 run 은 CHECK
  - 수용 기록: 나빠지지 않으면 ACCEPTED, 나빠지면 원래 판정
  - 바닥(2026-10-26): 처음 · 끝 |값| ≤ 0.03, 최저 ≥ −0.05 이면 PASS — get_up +0.36 뜸 · fall_front −0.13 묻힘은 CHECK
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from g4_rules import judge, judge_edges, judge_ground, judge_sweep, sweep_worst

ok = True


def check(msg, cond):
    global ok
    print(("   ✅ " if cond else "   ❌ ") + msg)
    ok = ok and cond


E0 = {"max10": 0, "max05": 0, "longest": 0.05}


def main():
    print("── 늘어남")
    check("0 · 0.05 → PASS", judge_edges(0, 0.05)[0] == "PASS")
    check("stalker run_03 (6, 0.1054) → PASS", judge_edges(6, 0.1054)[0] == "PASS")
    check("listener run_stop (1, 0.100) → PASS", judge_edges(1, 0.100)[0] == "PASS")
    check("oiler run_fwd (24, 0.104) → CHECK", judge_edges(24, 0.104)[0] == "CHECK")
    check("최장만 넘어도 CHECK (0, 0.12)", judge_edges(0, 0.12)[0] == "CHECK")
    check("경계값 (10, 0.11) → PASS", judge_edges(10, 0.11)[0] == "PASS")

    print("\n── 발 쓸기 (나쁜 발 기준)")
    check("나쁜 발 = 0 에 가까운 쪽", sweep_worst(-0.549, -0.469) == -0.469)
    check("stalker run_fwd (−0.835, −0.800) move → PASS", judge_sweep(-0.835, -0.800, "move", "run_fwd")[0] == "PASS")
    check("listener run_slow (−0.549, −0.469) move → PASS", judge_sweep(-0.549, -0.469, "move", "run_slow")[0] == "PASS")
    check("walker run (−0.202, −0.339) move → CHECK", judge_sweep(-0.202, -0.339, "move", "run")[0] == "CHECK")
    check("listener 04b (−0.003, −0.051) move → FAIL", judge_sweep(-0.003, -0.051, "move", "run")[0] == "FAIL")
    check("oiler run_fwd (−0.180, −0.130) move → FAIL", judge_sweep(-0.180, -0.130, "move", "run_fwd")[0] == "FAIL")
    check("inplace 는 쓸기 0 이어도 EXEMPT", judge_sweep(0.01, 0.0, "inplace", "run_b")[0] == "EXEMPT")
    check("역할 없는 run 이름 → CHECK", judge_sweep(-0.9, -0.9, None, "run_e")[0] == "CHECK")
    check("역할 없는 run 아닌 이름 → N/A", judge_sweep(None, None, None, "idle")[0] == "N/A")

    print("\n── 종합 · 역할표 · 수용 기록")
    roles = {"clips": {
        "run": {"role": "move", "source": "walker_run_04",
                "accepted": [{"gate": "sweep", "reason": "발 쓸기 부족(실결함)", "date": "2026-10-22", "metrics": {"sweep_worst": -0.202}}]},
        "walk_fwd": {"accepted": [{"gate": "edges", "reason": "가랑이 막 수용", "date": "2026-10-15", "metrics": {"max10": 416, "longest": 0.1698}}]},
        "run_b": {"role": "inplace"}}}
    r = judge("walker_run_04", E0, {"L": -0.202, "R": -0.339}, roles)
    check("source 이름으로 찾아 납품 이름 run 으로 판정", r["clip"] == "run" and r["role"] == "move")
    check("수용 기록과 같은 수치 → ACCEPTED", r["verdict"] == "ACCEPTED" and r["sweep"]["verdict"] == "ACCEPTED")
    r = judge("run", E0, {"L": -0.10, "R": -0.339}, roles)
    check("수용 때보다 나빠지면(−0.10) 원래 판정 FAIL 로", r["sweep"]["verdict"] == "FAIL" and r["verdict"] == "FAIL")
    r = judge("walk_fwd", {"max10": 416, "max05": 537, "longest": 0.1698}, None, roles)
    check("늘어남 수용 → ACCEPTED", r["verdict"] == "ACCEPTED")
    r = judge("walk_fwd", {"max10": 500, "max05": 600, "longest": 0.1698}, None, roles)
    check("늘어남이 기록보다 늘면 CHECK", r["verdict"] == "CHECK")
    r = judge("run_b", E0, {"L": 0.0, "R": 0.0}, roles)
    check("inplace + 늘어남 0 → 종합 PASS", r["verdict"] == "PASS" and r["sweep"]["verdict"] == "EXEMPT")
    r = judge("idle", E0, {"L": None, "R": None}, roles)
    check("역할표에 없는 일반 클립 → PASS", r["verdict"] == "PASS")
    r = judge("run", {"max10": 30, "max05": 99, "longest": 0.12}, {"L": -0.202, "R": -0.339}, roles)
    check("쓸기는 수용이어도 늘어남 CHECK 면 종합 CHECK", r["verdict"] == "CHECK")

    print("\n── 바닥")
    G0 = {"first": 0.004, "last": -0.003, "sink": -0.02, "f_sink": 10}
    check("서서 시작 · 끝 (±0.004) → PASS", judge_ground(G0)[0] == "PASS")
    check("측정 없음 → N/A", judge_ground(None)[0] == "N/A")
    v, rs = judge_ground({"first": 0.358, "last": 0.288, "sink": 0.0, "f_sink": 0})
    check("get_up 뜸 (+0.358 / +0.288) → CHECK, 사유 2개 '떠 있음'", v == "CHECK" and len(rs) == 2 and "떠 있음" in rs[0])
    v, rs = judge_ground({"first": 0.0, "last": -0.13, "sink": -0.13, "f_sink": 200})
    check("fall_front 묻힘 (−0.13) → CHECK, '묻힘' · 'f200 바닥 아래'", v == "CHECK" and "묻힘" in rs[0] and "f200" in rs[1])
    check("경계값 (0.03 / −0.03 / −0.05) → PASS", judge_ground({"first": 0.03, "last": -0.03, "sink": -0.05, "f_sink": 1})[0] == "PASS")
    r = judge("idle", E0, None, roles)
    check("바닥 없이 부르면(이전 호출) 종합은 그대로 PASS · 바닥 N/A", r["verdict"] == "PASS" and r["ground"]["verdict"] == "N/A")
    gr = {"clips": {"get_up": {"accepted": [{"gate": "ground", "reason": "시험", "date": "2026-10-26",
                                             "metrics": {"float_first": 0.04, "float_last": 0.0, "sink_depth": 0.0}}]}}}
    r = judge("get_up", E0, None, gr, {"first": 0.04, "last": 0.0, "sink": 0.0, "f_sink": 0})
    check("바닥 수용 기록과 같은 수치 → ACCEPTED", r["verdict"] == "ACCEPTED")
    r = judge("get_up", E0, None, gr, {"first": 0.08, "last": 0.0, "sink": 0.0, "f_sink": 0})
    check("바닥이 기록보다 나빠지면 CHECK", r["verdict"] == "CHECK")
    r = judge("idle", E0, None, roles, {"first": 0.36, "last": 0.0, "sink": 0.0, "f_sink": 0})
    check("늘어남 PASS 여도 바닥 CHECK 면 종합 CHECK", r["verdict"] == "CHECK")

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
