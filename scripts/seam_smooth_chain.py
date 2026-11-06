#!/usr/bin/env python3
"""5-4b 경계 스무딩을 캐릭터 설정(character.json rig_build.seam_smooth)에 적힌 순서대로 잇는다.

  python3 seam_smooth_chain.py --config ~/data/06_rig/<캐릭터>/character.json \\
      --blend ~/data/06_rig/<샘플>/transferred.blend \\
      --out   ~/data/06_rig/<샘플>/transferred_5-4b.blend [--dry-run]

수동 체인(RUNBOOK 5-4b, 각 리그의 WFIX.md)과 같은 일을 한다 — 단계마다 smooth_seams.py 를 Blender 로 한 번씩
부르고, 앞 단계의 출력 blend 가 다음 단계의 입력이다. 5-4 의 transferred.blend 는 덮어쓰지 않는다:
  단계 1..n-1  <out 이름>_<i>_<label>.blend  (+ _smooth_params.json)
  단계 n       <out>                          (+ <out 이름>_smooth_params.json)
  기록         <out 이름>_chain.json — 단계 · 인자 · 입출력 · 각 단계의 smooth_params 경로
단계가 하나라도 실패하면(종료 코드 ≠ 0 또는 출력 없음) 그 자리에서 멈춘다. 남은 단계를 건너뛰지 않는다.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from character_config import ConfigError, seam_passes, validate  # noqa: E402

BLENDER = os.environ.get("BLENDER", "/Applications/Blender4.5.app/Contents/MacOS/Blender")


def pass_argv(p, src, dst):
    return [BLENDER, "--background", "--python", str(Path(__file__).resolve().parent / "smooth_seams.py"), "--",
            "--blend", str(src), "--out", str(dst),
            "--pairs", ",".join(p["pairs"]), "--rings", str(p["rings"]), "--iters", str(p["iters"]),
            "--lam", repr(float(p["lam"]))]


def plan(passes, blend, out):
    out = Path(out)
    steps, src = [], Path(blend)
    for i, p in enumerate(passes, 1):
        dst = out if i == len(passes) else out.with_name(f"{out.stem}_{i}_{p['label']}{out.suffix}")
        steps.append((p, src, dst))
        src = dst
    return steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="character.json (v2, rig_build.seam_smooth)")
    ap.add_argument("--blend", required=True, help="5-4 출력 transferred.blend")
    ap.add_argument("--out", required=True, help="5-4b 최종 blend")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        passes = seam_passes(validate(json.loads(Path(a.config).read_text()), a.config))
    except (ConfigError, ValueError) as e:
        print(f"[오류] 설정: {e}")
        return 1
    if not passes:
        print(f"[오류] {a.config} 에 rig_build.seam_smooth 가 없다 — 5-4b 대상이 아니다")
        return 1
    out = Path(a.out)
    rec = {"stage": "5-4b", "config": str(a.config), "input": str(a.blend), "out": str(out), "steps": []}
    for i, (p, src, dst) in enumerate(plan(passes, a.blend, out), 1):
        argv = pass_argv(p, src, dst)
        print(f"[5-4b {i}/{len(passes)}] {p['label']}: {','.join(p['pairs'])} rings {p['rings']} iters {p['iters']} lam {p['lam']}")
        print("    $ " + " ".join(argv))
        if a.dry_run:
            continue
        log = dst.with_name(f"{dst.stem}.log")
        t0 = datetime.now()
        with open(log, "w") as f:
            rc = subprocess.run(argv, stdout=f, stderr=subprocess.STDOUT).returncode
        # Blender 는 --python 스크립트가 예외로 죽어도 0 을 낸다 — 출력이 생겼는지로 판정한다
        pj = dst.with_name(f"{dst.stem}_smooth_params.json")
        if rc != 0 or not dst.exists() or not pj.exists():
            print(f"    실패: 종료 코드 {rc}, 출력 {'있음' if dst.exists() else '없음'} — {log}")
            return 1
        rec["steps"].append({"n": i, "label": p["label"], "pairs": p["pairs"], "rings": p["rings"],
                             "iters": p["iters"], "lam": p["lam"], "input": str(src), "out": str(dst),
                             "smooth_params": str(pj), "log": str(log),
                             "elapsed_s": round((datetime.now() - t0).total_seconds(), 1)})
    if not a.dry_run:
        out.with_name(f"{out.stem}_chain.json").write_text(json.dumps(rec, indent=1, ensure_ascii=False))
        print(f"완료: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
