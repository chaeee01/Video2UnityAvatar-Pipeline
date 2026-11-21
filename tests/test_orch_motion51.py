"""동작 트랙 5-1 시험 (2026-11-21) — 클립 영상 하나 → 클립 FBX 를 명령 하나로 돌리려면 BAKE 의 신장비에 쓰는
클립 T포즈 메쉬(05_smpl_mesh/<클립>/smpl_tpose.obj)를 Pod 구간에서 만들어야 한다.

- 새 run 은 G0 → S2 → S5 → 5-1 → BAKE → G4 → CLIPFBX, 5-1 은 10/26 생산 큐와 같은 호출(--frame 0 --name <클립>)
- 이 변경 전에 Pod 구간을 마친 run(run.json 에 motion_51 표지 없음 · S5 완료)은 예전 목록 그대로 — 맥에서
  --resume 할 때 5-1 이 "미완료" 로 잡히지 않는다 (호환)
- dry-run 은 run 폴더를 바꾸지 않는다

Blender · 미러 · Pod 없이 돈다(CI 의 RUN). BLENDER 에는 /bin/sh 로 만든 가짜를 건다(test_orch_boundary 와 같은 방식).
"""
import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

OK = True
CLIP = "clipA"


def check(label, cond, got=""):
    global OK
    OK &= bool(cond)
    print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")


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


def make_vol(tmp, done, flag, tpose=False, with_run=True):
    """동작 트랙 run 하나. done 단계의 마커와 산출물 자리, flag 면 run.json 에 motion_51."""
    vol = Path(tmp) / "vol"
    d = vol / "data"
    sam2 = d / "02_sam2" / CLIP
    (sam2 / "masks").mkdir(parents=True)
    (sam2 / "masks" / "00000.png").write_bytes(b"x")
    (sam2 / f"{CLIP}_masked.mp4").write_bytes(b"x")
    (sam2 / "keyframes").mkdir()
    (sam2 / "keyframes" / "candidates.json").write_text('{"topk": []}')
    (d / "04_wham" / f"{CLIP}_masked").mkdir(parents=True)
    (d / "04_wham" / f"{CLIP}_masked" / "wham_output.pkl").write_bytes(b"x")
    if tpose:
        (d / "05_smpl_mesh" / CLIP).mkdir(parents=True)
        (d / "05_smpl_mesh" / CLIP / "smpl_tpose.obj").write_text("v 0 0 0\nv 0 1.7 0\n")
    cdir = d / "06_rig" / "lst"
    cdir.mkdir(parents=True)
    (cdir / "character.json").write_text(json.dumps({"version": 2, "character": "lst", "rig_dir": "06_rig/lst_w"}))
    (cdir / "clip_roles.json").write_text(json.dumps(
        {"clips": {"walk_a": {"source": CLIP, "role": "move", "bake": {"ground_align": False}}}}))
    (d / "06_rig" / "lst_w" / "motions").mkdir(parents=True)
    o = load(vol, Path(tmp) / "없는_blender")
    (d / "runs").mkdir()
    if not with_run:
        return vol, None
    run = o.Run.create(CLIP, str(d / "00_raw" / f"{CLIP}.mp4"), d / "runs")
    meta = {"frames": 240, "width": 1080, "height": 1920}
    if flag:
        meta["motion_51"] = True
    run.write_meta(meta)
    for k in done:
        run.mark_done(k, [], 0)
    return vol, run


def orch(vol, blender, *args, patch=None):
    o = load(vol, blender)
    if patch:
        patch(o)
    buf = io.StringIO()
    argv = sys.argv
    sys.argv = ["orchestrate.py", "--motion", "--character", "lst", "--name", CLIP, *args]
    try:
        with contextlib.redirect_stdout(buf):
            rc = o.main()
    except BaseException as e:
        rc = f"예외 {type(e).__name__}: {e}"
    finally:
        sys.argv = argv
    return rc, buf.getvalue()


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def stage_lines(out):
    return [l.split("]")[0][1:] for l in out.splitlines() if l.startswith("[") and "]" in l
            and l[1:l.index("]")] in ("G0", "S2", "S5", "5-1", "BAKE", "G4", "CLIPFBX")]


def main():
    print("── 새 run: --dry-run 계획에 5-1 이 S5 와 BAKE 사이에 보인다")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp, done=("G0",), flag=True)
        b = fake_blender(tmp)
        before = snapshot(run.root)
        rc, out = orch(vol, b, "--resume", "--dry-run")
        check("종료 코드 0", rc == 0, rc)
        check("단계 순서 S2 → S5 → 5-1 → BAKE → G4 → CLIPFBX", stage_lines(out) == ["S2", "S5", "5-1", "BAKE", "G4", "CLIPFBX"],
              stage_lines(out))
        line = next((l for l in out.splitlines() if "generate_smpl_mesh.py" in l), "")
        check("5-1 = wham 환경 · 10/26 생산 큐와 같은 인자 (--frame 0 --name <클립>)",
              " run -n wham " in line and f"wham_output.pkl --frame 0 --name {CLIP}" in line, line.strip())
        check("  데이터 루트가 /workspace 가 아니면 --out", f"--out {vol / 'data' / '05_smpl_mesh'}" in line)
        check("구간 경계는 5-1 뒤 (판정 후 [계속] → BAKE)",
              out.index("[5-1]") < out.index("Blender 구간 판정: 가능") < out.index("[BAKE]"))
        check("dry-run 은 run 폴더를 바꾸지 않는다", snapshot(run.root) == before)

        o = load(vol, b)
        ctx = {"name": CLIP, "track": "motion"}
        check("5-1 명령은 키프레임(frame) 없이 조립된다", "--frame" in o.stage_command("5-1", ctx)
              and o.stage_command("5-1", ctx)[o.stage_command("5-1", ctx).index("--frame") + 1] == "0")
        check("동작 트랙 5-1 의 필수 산출물 = smpl_tpose.obj",
              o.stage_outputs("5-1", CLIP, ctx) == [vol / "data" / "05_smpl_mesh" / CLIP / "smpl_tpose.obj"])
        check("외형 트랙 5-1 산출물은 그대로 (폴더)",
              o.stage_outputs("5-1", CLIP, {"name": CLIP}) == [vol / "data" / "05_smpl_mesh" / CLIP])

    print("── 새 run: Blender 를 못 띄우면 5-1 뒤 경계에서 인계 — 회수 목록에 05_smpl_mesh")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp, done=("G0",), flag=True)
        rc, out = orch(vol, fake_blender(tmp, ok=False), "--resume", "--dry-run")
        check("종료 코드 2, 5-1 까지 돌고 BAKE 는 돌지 않는다(dry)", rc == 2 and stage_lines(out) == ["S2", "S5", "5-1"]
              and "[인계] pod 구간 완료. 다음 [BAKE]" in out, (rc, stage_lines(out)))
        check("회수 목록 02_sam2 · 04_wham · 05_smpl_mesh",
              all(str(vol / "data" / p) in out for p in (f"02_sam2/{CLIP}", f"04_wham/{CLIP}_masked", f"05_smpl_mesh/{CLIP}")))

    print("── 새 run: 맥에서 이어받기 — 5-1 완료 + T포즈 메쉬 있음 → BAKE 부터")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp, done=("G0", "S2", "S5", "5-1"), flag=True, tpose=True)
        rc, out = orch(vol, fake_blender(tmp), "--resume", "--dry-run")
        check("건너뜀 G0, S2, S5, 5-1 → BAKE", rc == 0 and "건너뜀 (완료됨): G0, S2, S5, 5-1" in out
              and stage_lines(out) == ["BAKE", "G4", "CLIPFBX"], (rc, stage_lines(out)))

    print("── 새 run: 5-1 마커는 있는데 T포즈 메쉬가 없으면 멈춘다 (설계 5절 규칙 4)")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp, done=("G0", "S2", "S5", "5-1"), flag=True, tpose=False)
        rc, out = orch(vol, fake_blender(tmp), "--resume", "--dry-run")
        check("종료 코드 2 · [정지] 5-1 · 없음: smpl_tpose.obj", rc == 2 and "[정지] 5-1: 마커는 있는데 산출물이 없다" in out
              and "smpl_tpose.obj" in out, rc)

    print("── 예전 run (표지 없음 · S5 완료): 5-1 을 건너뛰고 예전 목록 그대로")
    for tpose in (True, False):
        with tempfile.TemporaryDirectory() as tmp:
            vol, run = make_vol(tmp, done=("G0", "S2", "S5"), flag=False, tpose=tpose)
            before = snapshot(run.root)
            rc, out = orch(vol, fake_blender(tmp), "--resume", "--dry-run")
            tag = "T포즈 메쉬 있음" if tpose else "T포즈 메쉬 없음(fallback_height 경로)"
            check(f"[{tag}] 종료 코드 0, 단계 BAKE → G4 → CLIPFBX (5-1 없음)",
                  rc == 0 and stage_lines(out) == ["BAKE", "G4", "CLIPFBX"], (rc, stage_lines(out)))
            check("  건너뜀 G0, S2, S5 · 다음 단계 BAKE(mac) — 예전 출력과 같은 줄",
                  "건너뜀 (완료됨): G0, S2, S5\n" in out and "다음 단계: [BAKE]" in out)
            check("  안내 한 줄 (조용히 지나가지 않는다)", "5-1: 이 run 은 동작 트랙에 5-1 이 들어가기 전" in out)
            check("  generate_smpl_mesh 를 부르지 않는다", "generate_smpl_mesh.py" not in out)
            check("  dry-run 은 run 폴더를 바꾸지 않는다", snapshot(run.root) == before)

    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp, done=("G0", "S2", "S5"), flag=False, tpose=True)
        rc, out = orch(vol, Path(tmp) / "없는_blender", "--resume")
        meta = json.loads((run.root / "run.json").read_text())
        check("예전 run 을 실제로 이어받아도(Blender 없음 → 정지) 다음 단계는 BAKE, 표지를 쓰지 않는다",
              rc == 2 and "[정지] 다음 [BAKE]" in out and "motion_51" not in meta, (rc, meta.get("motion_51")))

    print("── 표지 없음 · S5 전 run (dry-run 이 남긴 빈 run 등): 새 목록으로 이어 돌고 표지를 남긴다")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp, done=("G0",), flag=False)
        rc, out = orch(vol, fake_blender(tmp), "--resume", "--dry-run")
        check("dry-run: 5-1 이 계획에 있다", rc == 0 and "5-1" in stage_lines(out), stage_lines(out))
        check("  dry-run 은 표지를 쓰지 않는다", "motion_51" not in json.loads((run.root / "run.json").read_text()))
        rc, out = orch(vol, fake_blender(tmp), "--resume", "--until", "G0")
        check("실제 실행이면 표지를 남긴다", json.loads((run.root / "run.json").read_text()).get("motion_51") is True, rc)

    print("── 새로 만든 run 은 표지를 남긴다 (실제 실행)")
    with tempfile.TemporaryDirectory() as tmp:
        vol, _ = make_vol(tmp, done=(), flag=False, with_run=False)
        rc, out = orch(vol, fake_blender(tmp), "--video", str(Path(tmp) / "없는_영상.mp4"))
        runs = sorted((vol / "data" / "runs").glob(f"run_{CLIP}_*"))
        meta = json.loads((runs[-1] / "run.json").read_text())
        check("G0 에서 실패해도(입력 없음) 새 run.json 에 motion_51", len(runs) == 1 and meta.get("motion_51") is True
              and rc == 1, (rc, len(runs), meta.get("motion_51")))

    print("── 외형 트랙은 바뀌지 않는다")
    with tempfile.TemporaryDirectory() as tmp:
        o = load(Path(tmp), fake_blender(tmp))
        check("외형 트랙 단계 목록 = STAGES", o.stages_for({}) == o.STAGES)
        c = o.stage_command("5-1", {"name": "s", "frame": 138})
        check("외형 트랙 5-1 은 키프레임 번호", c[c.index("--frame") + 1] == "138", c)

    print("\n" + ("전부 통과" if OK else "실패 있음"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
