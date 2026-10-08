"""오케스트레이터 ↔ G1a 연결 시험 — 가짜 볼륨에서 G1a 단계를 실제로 돌린다.

Pod 없이 맥북에서 돈다. micromamba 는 "환경 이름을 무시하고 그대로 실행" 하는 대역으로
바꾸고, S2·S5 산출물 자리에 미러의 char_shuffle 을 걸어 둔다. 실전 검증(순서가 바뀐
원커맨드 1회)은 Pod 에서 따로 한다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
H = Path(os.path.expanduser("~/data"))
CS = H / "02_sam2" / "char_shuffle"
PKL = H / "04_wham" / "char_shuffle_masked" / "wham_output.pkl"


def make_vol(tmp, closed_legs=False):
    vol = Path(tmp) / "vol"
    mm = vol / "micromamba" / "bin"
    mm.mkdir(parents=True)
    shim = mm / "micromamba"                     # micromamba run -n <env> <cmd...>
    shim.write_text('#!/bin/bash\nshift 3\nif [ "$1" = python ]; then shift; exec "%s" "$@"; fi\nexec "$@"\n'
                    % sys.executable)
    shim.chmod(0o755)
    sam2 = vol / "data" / "02_sam2" / "demo"
    (sam2 / "keyframes").mkdir(parents=True)
    os.symlink(CS / "masks", sam2 / "masks")
    os.symlink(CS / "char_shuffle_masked.mp4", sam2 / "demo_masked.mp4")
    if closed_legs:      # 전 프레임 다리가 붙은 클립 흉내
        allsc = [{"frame": i, "score": 0.2, "bbox": [0, 0, 10, 10], "leg_gap": 0.0}
                 for i in range(192)]
        json.dump({"topk": allsc[:1], "all": allsc}, open(sam2 / "keyframes" / "candidates.json", "w"))
    else:
        for f in (CS / "keyframes").iterdir():
            if f.is_file():
                shutil.copy2(f, sam2 / "keyframes" / f.name)
    wham = vol / "data" / "04_wham" / "demo_masked"
    wham.mkdir(parents=True)
    os.symlink(PKL, wham / "wham_output.pkl")
    return vol, sam2


def orch(vol, *args):
    env = dict(os.environ, PIPELINE_VOL=str(vol))
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "orchestrate.py"), "--name", "demo",
                        *args], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout + r.stderr


def start_run(vol, done=("G0", "S2", "S5")):
    """S5 까지 끝난 run 을 만든다 (산출물은 make_vol 이 깔아 뒀다)."""
    sys.path.insert(0, str(REPO / "scripts"))
    os.environ["PIPELINE_VOL"] = str(vol)
    import importlib
    import orchestrate
    importlib.reload(orchestrate)
    runs = vol / "data" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    run = orchestrate.Run.create("demo", vol / "data" / "02_sam2" / "demo" / "demo_masked.mp4", runs)
    for k in done:
        run.mark_done(k, [], 0)
    return run, orchestrate


def main():
    if not ((CS / "masks").is_dir() and PKL.exists()):
        print("⚠️  미러에 char_shuffle 마스크·pkl 이 없어 건너뛴다")
        return 0
    ok = True

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")

    print("── 단계 순서")
    with tempfile.TemporaryDirectory() as tmp:
        vol, _ = make_vol(tmp)
        _, o = start_run(vol, done=())
        keys = [s["key"] for s in o.STAGES]
        check("G0 → S2 → S5 → G1a → S3 → 5-1", keys[:6] == ["G0", "S2", "S5", "G1a", "S3", "5-1"], keys)

    print("── 정상: G1a 가 돌고 S3 가 1위를 집는다")
    with tempfile.TemporaryDirectory() as tmp:
        vol, sam2 = make_vol(tmp)
        run, o = start_run(vol)
        stale = sorted(f.name for f in (sam2 / "keyframes").glob("key1_f*.png"))
        rc, out = orch(vol, "--resume", "--until", "G1a")
        check("종료 코드 0, G1a 완료 마커", rc == 0 and run.is_done("G1a"), out[-300:] if rc else "")
        now = sorted(f.name for f in (sam2 / "keyframes").glob("key1_f*.png"))
        check(f"key1 이 {len(stale)}장 → 1장 (f6)", now == ["key1_f00006.png"], now)
        kf, frame = o.pick_keyframe("demo", False)
        check("pick_keyframe → key1_f00006.png, frame 6",
              kf and kf.endswith("key1_f00006.png") and frame == "6", (kf, frame))
        # 옛 방식(이름순 첫 장)이 틀리는 상황을 만든다
        (sam2 / "keyframes" / "key1_f00001.png").write_bytes(b"stale")
        kf, frame = o.pick_keyframe("demo", False)
        check("옛 key1 이 섞여 있어도 candidates.json 의 1위를 집는다", frame == "6", frame)

    print("── 인계: 다리 붙음 + 다리 움직임 → 종료 코드 2")
    with tempfile.TemporaryDirectory() as tmp:
        vol, sam2 = make_vol(tmp, closed_legs=True)
        run, o = start_run(vol)
        rc, out = orch(vol, "--resume", "--until", "G1a")
        check("종료 코드 2, 마커 없음, 강행·직접 지정 안내",
              rc == 2 and not run.is_done("G1a") and "--force-keyframe" in out
              and "--keyframe" in out, rc)
        hist = json.loads((run.root / "attempts.json").read_text())
        check("attempts 에 HUMAN 기록", any(h.get("stage") == "G1a" and h.get("verdict") == "HUMAN"
                                          for h in hist))
        rc, out = orch(vol, "--resume", "--until", "G1a", "--force-keyframe")
        d = json.loads((sam2 / "keyframes" / "candidates.json").read_text())
        check("--force-keyframe → 0, forced 기록", rc == 0 and run.is_done("G1a")
              and d["closed_legs"]["forced"] is True, rc)

    print("── --keyframe 지정: G1a 를 건너뛴다")
    with tempfile.TemporaryDirectory() as tmp:
        vol, sam2 = make_vol(tmp)
        run, o = start_run(vol)
        before = sorted(f.name for f in (sam2 / "keyframes").iterdir())
        kf = str(sam2 / "keyframes" / "key2_f00006.png")
        rc, out = orch(vol, "--resume", "--until", "G1a", "--keyframe", kf)
        check("종료 코드 0, '건너뜀', frame=6", rc == 0 and "건너뜀" in out and "frame=6" in out, rc)
        check("keyframes/ 불변 (재선정하지 않았다)",
              sorted(f.name for f in (sam2 / "keyframes").iterdir()) == before)
        check("run 기록에 frame 6", run.meta().get("frame") == "6", run.meta().get("frame"))
    with tempfile.TemporaryDirectory() as tmp:
        vol, sam2 = make_vol(tmp)
        run, o = start_run(vol)
        rc, out = orch(vol, "--resume", "--until", "G1a", "--keyframe", "/x/내사진.png")
        check("프레임 번호를 못 읽는 파일명 → 종료 코드 1", rc == 1 and "프레임 번호" in out, rc)

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
