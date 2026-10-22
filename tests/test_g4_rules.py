"""G4 판정 로직(g4_rules) 단위 시험 — Blender 없이 돈다.

고정하는 것 (2026-10-22 실측 · 사용자 승인값):
  - 늘어남: 0.10 초과 ≤ 10 그리고 최장 ≤ 0.11 이면 PASS — stalker run_03(6, 0.105) 통과, oiler run_fwd(24) CHECK
  - 발 쓸기: 나쁜 발 기준 PASS ≤ −0.45 / FAIL > −0.20 — stalker −0.8 · run_slow −0.469 통과, 04b 불합격
  - inplace 면제, 역할 없는 run 은 CHECK
  - 수용 기록: 나빠지지 않으면 ACCEPTED, 나빠지면 원래 판정
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from g4_rules import judge, judge_edges, judge_sweep, sweep_worst

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

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
