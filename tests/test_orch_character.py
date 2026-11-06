"""캐릭터 설정 v2 · 5-4b · 동작 트랙 · G4 정지 · 수용 기록 · 루트 분리 시험 (2026-11-06).

Blender · Pod 없이 맥북에서 돈다. 실데이터 대조(listener 리그 웨이트 · 11/02 4편 굽기)는 따로 한다 —
여기서는 분기 · 명령 · 기록의 규칙만 본다.
"""
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "tools" / "review"))

import accept_clip  # noqa: E402
import bake_clip  # noqa: E402
import character_config as cc  # noqa: E402
import g4_rules  # noqa: E402
import seam_smooth_chain  # noqa: E402

OK = True


def check(label, cond, got=""):
    global OK
    OK &= bool(cond)
    print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")


def raises(fn):
    try:
        fn()
    except (cc.ConfigError, SystemExit) as e:
        return str(e) or True
    return False


PASSES = [
    {"label": "crotch", "pairs": ["L_Hip:R_Hip"], "rings": 10, "iters": 40, "lam": 0.5},
    {"label": "armpit", "pairs": ["L_Shoulder:Spine1", "L_Shoulder:Spine2", "R_Shoulder:Spine1", "R_Shoulder:Spine2"],
     "rings": 20, "iters": 160, "lam": 0.5},
    {"label": "collar", "pairs": ["L_Collar:R_Collar", "L_Collar:Spine1", "R_Collar:Spine1"], "rings": 10, "iters": 40, "lam": 0.5},
]
V2 = {"version": 2, "character": "lst", "rig_sample": "lst_wfixc", "rig_dir": "06_rig/lst_wfixc",
      "blend": "transferred.blend", "rest_pose": "rest_pose.json", "keyframe": 168,
      "rig_build": {"source_sample": "lst_apose", "transfer": {}, "seam_smooth": PASSES},
      "bake": {"fallback_height": None}}


def orch_module(vol, env_root=None):
    os.environ["PIPELINE_VOL"] = str(vol)
    os.environ.pop("PIPELINE_ENV_ROOT", None)
    if env_root:
        os.environ["PIPELINE_ENV_ROOT"] = str(env_root)
    import orchestrate
    return importlib.reload(orchestrate)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="orchchar_"))
    data = tmp / "vol" / "data"
    (data / "06_rig" / "lst").mkdir(parents=True)
    (data / "06_rig" / "lst" / "character.json").write_text(json.dumps(V2))

    print("── 설정 v2 읽기 · 검증")
    cfg, p = cc.load(data, "lst")
    check("v2 를 읽는다 · 단계 3개 순서 유지", [x["label"] for x in cc.seam_passes(cfg)] == ["crotch", "armpit", "collar"])
    v1 = {k: v for k, v in V2.items() if k not in ("rig_build", "bake")}
    check("v1 은 5-4b 없음으로 읽는다", cc.seam_passes(cc.validate(v1)) == [])
    for label, bad in [("pairs 가 'A|B' 꼴", {"pairs": ["L_Hip|R_Hip"]}), ("rings 0", {"rings": 0}),
                       ("iters 문자열", {"iters": "40"}), ("lam 누락", {"lam": None}), ("rings 가 bool", {"rings": True})]:
        b = json.loads(json.dumps(V2))
        b["rig_build"]["seam_smooth"][0].update(bad)
        if bad.get("lam", 1) is None:
            del b["rig_build"]["seam_smooth"][0]["lam"]
        check(f"틀린 꼴은 멈춘다 — {label}", raises(lambda: cc.validate(b)))
    b = json.loads(json.dumps(V2)); b["rig_build"]["seam_smooth"][1]["label"] = "crotch"
    check("label 중복은 멈춘다", raises(lambda: cc.validate(b)))
    hit, _ = cc.find_by_source_sample(data, "lst_apose")
    check("source_sample 로 캐릭터를 찾는다", hit and hit["character"] == "lst")
    check("없는 샘플은 (None, None)", cc.find_by_source_sample(data, "nope") == (None, None))
    (data / "06_rig" / "lst2").mkdir()
    (data / "06_rig" / "lst2" / "character.json").write_text(json.dumps(dict(V2, character="lst2")))
    check("같은 source_sample 이 둘이면 멈춘다", raises(lambda: cc.find_by_source_sample(data, "lst_apose")))
    (data / "06_rig" / "lst2" / "character.json").unlink()

    print("── 5-4b 연쇄 계획")
    steps = seam_smooth_chain.plan(PASSES, "/r/transferred.blend", "/r/transferred_5-4b.blend")
    names = [(Path(s).name, Path(d).name) for _, s, d in steps]
    check("앞 단계 출력이 다음 입력 · 마지막이 최종본", names == [
        ("transferred.blend", "transferred_5-4b_1_crotch.blend"),
        ("transferred_5-4b_1_crotch.blend", "transferred_5-4b_2_armpit.blend"),
        ("transferred_5-4b_2_armpit.blend", "transferred_5-4b.blend")], names)
    argv = seam_smooth_chain.pass_argv(PASSES[1], "a.blend", "b.blend")
    i = argv.index("--pairs")
    check("인자 = 수동 체인과 같은 값", argv[i + 1:i + 9] == ["L_Shoulder:Spine1,L_Shoulder:Spine2,R_Shoulder:Spine1,R_Shoulder:Spine2",
                                                         "--rings", "20", "--iters", "160", "--lam", "0.5", "--blend"][:8]
          or argv[i + 1:i + 8] == ["L_Shoulder:Spine1,L_Shoulder:Spine2,R_Shoulder:Spine1,R_Shoulder:Spine2",
                                   "--rings", "20", "--iters", "160", "--lam", "0.5"], argv[i:])
    check("5-4 의 transferred.blend 는 출력이 아니다", all(Path(d).name != "transferred.blend" for _, _, d in steps))

    print("── 단계 목록 · 루트")
    o = orch_module(tmp / "vol")
    check("설정 없음 → STAGES 그대로", o.stages_for({}) == o.STAGES)
    keys = [s["key"] for s in o.stages_for({"seam_passes": PASSES})]
    check("5-4b 는 5-4 바로 뒤", keys[keys.index("5-4") + 1] == "5-4b", keys)
    check("동작 트랙 = G0 · S2 · S5 · BAKE · G4 · CLIPFBX",
          [s["key"] for s in o.stages_for({"track": "motion"})] == ["G0", "S2", "S5", "BAKE", "G4", "CLIPFBX"])
    check("PIPELINE_ENV_ROOT 미설정 → 환경 루트 = 데이터 루트(현행)", o.ENV_ROOT == o.VOL)
    check("micromamba 는 환경 루트에서", o.build_cmd("wham", ["python", "x.py"])[0] == str(tmp / "vol" / "micromamba" / "bin" / "micromamba"))
    o2 = orch_module(tmp / "vol", env_root="/workspace")
    check("이미지 Pod 꼴: 데이터 /vol 류 · 환경 /workspace", o2.build_cmd("wham", ["x"])[0] == "/workspace/micromamba/bin/micromamba"
          and o2.data("04_wham") == tmp / "vol" / "data" / "04_wham")
    c51 = o2.stage_command("5-1", {"name": "s", "frame": 3})
    check("데이터 루트가 기본과 다르면 5-1 에 --out", c51[-2:] == ["--out", str(tmp / "vol" / "data" / "05_smpl_mesh")], c51[-2:])
    o3 = orch_module(Path("/workspace"))
    c51 = o3.stage_command("5-1", {"name": "s", "frame": 3})
    check("미설정(/workspace)이면 5-1 명령이 현행과 같다 (--out 없음)", "--out" not in c51 and c51[-2:] == ["--name", "s"], c51[-4:])
    c55 = o.stage_command("5-5", {"name": "s", "frame": 3, "seam_passes": PASSES})
    check("5-4b 가 돈 샘플의 5-5 는 스무딩 리그에 굽는다", any(x.endswith("transferred_5-4b.blend") for x in c55))
    c55 = o.stage_command("5-5", {"name": "s", "frame": 3})
    check("설정 없는 5-5 는 현행 그대로", any(x.endswith("/transferred.blend") for x in c55))

    print("── 환경이 없으면 멈춘다 (이미지 Pod)")
    envr = tmp / "img"
    (envr / "micromamba" / "envs" / "sam2").mkdir(parents=True)
    o4 = orch_module(tmp / "vol", env_root=envr)
    runs = tmp / "vol" / "data" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    run = o4.Run.create("s", "v.mp4", runs)
    rc = o4.run_stage(o4.STAGE_BY_KEY["S5"], {"name": "s", "frames": 10}, run, False)
    check("S5(wham) 가 없는 이미지에서 종료 코드 2", rc == o4.EXIT_HUMAN, rc)
    check("완료로 표시하지 않는다", not run.is_done("S5"))

    print("── G4 판정 → 완료 / 정지")
    o5 = orch_module(tmp / "vol")
    c = {"name": "clipA", "rig_dir": "06_rig/lst_wfixc", "character": "lst", "clip_key": "walk_a",
         "roles_path": str(data / "06_rig" / "lst" / "clip_roles.json")}
    gj = o5.stage_outputs("G4", "clipA", c)[0]
    gj.parent.mkdir(parents=True, exist_ok=True)
    run = o5.Run.create("clipA", "v.mp4", runs)
    fail = {"clip": "clipA", "verdict": "FAIL", "edges": {"verdict": "PASS", "reasons": [], "max10": 0, "longest": 0.02},
            "sweep": {"verdict": "FAIL", "reasons": ["발 쓸기 -0.027 > -0.2"], "worst": -0.027},
            "ground": {"verdict": "PASS", "reasons": [], "first": 0.0, "last": 0.0, "sink": -0.008}}
    gj.write_text(json.dumps(fail))
    rc = o5.g4_verdict(c, run, "try1", 1.0, False)
    check("FAIL → 종료 코드 2 · 완료 아님", rc == o5.EXIT_HUMAN and not run.is_done("G4"), rc)
    check("판정 JSON 을 시도별로 남긴다", (run.gates / "g4_clipA_try1.json").exists())
    gj.write_text(json.dumps(dict(fail, verdict="ACCEPTED")))
    rc = o5.g4_verdict(c, run, "try2", 1.0, False)
    check("ACCEPTED → 완료", rc == o5.EXIT_OK and run.is_done("G4"))
    check("앞 시도 판정은 보존", json.loads((run.gates / "g4_clipA_try1.json").read_text())["verdict"] == "FAIL")
    fbx = o5.stage_outputs("CLIPFBX", "clipA", c)[0]
    check("클립 FBX = 07_unity/<캐릭터>/<캐릭터>@<납품 이름>.fbx", fbx == data / "07_unity" / "lst" / "lst@walk_a.fbx", fbx)

    print("── 수용 기록 (accept_clip)")
    roles = {"version": 1, "clips": {"walk_a": {"role": "move", "source": "clipA"}, "idle": {"source": "clipI"}}}
    key, rec, pv = accept_clip.make_entry(roles, "clipA", "sweep", fail, "권장 이동 속도 명기로 납품", "2026-11-02")
    check("source 로 찾아 납품 이름에 적는다", key == "walk_a" and pv == "FAIL")
    check("sweep 수치 = sweep_worst", rec["metrics"] == {"sweep_worst": -0.027}, rec["metrics"])
    check("PASS 인 부분은 받아들이지 않는다", raises(lambda: accept_clip.make_entry(roles, "clipA", "edges", fail, "x", "d")))
    check("판정 JSON 의 클립이 다르면 멈춘다", raises(lambda: accept_clip.make_entry(roles, "clipI", "sweep", fail, "x", "d")))
    roles["clips"]["walk_a"]["accepted"] = [rec]
    check("같은 gate 수용 기록이 이미 있으면 멈춘다", raises(lambda: accept_clip.make_entry(roles, "clipA", "sweep", fail, "x", "d")))
    j = g4_rules.judge("clipA", {"max10": 0, "max05": 0, "longest": 0.02}, {"L": -0.027, "R": -0.037}, roles,
                       {"first": 0.0, "last": 0.0, "sink": -0.008, "f_sink": 0})
    check("기록 뒤 재판정은 ACCEPTED", j["verdict"] == "ACCEPTED", j["verdict"])
    j = g4_rules.judge("clipA", {"max10": 0, "max05": 0, "longest": 0.02}, {"L": -0.002, "R": -0.003}, roles,
                       {"first": 0.0, "last": 0.0, "sink": -0.008, "f_sink": 0})
    check("기록보다 나빠지면 원래 판정", j["verdict"] == "FAIL", j["verdict"])
    g = accept_clip.metrics_for("ground", {"ground": {"first": -0.06, "last": 0.01, "sink": -0.12}})
    check("ground 수치 = g4_rules.ground_metrics", g == g4_rules.ground_metrics({"first": -0.06, "last": 0.01, "sink": -0.12}))

    print("── 동작 트랙 BAKE 계획")
    rig = data / "06_rig" / "lst_wfixc"
    (rig / "motions" / "clipA").mkdir(parents=True, exist_ok=True)
    (rig / "rest_pose.json").write_text(json.dumps({"smpl_height": 1.7234}))
    (data / "06_rig" / "lst" / "clip_roles.json").write_text(json.dumps(
        {"clips": {"walk_a": {"role": "move", "source": "clipA", "bake": {"ground_align": True}},
                   "idle": {"source": "clipI"}}}))
    tp = data / "05_smpl_mesh" / "clipA"
    tp.mkdir(parents=True)
    tp.joinpath("smpl_tpose.obj").write_text("v 0 -0.8 0\nv 0 0.95 0\nf 1 2 1\n")
    pl = bake_clip.plan(data, "lst", "clipA")
    want = subprocess.run(["python3", "-c", "print(1.7234/(max([-0.8,0.95])-min([-0.8,0.95])))"],
                          capture_output=True, text=True).stdout.strip()
    got = pl["bake"][pl["bake"].index("--height-ratio") + 1]
    check("신장비 문자열 = bake_character.sh 식(print)", got == want, f"{got} / {want}")
    check("바닥 정렬은 역할표대로", "--ground-align" in pl["bake"])
    check("고정 npz 가 없으면 변환한다", pl["convert"] is not None)
    (rig / "motions" / "clipA" / "track_select.json").write_text("{}")
    check("track_select.json 이 있으면 고정 npz (변환 없음)", bake_clip.plan(data, "lst", "clipA")["convert"] is None)
    check("bake.ground_align 이 없으면 멈춘다", raises(lambda: bake_clip.plan(data, "lst", "clipI")))
    check("역할표에 없는 클립은 멈춘다", raises(lambda: bake_clip.plan(data, "lst", "nope")))

    print("── run_wham.sh 루트")
    lines = [l for l in (REPO / "scripts" / "run_wham.sh").read_text().splitlines()
             if l.startswith(("DATA=", "ENVR=", "OUT="))]
    for env, want in [({}, "/workspace /workspace /workspace/data/04_wham"),
                      ({"PIPELINE_VOL": "/vol", "PIPELINE_ENV_ROOT": "/workspace"}, "/vol /workspace /vol/data/04_wham")]:
        e = {k: v for k, v in os.environ.items() if k not in ("PIPELINE_VOL", "PIPELINE_ENV_ROOT")}
        e.update(env)
        out = subprocess.run(["bash", "-c", "\n".join(lines) + '\necho "$DATA $ENVR $OUT"'], capture_output=True,
                             text=True, env=e).stdout.strip()
        check(f"run_wham.sh {env or '미설정'} → {want}", out == want, out)

    print("\n" + ("✅ 전체 통과" if OK else "❌ 실패 있음"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
