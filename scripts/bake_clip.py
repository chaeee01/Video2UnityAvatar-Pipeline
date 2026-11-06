#!/usr/bin/env python3
"""동작 트랙 BAKE — 클립 하나를 캐릭터의 채택 리그에 굽는다. tools/review/bake_character.sh 한 편과 같은 순서다.

  python3 bake_clip.py --data ~/data --character listener --clip listener_walk_01_1102 [--dry-run]

  1. 리그 = character.json 의 rig_dir (transferred.blend · rest_pose.json). 신장 H = rest_pose.json smpl_height
  2. 동작 = 06_rig/<리그>/motions/<클립>/wham_pose.npz.
     blend_seam.json · track_select.json 이 있으면 고정 npz 를 그대로 쓴다. 없으면
     04_wham/<클립>_masked/wham_output_stitched.pkl(없으면 wham_output.pkl)에서 convert_wham_npz.py 로 만든다
  3. 신장비 = H / (05_smpl_mesh/<클립>/smpl_tpose.obj 의 높이). T포즈 메쉬가 없으면 H / bake.fallback_height
  4. apply_wham_pose.py --ref-pose --height-ratio --action-name <클립> [--ground-align]
     바닥 정렬 여부는 역할표(clip_roles.json) 그 클립의 bake.ground_align — **적혀 있지 않으면 멈춘다**(조용한 기본값 없음)

bake_character.sh 의 검토용 산출물(dump2 · 재생 렌더 · 비교 영상)은 만들지 않는다 — 판정은 다음 단계 G4 가 한다.
이미 animated.blend 가 있으면 지우지 않고 animated.blend.prev_<일시> 로 옮긴 뒤 굽는다.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from character_config import ConfigError, load, load_roles, resolve_clip  # noqa: E402

BLENDER = os.environ.get("BLENDER", "/Applications/Blender4.5.app/Contents/MacOS/Blender")
S = Path(__file__).resolve().parent


def height_ratio(data, clip, H, fallback):
    """bake_character.sh 와 같은 식 · 같은 부동소수 문자열 (python3 print = repr)."""
    obj = Path(data) / "05_smpl_mesh" / clip / "smpl_tpose.obj"
    if obj.exists():
        ys = [float(l.split()[2]) for l in open(obj) if l.startswith("v ")]
        return H / (max(ys) - min(ys)), f"T포즈 메쉬 {obj}"
    if fallback is None:
        raise ConfigError(f"T포즈 메쉬가 없는데 character.json bake.fallback_height 도 없다 ({obj})")
    return H / fallback, f"T포즈 메쉬 없음 — 평균 신장 {fallback} 사용"


def plan(data, character, clip):
    data = Path(data)
    cfg, _ = load(data, character)
    roles, roles_path = load_roles(data, character)
    key, entry = resolve_clip(roles, clip)
    if key is None:
        raise ConfigError(f"역할표에 클립이 없다: {clip} ({roles_path}) — 항목(source · bake.ground_align)을 먼저 적는다")
    ga = (entry.get("bake") or {}).get("ground_align")
    if not isinstance(ga, bool):
        raise ConfigError(f"역할표 {key}: bake.ground_align 이 없다 (true/false 를 적는다) — {roles_path}")
    rig = data / cfg["rig_dir"]
    H = json.loads((rig / "rest_pose.json").read_text())["smpl_height"]
    M = rig / "motions" / clip
    fixed = [n for n in ("blend_seam.json", "track_select.json") if (M / n).exists()]
    pkl = data / "04_wham" / f"{clip}_masked" / "wham_output_stitched.pkl"
    if not pkl.exists():
        pkl = data / "04_wham" / f"{clip}_masked" / "wham_output.pkl"
    r, r_note = height_ratio(data, clip, H, (cfg.get("bake") or {}).get("fallback_height"))
    conv = None if fixed else ["python3", str(S / "convert_wham_npz.py"), "--pkl", str(pkl), "--out", str(M / "wham_pose.npz")]
    bake = [BLENDER, "--background", "--python", str(S / "apply_wham_pose.py"), "--",
            "--blend", str(rig / cfg.get("blend", "transferred.blend")), "--npz", str(M / "wham_pose.npz"),
            "--ref-pose", str(rig / cfg.get("rest_pose", "rest_pose.json")), "--height-ratio", str(r),
            "--action-name", clip, *(["--ground-align"] if ga else []), "--out", str(M / "animated.blend")]
    return dict(key=key, rig=rig, motion=M, fixed=fixed, pkl=pkl, ratio=r, ratio_note=r_note,
                ground_align=ga, convert=conv, bake=bake, roles=roles_path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="data 루트 (<vol>/data)")
    ap.add_argument("--character", required=True)
    ap.add_argument("--clip", required=True, help="클립 이름(굽기 폴더 이름 = 역할표 source)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        p = plan(a.data, a.character, a.clip)
    except (ConfigError, OSError, KeyError, ValueError) as e:
        print(f"[오류] {e}")
        return 1
    M = p["motion"]
    print(f"클립 {a.clip} (납품 {p['key']}) → 리그 {p['rig'].name}, 신장비 {p['ratio']} ({p['ratio_note']}), "
          f"바닥 정렬 {'켬' if p['ground_align'] else '끔'}")
    if p["fixed"]:
        print(f"  고정 npz 사용 — {', '.join(p['fixed'])}")
    for cmd in ([p["convert"]] if p["convert"] else []) + [p["bake"]]:
        print("    $ " + " ".join(cmd))
    if a.dry_run:
        return 0
    M.mkdir(parents=True, exist_ok=True)
    if p["convert"]:
        with open(M / "conv.log", "w") as f:
            if subprocess.run([sys.executable, *p["convert"][1:]], stdout=f, stderr=subprocess.STDOUT).returncode:
                print(f"  실패: npz 변환 — {M / 'conv.log'}")
                return 1
    if not (M / "wham_pose.npz").exists():
        print(f"  실패: {M / 'wham_pose.npz'} 가 없다")
        return 1
    out = M / "animated.blend"
    if out.exists():
        keep = out.with_name(f"animated.blend.prev_{datetime.now():%Y%m%d_%H%M%S}")
        out.rename(keep)
        print(f"  기존 animated.blend 보존 → {keep.name}")
    with open(M / "bake.log", "w") as f:
        rc = subprocess.run(p["bake"], stdout=f, stderr=subprocess.STDOUT).returncode
    if rc != 0 or not out.exists():
        print(f"  실패: 굽기 종료 코드 {rc}, 출력 {'있음' if out.exists() else '없음'} — {M / 'bake.log'}")
        return 1
    (M / "bake_clip.json").write_text(json.dumps({k: (str(v) if isinstance(v, Path) else v) for k, v in p.items()},
                                                 indent=1, ensure_ascii=False))
    print(f"  완료: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
