"""모션 트랙의 맥북 구간 시험 — 기준 자세 기록, 다른 클립 굽기, 캐릭터 FBX + 클립 FBX.

Blender 와 미러의 walker_walk_02 리그가 있어야 돈다 (없으면 건너뛴다). 2~3분 걸린다.
가장 중요한 것은 A 다 — **새 경로가 기존 동작을 깨지 않았는가.** 리그를 만든 클립을
"다른 클립인 것처럼" rest_pose.json 을 거쳐 구우면 기존 animated.blend 와 같아야 한다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
S = REPO / "scripts"
BLENDER = "/Applications/Blender4.5.app/Contents/MacOS/Blender"
H = Path(os.path.expanduser("~/data"))
SAMPLE, FRAME = "walker_walk_02", 138
RIG = H / "06_rig" / SAMPLE

CMP = r'''
import bpy, sys, json
a, b, out = sys.argv[sys.argv.index("--")+1:][:3]
def curves(path):
    bpy.ops.wm.open_mainfile(filepath=path)
    act = bpy.data.objects["SMPL_rig"].animation_data.action
    return act.name, {f"{fc.data_path}[{fc.array_index}]": [kp.co[1] for kp in fc.keyframe_points] for fc in act.fcurves}
na, ca = curves(a); nb, cb = curves(b)
same_keys = sorted(ca) == sorted(cb) and all(len(ca[k]) == len(cb[k]) for k in ca)
mx = max((abs(x - y) for k in ca for x, y in zip(ca[k], cb[k])), default=9.0) if same_keys else 9.0
loc0 = [cb[f'pose.bones["Pelvis"].location[{i}]'][0] for i in range(3)]
json.dump({"names": [na, nb], "curves": len(cb), "same_keys": same_keys, "max_diff": mx,
           "frames": len(next(iter(cb.values()))), "pelvis_loc0": loc0}, open(out, "w"))
'''
FBX = r'''
import bpy, sys, json
out = sys.argv[sys.argv.index("--")+1]; res = {}
for path in sys.argv[sys.argv.index("--")+2:]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=path)
    arm = [o for o in bpy.data.objects if o.type == "ARMATURE"]; mesh = [o for o in bpy.data.objects if o.type == "MESH"]
    res[path.split("/")[-1]] = {"bones": len(arm[0].data.bones) if arm else 0, "root": arm[0].name if arm else None,
        "meshes": len(mesh), "verts": len(mesh[0].data.vertices) if mesh else 0,
        "actions": [[a.name, int(a.frame_range[0]), int(a.frame_range[1])] for a in bpy.data.actions]}
json.dump(res, open(out, "w"))
'''


def blender(script, *args):
    r = subprocess.run([BLENDER, "--background", "--python", str(script), "--", *map(str, args)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def main():
    need = [RIG / "transferred.blend", RIG / "animated.blend", RIG / "wham_pose.npz",
            H / "05_smpl_mesh" / SAMPLE / "smpl_tpose.obj"]
    if not os.path.exists(BLENDER) or not all(p.exists() for p in need):
        print("⚠️  Blender 또는 미러의 walker_walk_02 리그가 없어 건너뛴다")
        return 0
    ok = True

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 미러를 건드리지 않도록 data 루트를 임시 폴더에 흉내 낸다 (큰 파일은 링크)
        data = tmp / "data"
        (data / "06_rig" / SAMPLE).mkdir(parents=True)
        (data / "05_smpl_mesh" / SAMPLE).mkdir(parents=True)
        for f in ("transferred.blend", "wham_pose.npz", "aligned_params.json"):
            os.symlink(RIG / f, data / "06_rig" / SAMPLE / f)
        os.symlink(need[3], data / "05_smpl_mesh" / SAMPLE / "smpl_tpose.obj")
        env = dict(os.environ, PIPELINE_VOL=str(tmp))

        print("── 기준 자세 기록 (make_rest_pose.py)")
        r = subprocess.run([sys.executable, str(S / "make_rest_pose.py"), "--character", "walker",
                            "--sample", SAMPLE, "--frame", str(FRAME)], capture_output=True, text=True, env=env)
        rest_p = data / "06_rig" / SAMPLE / "rest_pose.json"
        check("rest_pose.json · character.json 생성", r.returncode == 0 and rest_p.exists()
              and (data / "06_rig" / "walker" / "character.json").exists(), r.stderr[-200:])
        rest = json.load(open(rest_p))
        import numpy as np
        d = np.load(RIG / "wham_pose.npz")
        check("pose 는 키프레임의 pose, trans_first 는 첫 프레임",
              np.allclose(rest["pose"], d["pose"][FRAME], atol=1e-6)
              and np.allclose(rest["trans_first"], d["trans"][0], atol=1e-6)
              and np.allclose(rest["trans_ref"], d["trans"][FRAME], atol=1e-6))
        check("신장 1.6~1.9 (T포즈 OBJ 의 세로 범위)", 1.6 < rest["smpl_height"] < 1.9, rest["smpl_height"])
        char = json.load(open(data / "06_rig" / "walker" / "character.json"))
        check("character.json 은 리그를 가리키기만 한다 (data 루트 기준 상대 경로)",
              char["rig_dir"] == f"06_rig/{SAMPLE}" and char["keyframe"] == FRAME, char["rig_dir"])
        r = subprocess.run([sys.executable, str(S / "make_rest_pose.py"), "--character", "walker",
                            "--sample", SAMPLE, "--frame", "18"], capture_output=True, text=True, env=env)
        check("리그의 키프레임이 아닌 프레임을 주면 멈춘다 (정렬 기록과 대조)",
              r.returncode != 0 and "정렬 기록과 다르다" in r.stderr + r.stdout)

        print("── A. 같은 클립을 rest_pose.json 을 거쳐 굽기 = 기존 결과")
        cmp_py, fbx_py = tmp / "cmp.py", tmp / "fbx.py"
        cmp_py.write_text(CMP)
        fbx_py.write_text(FBX)
        same = tmp / "same.blend"
        rc, out = blender(S / "apply_wham_pose.py", "--blend", RIG / "transferred.blend",
                          "--npz", RIG / "wham_pose.npz", "--ref-pose", rest_p,
                          "--action-name", "walk_02", "--out", same)
        check("굽기 성공", rc == 0 and same.exists() and "Traceback" not in out, out[-200:] if rc else "")
        blender(cmp_py, RIG / "animated.blend", same, tmp / "cmp.json")
        c = json.load(open(tmp / "cmp.json"))
        check(f"본 회전·루트 이동이 기존 animated.blend 와 일치 (커브 {c['curves']}, 최대 차 {c['max_diff']:.1e})",
              c["same_keys"] and c["max_diff"] < 1e-5)
        check("액션 이름이 --action-name 대로", c["names"][1] == "walk_02", c["names"])

        print("── B. 신장비 — 루트 이동만 달라진다")
        ratio = tmp / "ratio.blend"
        blender(S / "apply_wham_pose.py", "--blend", RIG / "transferred.blend", "--npz", RIG / "wham_pose.npz",
                "--ref-pose", rest_p, "--height-ratio", "2.0", "--out", ratio)
        blender(cmp_py, same, ratio, tmp / "cmp2.json")
        c2 = json.load(open(tmp / "cmp2.json"))
        check("신장비 2.0: 첫 프레임의 골반 위치는 같다 (원점이 첫 프레임이므로)",
              all(abs(x - y) < 1e-6 for x, y in zip(c["pelvis_loc0"], c2["pelvis_loc0"])), c2["pelvis_loc0"])
        check("신장비 2.0: 이후 프레임은 달라진다", c2["max_diff"] > 1e-3, c2["max_diff"])

        print("── C. 캐릭터 FBX 1개 + 클립 FBX")
        char_fbx, clip_fbx = tmp / "walker.fbx", tmp / "walker@walk_02.fbx"
        rc1, _ = blender(S / "export_unity_fbx.py", "--blend", RIG / "transferred.blend", "--out", char_fbx, "--no-anim")
        rc2, _ = blender(S / "export_unity_fbx.py", "--blend", same, "--out", clip_fbx,
                         "--armature-only", "--take-name", "walk_02")
        check("둘 다 내보내짐", rc1 == 0 and rc2 == 0 and char_fbx.exists() and clip_fbx.exists())
        blender(fbx_py, tmp / "fbx.json", char_fbx, clip_fbx)
        f = json.load(open(tmp / "fbx.json"))
        a, b = f["walker.fbx"], f["walker@walk_02.fbx"]
        check("캐릭터 FBX: 메쉬 1 + 본 24, 동작 없음", a["meshes"] == 1 and a["bones"] == 24 and a["actions"] == [], a)
        check("클립 FBX: 메쉬 없음 + 본 24, 동작 1개(walk_02, 192프레임)",
              b["meshes"] == 0 and b["bones"] == 24 and len(b["actions"]) == 1
              and b["actions"][0][0].endswith("walk_02") and b["actions"][0][2] - b["actions"][0][1] == 191, b)
        check("두 FBX 의 골격 루트 이름이 같다 (Unity 가 아바타를 공유하려면)", a["root"] == b["root"], (a["root"], b["root"]))
        sz = (char_fbx.stat().st_size, clip_fbx.stat().st_size)
        check(f"클립 FBX 는 캐릭터 FBX 의 1% 미만 ({sz[1] / 1e3:.0f}KB 대 {sz[0] / 1e6:.0f}MB)", sz[1] < sz[0] * 0.01)
        rc, out = blender(S / "export_unity_fbx.py", "--blend", same, "--out", tmp / "x.fbx", "--armature-only", "--no-anim")
        check("--armature-only 와 --no-anim 을 함께 주면 내보내지 않는다", not (tmp / "x.fbx").exists())

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
