#!/usr/bin/env python3
"""character.json v1 → v2 전환 (2026-11-06) — 5-4b 값을 채택 리그의 근거 파일에서 그대로 옮긴다.

  python3 tools/review/migrate_character_v2.py --data ~/data [--dry-run]

수치는 손으로 적지 않는다. 각 단계의 pairs · rings · iters · lam 은 채택 리그 폴더의
transferred_smooth_params_<label>.json(smooth_seams.py 가 그 실행에서 남긴 기록)에서 읽고, 단계 순서는
그 리그의 WFIX.md 에 적힌 순서다. 기존 필드는 건드리지 않고 rig_build · bake 두 절만 덧붙인다.
쓰기 전에 v1 을 character_prev_v1_<날짜>.json 으로 복사한다. 이미 v2 면 건너뛴다.

근거 (2026-11-06 확인):
  listener  rig listener_apose_06_wfixc — WFIX.md 1~4: 5-4 기본값 → 가랑이 → 겨드랑이 → 가슴.
            5-4 입력은 listener_apose_06/rigged.blend (listener_apose_06_wfix_base/transfer.log 의 "Read blend").
            fallback_height: 사용 기록 없음 → null
  walker    rig walker_walk_02_wfix — WFIX.md 1~3: 5-4 는 walker_walk_02/transferred.blend 그대로 → 가랑이 → 겨드랑이.
            (walker_walk_02_wfix_c10arm20/transferred.blend 와 sha256 동일 — 그 실험의 결과를 채택한 것)
            fallback_height 1.7881: 10/26 walker 최종 굽기(review_1026 08_final)의 bake_run.log 한 줄
            "(walker_fall_back_c2_t0: T포즈 메쉬 없음 — 평균 신장 1.7881 사용)"
"""
import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

PLAN = {
    "listener": {"source_sample": "listener_apose_06", "order": ["crotch", "armpit", "collar"], "fallback_height": None},
    "walker": {"source_sample": "walker_walk_02", "order": ["crotch", "armpit"], "fallback_height": 1.7881},
}


def build(data, character, spec):
    cp = Path(data) / "06_rig" / character / "character.json"
    cfg = json.loads(cp.read_text())
    rig = Path(data) / cfg["rig_dir"]
    passes = []
    for label in spec["order"]:
        ev = rig / f"transferred_smooth_params_{label}.json"
        e = json.loads(ev.read_text())
        if e.get("stage") != "5-4b" or e.get("script") != "smooth_seams.py":
            raise SystemExit(f"[오류] 근거 파일이 5-4b 기록이 아니다: {ev}")
        passes.append({"label": label, "pairs": [p.replace("|", ":") for p in e["pairs"]],
                       "rings": e["rings"], "iters": e["iters"], "lam": e["lam"],
                       "evidence": str(ev).replace(str(Path.home()), "~")})
    v2 = dict(cfg)
    v2["version"] = 2
    v2["rig_build"] = {"source_sample": spec["source_sample"], "transfer": {}, "seam_smooth": passes}
    v2["bake"] = {"fallback_height": spec["fallback_height"]}
    return cp, cfg, v2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    for ch, spec in PLAN.items():
        cp, v1, v2 = build(a.data, ch, spec)
        if v1.get("version") == 2:
            print(f"{ch}: 이미 v2 — 건너뜀")
            continue
        print(f"{ch}: " + " → ".join(f"{p['label']}({','.join(p['pairs'])} {p['rings']}/{p['iters']} lam {p['lam']})"
                                     for p in v2["rig_build"]["seam_smooth"])
              + f", source {spec['source_sample']}, fallback_height {spec['fallback_height']}")
        if a.dry_run:
            continue
        keep = cp.with_name(f"character_prev_v1_{date.today():%Y%m%d}.json")
        if keep.exists():
            raise SystemExit(f"[오류] 보존본이 이미 있다: {keep}")
        shutil.copy2(cp, keep)
        cp.write_text(json.dumps(v2, indent=1, ensure_ascii=False))
        print(f"  기록함: {cp}  (v1 보존 {keep.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
