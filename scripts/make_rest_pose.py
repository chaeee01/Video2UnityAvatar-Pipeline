#!/usr/bin/env python3
"""리그의 기준 자세 기록(rest_pose.json)과 캐릭터 포인터(character.json)를 만든다.

외형 트랙이 끝난 리그에 대해 한 번 돌린다. 모션 트랙이 **다른 클립의 동작**을 이 리그에
구울 때 이 기록을 읽는다 (apply_wham_pose.py --ref-pose).

  python3 make_rest_pose.py --character walker --sample walker_walk_02 --frame 138

왜 필요한가 — 리그의 rest 자세는 T포즈가 아니라 **그 리그를 만든 키프레임의 자세**다
(T포즈 통일은 EH-211, 미구현). 베이킹은 "기준 자세 대비 상대 회전" 이므로, 같은 캐릭터의
다른 클립을 구우려면 그 기준 자세(리그를 만든 클립의 그 프레임 pose)를 알아야 한다.
그것만 있으면 EH-211 없이도 같은 캐릭터 안에서는 동작을 옮길 수 있다.

쓰는 것:
  <data>/06_rig/<샘플>/rest_pose.json
      pose         기준 자세 — 리그 클립의 키프레임 pose (72, axis-angle, WHAM 카메라 좌표)
      trans_ref    그 프레임의 루트 위치
      trans_first  리그 클립 **첫 프레임**의 루트 위치 (아래 "첫 프레임 가정" 참조)
      smpl_height  이 체형(평균 betas)의 T포즈 신장 — trans 를 옮길 때 신장비의 분모
      align_scale  5-2 정렬 스케일 (참고용 — 베이킹은 blend 의 SMPL_body 에서 직접 읽는다)
  <data>/06_rig/<캐릭터>/character.json
      캐릭터 이름 → 리그가 있는 샘플 폴더. 리그를 옮기지 않고 가리키기만 한다.

**첫 프레임 가정.** 모션 클립은 자기 첫 프레임을 원점으로 삼는다. 그런데 리그의 rest 는
키프레임 자세라 첫 프레임의 자세와 골반 높이가 다르다(벌린 다리 대 선 자세). 그 차이를
리그 클립에서 잰 (trans_first - trans_ref) 로 메운다. 이것은 **모션 클립의 첫 프레임이
리그 클립의 첫 프레임과 같은 자세**일 때 맞는다 — Veo 의 시작 프레임 방식으로 만든 클립은
같은 레퍼런스 이미지에서 출발하므로 성립한다. 그렇지 않은 클립을 구우면 발이 뜨거나 묻힌다.
"""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np

VOL = Path(os.environ.get("PIPELINE_VOL", "/workspace"))


def obj_height(path):
    """OBJ 의 세로 범위. SMPL T포즈는 Y 가 위(또는 아래)이고 팔이 수평이라 Y 범위가 곧 신장이다."""
    ys = [float(line.split()[2]) for line in open(path) if line.startswith("v ")]
    if not ys:
        raise SystemExit(f"정점이 없다: {path}")
    return max(ys) - min(ys)


def main():
    ap = argparse.ArgumentParser(description="rest_pose.json · character.json 생성")
    ap.add_argument("--character", required=True, help="캐릭터 이름 (예: walker)")
    ap.add_argument("--sample", required=True, help="리그를 만든 샘플 이름 (예: walker_walk_02)")
    ap.add_argument("--frame", type=int, required=True, help="리그를 만든 키프레임 번호")
    ap.add_argument("--data", default=str(VOL / "data"), help="data 루트 (기본 <vol>/data)")
    ap.add_argument("--verdict", default=None, help="육안 판정 메모 (예: '합격 2026-10-12')")
    a = ap.parse_args()

    data = Path(os.path.expanduser(a.data))
    rig = data / "06_rig" / a.sample
    npz = rig / "wham_pose.npz"
    tpose = data / "05_smpl_mesh" / a.sample / "smpl_tpose.obj"
    for f in (rig / "transferred.blend", npz, tpose, rig / "aligned_params.json"):
        if not f.exists():
            raise SystemExit(f"없음: {f}")

    d = np.load(npz)
    pose, trans = d["pose"], d["trans"]
    if not (0 <= a.frame < len(pose)):
        raise SystemExit(f"--frame {a.frame} 이 범위 밖이다 (0..{len(pose) - 1})")
    align = json.load(open(rig / "aligned_params.json"))
    # 키프레임이 이 리그의 것인지 — 정렬에 쓴 SMPL 메쉬 이름과 맞춰 본다 (추측하지 않는다)
    want = f"smpl_frame{a.frame}.obj"
    if Path(align.get("smpl", "")).name != want:
        raise SystemExit(f"--frame {a.frame} 이 이 리그의 정렬 기록과 다르다: "
                         f"aligned_params.json 은 {Path(align.get('smpl', '')).name} 을 썼다")

    rest = {
        "version": 1,
        "character": a.character,
        "rig_sample": a.sample,
        "frame": a.frame,
        "n_frames": int(len(pose)),
        "pose": [round(float(x), 7) for x in pose[a.frame]],
        "trans_ref": [round(float(x), 7) for x in trans[a.frame]],
        "trans_first": [round(float(x), 7) for x in trans[0]],
        "smpl_height": round(obj_height(tpose), 6),
        "align_scale": align.get("scale"),
        "source": {"npz": f"06_rig/{a.sample}/wham_pose.npz",
                   "tpose": f"05_smpl_mesh/{a.sample}/smpl_tpose.obj"},
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    out = rig / "rest_pose.json"
    out.write_text(json.dumps(rest, ensure_ascii=False, indent=1))

    cdir = data / "06_rig" / a.character
    cdir.mkdir(parents=True, exist_ok=True)
    char = {
        "version": 1,
        "character": a.character,
        "rig_sample": a.sample,                       # 리그는 옮기지 않는다 — 여기를 가리킨다
        "rig_dir": f"06_rig/{a.sample}",              # data 루트 기준 (Pod·맥북에서 루트만 다르다)
        "blend": "transferred.blend",
        "rest_pose": "rest_pose.json",
        "keyframe": a.frame,
        "verdict": a.verdict,
        "date": rest["date"],
    }
    (cdir / "character.json").write_text(json.dumps(char, ensure_ascii=False, indent=1))
    print(f"기준 자세: {out}")
    print(f"  프레임 {a.frame}/{len(pose) - 1}  신장 {rest['smpl_height']}  정렬 스케일 {rest['align_scale']}")
    print(f"캐릭터: {cdir / 'character.json'}  →  {char['rig_dir']}")


if __name__ == "__main__":
    main()
