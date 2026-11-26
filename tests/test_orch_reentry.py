"""오케스트레이터 재진입 시험 (2026-11-26) — 종료 코드 2 뒤의 조치가 명령 하나로 실행되는가.

A. 동작 트랙 --resume 이 BAKE 완료 run 에서 죽지 않는다 (resume_point 에 name 없는 track dict → KeyError: 'name')
B. --from <단계> — 그 단계부터 다시. S5 불합격 안내가 실제로 S2 를 다시 돌리는 명령을 가리킨다.
   이미 완료라 쓰이지 않을 인자(--point · --keyframe · --force-keyframe · --until)는 조용히 무시하지 않고 종료 코드 1.
C. 동작 트랙 다시 굽기 = --resume --from BAKE (이전 animated.blend · 판정 · FBX 는 지우지 않고 보존)
+ handoff 의 맥 구간 안내 줄이 동작 트랙 인자를 빠뜨리지 않는다, --from 은 실행 가능 판정 전에는 아무것도 바꾸지 않는다,
  채택된 리그를 바꾸는 --from 은 멈춘다, 보존본(_from · .superseded_ · _probe · .prev_)을 산출물로 오인하지 않는다.

Blender · 미러 · Pod 없이 돈다(CI 의 RUN). BLENDER 는 /bin/sh 가짜, 단계 실행은 run_stage 를 가짜로 바꿔 흉내 낸다.
"""
import contextlib
import importlib
import io
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

OK = True
CLIP, CH, RIG, KEY = "clipA", "lst", "lst_w", "walk_a"
APP = "appA"
MOTION_ALL = ["G0", "S2", "S5", "5-1", "BAKE", "G4", "CLIPFBX"]
APP_ALL = ["G0", "S2", "S5", "G1a", "S3", "5-1", "5-2", "5-3", "5-4", "5-5", "FBX"]


def check(label, cond, got=""):
    global OK
    OK &= bool(cond)
    print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got)[:300] if got != '' else ''}")


def fake_blender(d, ok=True):
    p = Path(d) / ("blender_ok" if ok else "blender_bad")
    body = 'echo V2UA_BLENDER_OK\nexit 0' if ok else 'echo "libSM.so.6: cannot open" >&2\nexit 127'
    p.write_text(f'#!/bin/sh\n{body}\n')
    p.chmod(0o755)
    return p


def load(vol, blender):
    os.environ["PIPELINE_VOL"] = str(vol)
    os.environ.pop("PIPELINE_ENV_ROOT", None)
    os.environ["BLENDER"] = str(blender)
    import orchestrate
    return importlib.reload(orchestrate)


def touch(p, data=b"x"):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def make_motion(tmp, done, flag=True):
    """동작 트랙 run. done 단계의 마커와 산출물."""
    vol = Path(tmp) / "vol"
    d = vol / "data"
    touch(d / "00_raw" / f"{CLIP}.mp4")
    sam2 = d / "02_sam2" / CLIP
    touch(sam2 / "masks" / "00000.png")
    touch(sam2 / f"{CLIP}_masked.mp4")
    touch(sam2 / "keyframes" / "candidates.json", b'{"topk": []}')
    touch(d / "04_wham" / f"{CLIP}_masked" / "wham_output.pkl")
    touch(d / "04_wham" / f"{CLIP}_masked" / "tracking_results.pth")
    touch(d / "05_smpl_mesh" / CLIP / "smpl_tpose.obj", b"v 0 0 0\nv 0 1.7 0\n")
    cdir = d / "06_rig" / CH
    cdir.mkdir(parents=True)
    (cdir / "character.json").write_text(json.dumps({"version": 2, "character": CH, "rig_dir": f"06_rig/{RIG}"}))
    (cdir / "clip_roles.json").write_text(json.dumps(
        {"clips": {KEY: {"source": CLIP, "role": "move", "bake": {"ground_align": False}}}}))
    m = d / "06_rig" / RIG / "motions" / CLIP
    m.mkdir(parents=True)
    touch(m / "track_select.json", b'{"track": 0}')           # 고정 npz 표지 — 다시 굽기에서 그대로 남아야 한다
    if "BAKE" in done:
        touch(m / "animated.blend", b"old-bake")
    if "G4" in done:
        touch(m / "g4" / f"g4_{KEY}.json", b'{"verdict": "PASS"}')
    if "CLIPFBX" in done:
        touch(d / "07_unity" / CH / f"{CH}@{KEY}.fbx", b"old-fbx")
    o = load(vol, Path(tmp) / "없는_blender")
    (d / "runs").mkdir()
    run = o.Run.create(CLIP, str(d / "00_raw" / f"{CLIP}.mp4"), d / "runs")
    meta = {"frames": 240, "width": 1080, "height": 1920}
    if flag:
        meta["motion_51"] = True
    run.write_meta(meta)
    for k in done:
        run.mark_done(k, [], 0)
    return vol, run


def make_app(tmp, done, adopted=False, seam=False):
    """외형 트랙 run. adopted 면 06_rig/chr/character.json 이 이 샘플의 리그를 rig_dir 로 가리킨다."""
    vol = Path(tmp) / "vol"
    d = vol / "data"
    touch(d / "00_raw" / f"{APP}.mp4")
    sam2 = d / "02_sam2" / APP
    touch(sam2 / "masks" / "00000.png")
    touch(sam2 / f"{APP}_masked.mp4")
    touch(sam2 / "keyframes" / "candidates.json", b'{"topk": [{"frame": 6}]}')
    touch(sam2 / "keyframes" / "key1_f00006.png")
    touch(d / "04_wham" / f"{APP}_masked" / "wham_output.pkl")
    touch(d / "03_trellis2" / APP / f"{APP}.glb")
    touch(d / "03_trellis2" / f"{APP}_probe1" / f"{APP}.glb")   # 기존 관례의 보존본 — 산출물로 보면 안 된다
    touch(d / "05_smpl_mesh" / APP / "smpl_frame6.obj")
    rig = d / "06_rig" / APP
    for f in ("aligned.blend", "aligned_params.json", "rigged.blend", "rigged_params.json",
              "transferred.blend", "transferred_params.json", "animated.blend"):
        touch(rig / f, b"x")
    # dry-run 의 G2r 게이트 명령이 읽는 값 (gate_command 5-4)
    touch(rig / "rigged_params.json", b'{"joint_dist": 0.025}')
    touch(rig / "transferred_params.json", b'{"fallback_pct": 0.3, "unassigned_pct": 0.0}')
    touch(rig / "aligned_params.json", b'{}')
    touch(rig / "animated.blend.prev_20261101_000000")
    touch(d / "07_unity" / APP / f"{APP}_wham.fbx")
    (d / "06_rig").mkdir(exist_ok=True)
    if adopted:
        touch(d / "06_rig" / "chr" / "character.json",
              json.dumps({"version": 1, "character": "chr", "rig_dir": f"06_rig/{APP}"}).encode())
    if seam:
        touch(d / "06_rig" / "chs" / "character.json", json.dumps(
            {"version": 2, "character": "chs", "rig_dir": "06_rig/other",
             "rig_build": {"source_sample": APP, "seam_smooth": [{"label": "crotch", "pairs": ["L_Hip:R_Hip"],
                                                                  "rings": 10, "iters": 40, "lam": 0.5}]}}).encode())
        touch(rig / "transferred_5-4b.blend")
        touch(rig / "transferred_5-4b_chain.json")
    o = load(vol, Path(tmp) / "없는_blender")
    (d / "runs").mkdir()
    run = o.Run.create(APP, str(d / "00_raw" / f"{APP}.mp4"), d / "runs")
    run.write_meta({"frames": 192, "width": 1080, "height": 1920, "frame": "6",
                    "keyframe": str(sam2 / "keyframes" / "key1_f00006.png")})
    for k in done:
        run.mark_done(k, [], 0)
    return vol, run


def fake_runner(log):
    """run_stage 대역 — 실행 순서를 기록하고 선언 산출물을 만든 뒤 마커를 남긴다."""
    def f(s, c, run, dry):
        log.append(s["key"])
        if not dry:
            o = sys.modules["orchestrate"]
            for p in o.stage_outputs(s["key"], c["name"], c):
                p = Path(p)
                if p.suffix:
                    touch(p, b"new")
                else:
                    touch(p / "new")
            run.mark_done(s["key"], [], 0)
        return 0
    return f


def orch(vol, blender, *args, motion=True, name=CLIP, runner=None):
    o = load(vol, blender)
    if runner is not None:
        o.run_stage = runner
    buf = io.StringIO()
    argv = sys.argv
    pre = ["--motion", "--character", CH] if motion else []
    sys.argv = ["orchestrate.py", *pre, "--name", name, *args]
    try:
        with contextlib.redirect_stdout(buf):
            rc = o.main()
    except SystemExit as e:
        rc = f"SystemExit {e.code}"
    except BaseException as e:
        rc = f"예외 {type(e).__name__}: {e}"
    finally:
        sys.argv = argv
    return rc, buf.getvalue()


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def stage_lines(out, keys):
    return [l.split("]")[0][1:] for l in out.splitlines() if l.startswith("[") and "]" in l and l[1:l.index("]")] in keys]


def main():
    global OK
    ok_bl = None
    with tempfile.TemporaryDirectory() as bt:
        ok_bl = fake_blender(bt, ok=True)
        bad_bl = fake_blender(bt, ok=False)

        print("A. 동작 트랙 — BAKE 완료 run 을 이어받기")
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, ["G0", "S2", "S5", "5-1", "BAKE"])
            rc, out = orch(vol, ok_bl, "--resume", "--dry-run")
            check("① --resume --dry-run 이 예외 없이 끝난다", rc == 0, rc if rc != 0 else "")
            check("① 계획이 G4 부터", stage_lines(out, MOTION_ALL)[:1] == ["G4"], stage_lines(out, MOTION_ALL))
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, ["G0", "S2", "S5", "5-1", "BAKE"])
            log = []
            rc, out = orch(vol, ok_bl, "--resume", runner=fake_runner(log))
            check("② 실행 — G4 → CLIPFBX 만 돈다", rc == 0 and log == ["G4", "CLIPFBX"], (rc, log))
            check("② G4 · CLIPFBX 마커", run.is_done("G4") and run.is_done("CLIPFBX"))

        print("H. handoff — 맥 구간에서 Pod 단계를 만났을 때의 안내")
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, ["G0"])
            rc, out = orch(vol, ok_bl, "--resume", "--section", "mac", "--dry-run")
            line = [l for l in out.splitlines() if "orchestrate.py" in l and "--resume" in l]
            check("③ 안내 명령에 --motion --character 가 있다", rc == 2 and line and all("--motion --character lst" in l for l in line),
                  (rc, line))

        print("B. S5 불합격 안내 · --from S2 · 쓰이지 않을 인자")
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, ["G0", "S2"])
            o = load(vol, ok_bl)
            c = dict(name=CLIP, track="motion", character=CH, video=str(vol / "data" / "00_raw" / f"{CLIP}.mp4"))
            (run.root / "attempts.json").write_text(json.dumps([{"stage": "S5", "n": 1, "verdict": "FAIL"}]))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                o.exhausted("S5", c, run)
            cmds = [l.strip() for l in buf.getvalue().splitlines() if "orchestrate.py" in l]
            check("④ S5 안내가 --from S2 --point 를 가리킨다", cmds and "--from S2" in cmds[0] and "--point" in cmds[0], cmds)
            if cmds:
                parts = shlex.split(cmds[0].replace("<x>,<y>[;<x>,<y>...]", "100,200"))
                argv = sys.argv
                sys.argv = ["orchestrate.py"] + parts[parts.index("scripts/orchestrate.py") + 1 if "scripts/orchestrate.py" in parts else parts.index("orchestrate.py") + 1:]
                try:
                    a = o.parse_args()
                    good = getattr(a, "from_stage", None) == "S2" and a.point == "100,200" and a.motion
                except SystemExit:
                    good = False
                finally:
                    sys.argv = argv
                check("④ 그 명령이 인자 파싱을 통과 (--from S2 · --point · --motion)", good)
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, ["G0", "S2"])
            before = snapshot(vol)
            rc, out = orch(vol, ok_bl, "--resume", "--point", "100,200", "--dry-run")
            check("⑤ S2 완료 run 에 --point 만 → 종료 코드 1 + --from S2 안내", rc == 1 and "--from S2" in out, (rc, out[-300:]))
            check("⑤ 아무것도 바뀌지 않는다", snapshot(vol) == before)
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, MOTION_ALL)
            before = snapshot(vol)
            rc, out = orch(vol, ok_bl, "--resume", "--from", "S2", "--dry-run")
            check("⑥ --from S2 --dry-run 종료 코드 0", rc == 0, (rc, out[-400:]))
            check("⑥ dry-run 은 run · 산출물을 바이트 단위로 바꾸지 않는다", snapshot(vol) == before)
            check("⑥ 무효화 목록 · 옮길 산출물 · 다시 돌 순서를 출력", "무효화" in out and "_from" in out and "S2 → S5 → 5-1 → BAKE → G4 → CLIPFBX" in out,
                  out[-600:])
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, MOTION_ALL)
            d = vol / "data"
            log = []
            rc, out = orch(vol, ok_bl, "--resume", "--from", "S2", "--point", "100,200", runner=fake_runner(log))
            check("⑦ --from S2 실행 — S2 부터 끝까지", rc == 0 and log == ["S2", "S5", "5-1", "BAKE", "G4", "CLIPFBX"], (rc, log))
            sup = sorted(p.name.split(".done")[0] for p in run.done.glob("*.done.superseded_*"))
            check("⑦ S2 이후 마커는 지우지 않고 .superseded_ 로", sup == sorted(["S2", "S5", "5-1", "BAKE", "G4", "CLIPFBX"]), sup)
            check("⑦ G0 마커는 그대로", run.is_done("G0") and not list(run.done.glob("G0.done.superseded_*")))
            moved = [p.name for p in (d / "02_sam2" / CLIP).iterdir() if "_from" in p.name] + \
                    [p.name for p in (d / "04_wham").iterdir() if "_from" in p.name]
            check("⑦ S2 산출물 · S5 폴더가 _from 으로 보존", any(n.startswith("masks_from") for n in moved)
                  and any(n.startswith(f"{CLIP}_masked_from") for n in moved), moved)
            meta = run.meta()
            fr = (meta.get("from") or [{}])[-1]
            check("⑦ run.json 에 FROM 기록 (완료 표시 · 옮긴 목록)", fr.get("stage") == "S2" and fr.get("status") == "done" and fr.get("moves"), fr)
            att = json.loads((run.root / "attempts.json").read_text())
            check("⑦ attempts.json 에 FROM 기록", any(str(h.get("verdict", "")).startswith("FROM") for h in att))

        print("C. 다시 굽기 — --resume --from BAKE")
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, MOTION_ALL)
            d = vol / "data"
            m = d / "06_rig" / RIG / "motions" / CLIP
            log = []
            rc, out = orch(vol, ok_bl, "--resume", "--from", "BAKE", runner=fake_runner(log))
            check("⑧ BAKE → G4 → CLIPFBX 만 돈다", rc == 0 and log == ["BAKE", "G4", "CLIPFBX"], (rc, log))
            old = [p for p in m.iterdir() if p.name.startswith("animated.blend_from")]
            check("⑧ 이전 animated.blend 보존 (내용 그대로)", len(old) == 1 and old[0].read_bytes() == b"old-bake", [p.name for p in m.iterdir()])
            check("⑧ 이전 판정 · FBX 보존", any(p.name.startswith(f"g4_{KEY}.json_from") for p in (m / "g4").iterdir())
                  and any(p.name.startswith(f"{CH}@{KEY}.fbx_from") for p in (d / "07_unity" / CH).iterdir()))
            check("⑧ 고정 npz 표지(track_select.json)는 그대로", (m / "track_select.json").read_bytes() == b'{"track": 0}')
            check("⑧ BAKE 앞 마커는 그대로", all(run.is_done(k) for k in ("G0", "S2", "S5", "5-1")))
            check("⑧ 실행 출력에 옮긴 경로 · 크기", "animated.blend_from" in out and "B)" in out, out[-500:])
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, MOTION_ALL)
            rc, out = orch(vol, ok_bl, "--resume", "--from", "S3", "--dry-run")
            check("⑨ 동작 트랙에 없는 단계(S3) → 종료 코드 1", rc == 1, (rc, out[-200:]))
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, ["G0", "S2", "S5"], flag=False)         # 5-1 이전의 예전 run
            rc, out = orch(vol, ok_bl, "--resume", "--from", "5-1", "--dry-run")
            check("⑨ 예전 run(목록에 5-1 없음)에 --from 5-1 → 종료 코드 1", rc == 1, (rc, out[-200:]))
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_app(tmp, APP_ALL)
            rc, out = orch(vol, ok_bl, "--resume", "--from", "5-2", "--dry-run", motion=False, name=APP)
            check("⑩ 외형 --from 5-2 → 5-2 → 5-3 → 5-4 → 5-5 → FBX", rc == 0 and "5-2 → 5-3 → 5-4 → 5-5 → FBX" in out, (rc, out[-400:]))
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_app(tmp, APP_ALL[:9] + ["5-4b", "5-5", "FBX"], seam=True)
            rc, out = orch(vol, ok_bl, "--resume", "--from", "5-2", "--dry-run", motion=False, name=APP)
            check("⑩ 5-4b 설정이 있으면 무효화 범위에 5-4b 포함", rc == 0 and "5-4 → 5-4b → 5-5" in out, (rc, out[-400:]))

        print("P. --from 은 실행 가능 판정을 먼저 — 통과 전에는 아무것도 바꾸지 않는다")
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, MOTION_ALL)
            (vol / "micromamba" / "envs").mkdir(parents=True)      # 환경 폴더는 있는데 sam2 가 없다
            before = snapshot(vol)
            rc, out = orch(vol, ok_bl, "--resume", "--from", "S2")
            check("⑪ 환경 없는 기계에서 --from S2 → 종료 코드 2", rc == 2, (rc, out[-300:]))
            check("⑪ run 폴더 · 산출물 바이트 불변", snapshot(vol) == before)
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, MOTION_ALL)
            before = snapshot(vol)
            rc, out = orch(vol, bad_bl, "--resume", "--from", "BAKE")
            check("⑪ Blender 구간을 못 도는 기계에서 --from BAKE → 종료 코드 2", rc == 2, (rc, out[-300:]))
            check("⑪ run 폴더 · 산출물 바이트 불변", snapshot(vol) == before)

        print("R. 채택된 리그를 바꾸는 --from")
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_app(tmp, APP_ALL, adopted=True)
            before = snapshot(vol)
            rc, out = orch(vol, ok_bl, "--resume", "--from", "5-2", motion=False, name=APP)
            check("⑫ character.json 이 가리키는 리그 → 종료 코드 1 + 캐릭터 이름", rc == 1 and "chr" in out, (rc, out[-300:]))
            check("⑫ 바이트 불변", snapshot(vol) == before)
            rc, out = orch(vol, ok_bl, "--resume", "--from", "5-5", "--dry-run", motion=False, name=APP)
            check("⑫ 리그를 바꾸지 않는 --from 5-5 는 막지 않는다", rc == 0, (rc, out[-300:]))

        print("N. 보존본을 산출물로 오인하지 않는다")
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_app(tmp, APP_ALL)
            o = load(vol, ok_bl)
            start, skipped, problem = o.resume_point(run, APP, None, o.stages_for({}), {})
            check("⑬ _probe1 · .prev_ 가 있어도 완료 run 은 그대로 완료", start is None and problem is None, (start, problem))
            log = []
            rc, out = orch(vol, ok_bl, "--resume", "--from", "S3", runner=fake_runner(log), motion=False, name=APP)
            d = vol / "data"
            names = [p.name for p in (d / "03_trellis2").iterdir()]
            check("⑬ S3 폴더는 _from 으로, 기존 _probe1 은 그대로", any(n.startswith(f"{APP}_from") for n in names) and f"{APP}_probe1" in names, names)
            o = load(vol, ok_bl)
            rl = [str(p) for p in o.retrieve_list(type("A", (), {"name": APP})(), {}, run)]
            check("⑬ 회수 목록에 보존본(_from · _probe)이 없다", not any("_from" in p or "_probe" in p for p in rl), rl)
            outs = [str(p) for k in APP_ALL for p in o.stage_outputs(k, APP, {})]
            check("⑬ stage_outputs 는 보존본 이름을 가리키지 않는다", not any("_from" in p or "superseded" in p or "_probe" in p or ".prev_" in p for p in outs))

        print("U. 쓰이지 않을 인자는 조용히 무시하지 않는다")
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_app(tmp, ["G0", "S2", "S5", "G1a"])
            rc, out = orch(vol, ok_bl, "--resume", "--force-keyframe", "--dry-run", motion=False, name=APP)
            check("⑭ G1a 완료 run 에 --force-keyframe → 1 + --from G1a", rc == 1 and "--from G1a" in out, (rc, out[-200:]))
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_app(tmp, APP_ALL[:6])
            kf = str(vol / "data" / "02_sam2" / APP / "keyframes" / "key1_f00006.png")
            rc, out = orch(vol, ok_bl, "--resume", "--keyframe", kf, "--dry-run", motion=False, name=APP)
            check("⑭ S3 완료 run 에 --keyframe → 1 + --from S3", rc == 1 and "--from S3" in out, (rc, out[-200:]))
            rc, out = orch(vol, ok_bl, "--resume", "--from", "S3", "--keyframe", kf, "--dry-run", motion=False, name=APP)
            check("⑭ --from S3 --keyframe 는 받는다", rc == 0, (rc, out[-300:]))
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_motion(tmp, ["G0"])
            rc, out = orch(vol, ok_bl, "--resume", "--keyframe", "x_f00001.png", "--dry-run")
            check("⑭ 동작 트랙에 --keyframe → 1", rc == 1, (rc, out[-200:]))
            rc, out = orch(vol, ok_bl, "--resume", "--until", "G0", "--dry-run")
            check("⑭ 이미 완료한 단계로 --until → 1", rc == 1, (rc, out[-200:]))
            rc, out = orch(vol, ok_bl, "--resume", "--until", "S3", "--dry-run")
            check("⑭ 이 트랙에 없는 단계로 --until → 1", rc == 1, (rc, out[-200:]))
            rc, out = orch(vol, ok_bl, "--resume", "--until", "S5", "--dry-run")
            check("⑭ 남은 단계로 --until 은 그대로 받는다", rc == 0, (rc, out[-200:]))

    print("\n" + ("✅ 전체 통과" if OK else "❌ 실패 있음"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
