"""리그 rest 자세의 머리–발목 높이 ÷ 전체 키 비율을 잰다 (읽기 전용, Blender).

11/02 권장 이동 속도 산출 기록(review_1102/sweep_target_1102.md)의 정의를 재현한다:
  "머리–발목(유닛) = 키(유닛) × (리그 rest 자세의 머리–발목 ÷ 전체 키). 비율은 리그 transferred.blend 에서 실측."
  전체 키 = 메쉬 최고점–최저점. 당시 측정 스크립트가 남아 있지 않아(결손) 2026-11-23 에 다시 만들었다.
  walker 기록값(전체 키 1.0003 · 머리–발목 0.8230 · 비율 0.8227)과 대조해 방법을 검증한다.

확정 정의 (2026-11-23 검증):
  비율 = (Head 본 시작점 z − 낮은 발목 본(L/R_Ankle) 시작점 z) ÷ 메쉬(geometry_0) 높이(월드 z 최고–최저), rest 자세.
  끝점(Head tail) 기준은 기록과 불일치한다 — walker 0.8496 (기록 0.8230). 결과의 ratio_headstart 가 정의값이다.
  walker 검증값 (~/data/06_rig/walker_walk_02_wfix/transferred.blend, 맥 Blender 4.5):
    전체 키 1.0003 · 머리–발목 0.8230 — 기록과 일치, 비율 0.8228 (기록 0.8227 — 마지막 자리 반올림 차)
  실측 (Pod v3 이미지 Blender 4.5.12): teacher_shape_01 0.9945 · 0.8456 · 0.8502 / student_shape_01 1.0000 · 0.8508 · 0.8508
  권장 이동 속도(유닛/초) = |G4 발 쓸기(H/초)| × 캐릭터 키(유닛) × 비율.

  $BLENDER --background --python tools/review/rig_head_ankle_ratio.py -- --blend <06_rig/<리그>/transferred.blend> [--mesh geometry_0]

출력(JSON 한 줄, "RATIO_JSON " 접두): 메쉬 높이, 머리–발목 두 변형(Head 본 시작점 / 끝점 − 낮은 발목 본 시작점), 각 비율.
아무것도 쓰지 않는다(파일 저장 없음).
"""
import json
import sys

import bpy
from mathutils import Vector


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {"blend": None, "mesh": None}
    for k, v in zip(a[::2], a[1::2]):
        out[k.lstrip("-")] = v
    return out


def main():
    a = args()
    bpy.ops.wm.open_mainfile(filepath=a["blend"])
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if len(arms) != 1:
        raise SystemExit(f"아마추어가 1개가 아니다: {[o.name for o in arms]}")
    arm = arms[0]
    mw = arm.matrix_world
    b = arm.data.bones
    head_h = (mw @ b["Head"].head_local).z
    head_t = (mw @ b["Head"].tail_local).z
    ankle = min((mw @ b["L_Ankle"].head_local).z, (mw @ b["R_Ankle"].head_local).z)
    res = {"blend": a["blend"], "armature": arm.name, "meshes": {}}
    for o in meshes:
        zs = [(o.matrix_world @ Vector(v.co)).z for v in o.data.vertices]  # rest(모디파이어 미적용) 좌표
        res["meshes"][o.name] = {"verts": len(zs), "height": round(max(zs) - min(zs), 4)}
    name = a["mesh"] or max(res["meshes"], key=lambda k: res["meshes"][k]["verts"])
    H = res["meshes"][name]["height"]
    res.update(mesh=name, total_height=H,
               head_ankle_headstart=round(head_h - ankle, 4), ratio_headstart=round((head_h - ankle) / H, 4),
               head_ankle_headend=round(head_t - ankle, 4), ratio_headend=round((head_t - ankle) / H, 4))
    print("RATIO_JSON " + json.dumps(res, ensure_ascii=False))


main()
