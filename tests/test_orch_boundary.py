"""구간 경계 판정 시험 (2026-11-21) — pod → mac 경계에서 "이 기계가 Blender 구간을 돌 수 있는가" 로 이어 돌거나 멈춘다.

Blender · 미러 · Pod 없이 돈다(CI 의 RUN). BLENDER 에는 /bin/sh 로 만든 가짜를 걸어 표지 출력 · 127 종료 ·
표지 없는 0 종료 · 부재를 흉내 내고, 오케스트레이터 main() 을 같은 프로세스에서 부른다.
실제 Blender 로 하는 관통은 이미지 반영 뒤 Pod 에서 한 번으로 묶는다.
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
POD_DONE = ("G0", "S2", "S5", "G1a", "S3")       # 5-1 이 남은 run — 경계 직전


def check(label, cond, got=""):
    global OK
    OK &= bool(cond)
    print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")


def fake_blender(d, kind):
    """가짜 Blender. 호출될 때마다 calls 파일에 한 줄 쓴다 (판정이 몇 번 띄우는지 센다)."""
    p = Path(d) / f"blender_{kind}"
    body = {
        "ok": 'echo V2UA_BLENDER_OK\necho "Blender 4.5.12 LTS"\nexit 0',
        "lib127": 'echo "Blender: error while loading shared libraries: libSM.so.6: '
                  'cannot open shared object file: No such file or directory" >&2\nexit 127',
        "nomark": 'echo "Traceback (most recent call last): ModuleNotFoundError: io_scene_fbx" >&2\nexit 0',
    }[kind]
    p.write_text(f'#!/bin/sh\necho "$@" >> "{d}/calls"\n{body}\n')
    p.chmod(0o755)
    return p


def make_vol(tmp, done=POD_DONE, name="smp"):
    """외형 트랙 run 하나. done 단계의 마커와 산출물 자리를 깐다."""
    vol = Path(tmp) / "vol"
    d = vol / "data"
    sam2 = d / "02_sam2" / name
    (sam2 / "masks").mkdir(parents=True)
    (sam2 / "masks" / "00000.png").write_bytes(b"x")
    (sam2 / f"{name}_masked.mp4").write_bytes(b"x")
    (sam2 / "keyframes").mkdir()
    (sam2 / "keyframes" / "candidates.json").write_text('{"topk": []}')
    (d / "04_wham" / f"{name}_masked").mkdir(parents=True)
    (d / "04_wham" / f"{name}_masked" / "wham_output.pkl").write_bytes(b"x")
    (d / "03_trellis2" / name).mkdir(parents=True)
    (d / "03_trellis2" / name / f"{name}.glb").write_bytes(b"x")
    if "5-1" in done:
        (d / "05_smpl_mesh" / name).mkdir(parents=True)
        (d / "05_smpl_mesh" / name / "smpl_frame6.obj").write_bytes(b"x")
    (d / "06_rig").mkdir(parents=True)
    o = load(vol)
    (d / "runs").mkdir()
    run = o.Run.create(name, str(sam2 / f"{name}_masked.mp4"), d / "runs")
    run.write_meta({"frames": 120, "frame": "6", "keyframe": str(sam2 / "keyframes" / "key1_f00006.png")})
    for k in done:
        run.mark_done(k, [], 0)
    return vol, run


def load(vol, blender=None):
    os.environ["PIPELINE_VOL"] = str(vol)
    os.environ.pop("PIPELINE_ENV_ROOT", None)
    if blender is None:
        os.environ.pop("BLENDER", None)
    else:
        os.environ["BLENDER"] = str(blender)
    import orchestrate
    return importlib.reload(orchestrate)


def orch(vol, blender, *args, name="smp", patch=None):
    """main() 을 같은 프로세스에서 부른다. (종료 코드, 출력)."""
    o = load(vol, blender)
    if patch:
        patch(o)
    buf = io.StringIO()
    argv = sys.argv
    sys.argv = ["orchestrate.py", "--name", name, *args]
    try:
        with contextlib.redirect_stdout(buf):
            rc = o.main()
    except BaseException as e:            # traceback 이 나면 시험이 그것을 잡아 실패로 센다
        rc = f"예외 {type(e).__name__}: {e}"
    finally:
        sys.argv = argv
    return rc, buf.getvalue()


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def calls(tmp):
    f = Path(tmp) / "calls"
    return len(f.read_text().splitlines()) if f.exists() else 0


def main():
    print("── pod → mac 경계: 판정 불가면 멈춘다 (종료 코드 2, traceback 없음)")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp)
        rc, out = orch(vol, Path(tmp) / "없는_blender", "--resume", "--dry-run")
        check("BLENDER 부재 → 종료 코드 2", rc == 2, rc)
        check("사유: 실행 파일이 없다 + 경로", "Blender 실행 파일이 없다" in out and "없는_blender" in out)
        check("5-1 은 돌고(dry) 5-2 는 돌지 않는다", "generate_smpl_mesh.py" in out and "align_smpl_to_trellis.py" not in out)
        check("두 갈래 안내 — 여기서(BLENDER=) / 회수해서(목록)",
              "BLENDER=<경로>" in out and "다른 기계(맥북)" in out and "03_trellis2" in out)
        check("traceback 없음", "Traceback" not in out)

        rc, out = orch(vol, None, "--resume", "--dry-run")
        check("BLENDER 미지정 → 기본 경로를 보고 사유에 '미지정' 표기",
              "BLENDER 미지정" in out or "Blender 구간 판정: 가능" in out)

        b = fake_blender(tmp, "lib127")
        rc, out = orch(vol, b, "--resume", "--dry-run")
        check("기동 127(libSM) → 종료 코드 2, 사유에 종료 코드와 마지막 줄",
              rc == 2 and "종료 코드 127" in out and "libSM.so.6" in out, rc)

        b = fake_blender(tmp, "nomark")
        rc, out = orch(vol, b, "--resume", "--dry-run")
        check("종료 코드 0 이어도 표지가 없으면 불가 (Blender 는 스크립트가 죽어도 0)", rc == 2 and "기동 실패" in out, rc)

    print("── 판정 가능하면 경계를 넘어 이어 돈다")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp)
        b = fake_blender(tmp, "ok")
        before = snapshot(run.root)
        rc, out = orch(vol, b, "--resume", "--dry-run")
        check("종료 코드 0, 모든 단계 완료", rc == 0 and "모든 단계 완료" in out, rc)
        check("[계속] 출력 후 5-2 명령이 가짜 Blender 로 조립된다",
              "[계속]" in out and f"{b} --background --python" in out and "align_smpl_to_trellis.py" in out)
        check("회수 안내는 나오지 않는다", "다른 기계(맥북)" not in out and "[인계]" not in out)
        check("판정 Blender 는 한 번만 띄운다", calls(tmp) == 1, calls(tmp))
        check("dry-run 은 run 폴더를 바꾸지 않는다", snapshot(run.root) == before)

        rc, out = orch(vol, b, "--resume", "--dry-run", "--section", "pod")
        check("--section pod → 판정 없이 경계에서 종료 코드 2", rc == 2 and "Blender 구간 판정:" not in out, rc)
        check("  사유는 --section, 안내는 --section 없이 이어받기",
              "--section pod 로 구간을 지정했다" in out and "--section 없이" in out and "BLENDER=<경로>" not in out)

        rc, out = orch(vol, b, "--resume", "--dry-run", "--until", "5-1")
        check("--until 5-1 → 경계 전에 멈춘다 (판정 안 함)", rc == 0 and "Blender 구간 판정:" not in out, rc)

        miss = lambda o: setattr(o, "MAC_PY_MODULES", ("numpy", "v2ua_없는_모듈"))
        rc, out = orch(vol, b, "--resume", "--dry-run", patch=miss)
        check("이 인터프리터에 모듈이 없으면 종료 코드 2, 사유에 모듈과 인터프리터",
              rc == 2 and "v2ua_없는_모듈 없음" in out and sys.executable in out, rc)

    print("── mac 구간에서 시작 (--resume)")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp, done=POD_DONE + ("5-1",))
        b = fake_blender(tmp, "ok")
        rc, out = orch(vol, b, "--resume", "--dry-run")
        check("판정 가능 → 5-2 부터 돈다 (dry)", rc == 0 and "Blender 구간 판정: 가능" in out and "[5-2]" in out, rc)
        before_attempts = (run.root / "attempts.json").read_text()
        rc, out = orch(vol, Path(tmp) / "없는_blender", "--resume")
        check("판정 불가 → 단계를 돌지 않고 [정지] + 종료 코드 2", rc == 2 and "[정지] 다음 [5-2]" in out
              and not run.is_done("5-2"), rc)
        check("  traceback 없음, BLENDER= 안내", "Traceback" not in out and "BLENDER=<경로>" in out)
        att = json.loads((run.root / "attempts.json").read_text())
        check("  시도 기록에 사유가 남는다 (실제 실행)", att and att[-1]["verdict"].startswith("HUMAN(Blender")
              and (run.root / "attempts.json").read_text() != before_attempts, att[-1:] if att else att)

    print("── 5-4b 설정 — 없으면 알리고 기록, --character 명시인데 없으면 멈춘다")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp, done=POD_DONE + ("5-1",))
        rc, out = orch(vol, Path(tmp) / "없는_blender", "--resume")
        check("자동 탐색 실패 → '5-4b 설정 없음 — 건너뜀' + 찾은 곳", "5-4b 설정 없음 — 건너뜀" in out
              and str(vol / "data" / "06_rig") in out)
        meta = json.loads((run.root / "run.json").read_text())
        check("  run.json 에 기록", meta.get("seam_smooth_5_4b", {}).get("applied") is False, meta.get("seam_smooth_5_4b"))
        cdir = vol / "data" / "06_rig" / "cx"
        cdir.mkdir()
        cfg = {"version": 2, "character": "cx", "rig_dir": "06_rig/cx",
               "rig_build": {"source_sample": "smp", "transfer": {}}}
        (cdir / "character.json").write_text(json.dumps(cfg))
        rc, out = orch(vol, Path(tmp) / "없는_blender", "--resume", "--dry-run", "--character", "cx")
        check("--character 명시 + seam_smooth 없음 → 종료 코드 1", rc == 1 and "rig_build.seam_smooth 가 없다" in out, rc)
        rc, out = orch(vol, Path(tmp) / "없는_blender", "--resume", "--dry-run")
        check("명시 없이 같은 설정 → 건너뜀 + 설정 경로", "5-4b 설정 없음 — 건너뜀" in out and str(cdir / "character.json") in out)
        rc, out = orch(vol, Path(tmp) / "없는_blender", "--resume", "--dry-run", "--character", "nochar")
        check("--character 의 설정 파일이 없으면 종료 코드 1 (기존 동작)", rc == 1 and "캐릭터 설정이 없다" in out, rc)

    print("── 동작 트랙 경계 — 회수 목록 · 이어받기 명령")
    with tempfile.TemporaryDirectory() as tmp:
        vol, run = make_vol(tmp, done=("G0", "S2"), name="clipA")
        cdir = vol / "data" / "06_rig" / "lst"
        cdir.mkdir()
        (cdir / "character.json").write_text(json.dumps({"version": 2, "character": "lst", "rig_dir": "06_rig/lst_w"}))
        (cdir / "clip_roles.json").write_text(json.dumps({"clips": {"walk_a": {"source": "clipA", "role": "walk"}}}))
        rc, out = orch(vol, Path(tmp) / "없는_blender", "--motion", "--character", "lst", "--resume", "--dry-run",
                       name="clipA")
        check("종료 코드 2, 동작 트랙 이어받기 명령", rc == 2
              and "--motion --character lst --name clipA --resume" in out, rc)
        check("  회수 목록은 02_sam2 · 04_wham 만", "02_sam2" in out and "clipA_masked" in out and "03_trellis2" not in out)

    print("── run_cmd: 실행 파일이 없으면 traceback 대신 127")
    with tempfile.TemporaryDirectory() as tmp:
        o = load(Path(tmp))
        log = Path(tmp) / "x.log"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                rc = o.run_cmd([str(Path(tmp) / "없는_실행파일"), "a"], log, False)
            except FileNotFoundError as e:
                rc = f"예외 {e}"
        check("종료 코드 127 (게이트 FAIL 1 과 섞이지 않게)", rc == 127, rc)
        check("  로그 · 출력에 경로", "없는_실행파일" in log.read_text() and "없는_실행파일" in buf.getvalue())

    print("\n" + ("전부 통과" if OK else "실패 있음"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
