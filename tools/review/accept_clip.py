#!/usr/bin/env python3
"""G4 수용 기록 — 사람이 보고 받아들인 CHECK/FAIL 을 clip_roles.json 의 accepted 에 남긴다.

  python3 tools/review/accept_clip.py --roles ~/data/06_rig/<캐릭터>/clip_roles.json \\
      --clip <납품 이름 또는 source> --gate edges|sweep|ground \\
      --g4 <g4_<클립>.json> --reason "<사유>" [--date 2026-11-02] [--dry-run]

수치는 그 G4 판정 JSON 에서 g4_rules 가 비교하는 값 그대로 옮긴다 — edges: max10 · longest, sweep: sweep_worst,
ground: float_first · float_last · sink_depth. 다시 돌렸을 때 이 수치보다 나빠지지 않으면 ACCEPTED 가 된다
(scripts/g4_rules.py apply_acceptance). 오케스트레이터는 수용 기록을 쓰지 않는다 — 이 명령이 유일한 경로다.

멈추는 경우: 그 부분 판정이 CHECK/FAIL 이 아님(받아들일 것이 없다), 판정 JSON 의 클립이 --clip 과 다름,
같은 gate 의 수용 기록이 이미 있음. 쓰기 전에 역할표를 clip_roles.json.bak_<일시> 로 복사한다.
"""
import argparse
import json
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from g4_rules import ground_metrics, resolve  # noqa: E402


def metrics_for(gate, g4):
    part = g4.get(gate) or {}
    if gate == "edges":
        return {"max10": part["max10"], "longest": part["longest"]}
    if gate == "sweep":
        return {"sweep_worst": part["worst"]}
    return ground_metrics(part)


def make_entry(roles, clip, gate, g4, reason, day):
    key, entry = resolve(roles, clip)
    if key not in roles.get("clips", {}):
        raise SystemExit(f"[오류] 역할표에 클립이 없다: {clip}")
    k2, _ = resolve(roles, g4.get("clip", ""))
    if k2 != key:
        raise SystemExit(f"[오류] 판정 JSON 의 클립({g4.get('clip')})이 --clip({clip} → {key})과 다르다")
    pv = (g4.get(gate) or {}).get("verdict")
    if pv not in ("CHECK", "FAIL"):
        raise SystemExit(f"[오류] {key} 의 {gate} 판정이 {pv} 다 — 받아들일 CHECK/FAIL 이 없다")
    if any(a.get("gate") == gate for a in entry.get("accepted", [])):
        raise SystemExit(f"[오류] {key} 에 gate {gate} 수용 기록이 이미 있다 — 손으로 확인한다")
    return key, {"gate": gate, "reason": reason, "date": day, "metrics": metrics_for(gate, g4)}, pv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roles", required=True)
    ap.add_argument("--clip", required=True)
    ap.add_argument("--gate", required=True, choices=["edges", "sweep", "ground"])
    ap.add_argument("--g4", required=True, help="그 클립의 G4 판정 JSON")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--date", default=str(date.today()), help="수용 날짜 (기본 오늘)")
    ap.add_argument("--dry-run", action="store_true", help="적을 내용만 보여 준다")
    a = ap.parse_args()
    rp = Path(a.roles)
    roles = json.loads(rp.read_text())
    g4 = json.loads(Path(a.g4).read_text())
    key, rec, pv = make_entry(roles, a.clip, a.gate, g4, a.reason, a.date)
    print(f"{key} ({g4.get('clip')}) {a.gate} {pv} → 수용 기록: {json.dumps(rec, ensure_ascii=False)}")
    if a.dry_run:
        return 0
    bak = rp.with_name(f"{rp.name}.bak_{datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(rp, bak)
    roles["clips"][key].setdefault("accepted", []).append(rec)
    rp.write_text(json.dumps(roles, indent=1, ensure_ascii=False))
    print(f"  기록함: {rp}  (이전 판 {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
