"""G3(재투영 일관성) 시험 (2026-11-21) — 합성 입력만 쓴다 (미러 · Pod · torch · Blender 불필요, CI 의 RUN).

① g3_rules 순수 로직: 오차 0, 알려진 오차, 연속 튐 구간(5프레임 CHECK / 4프레임 PASS / 프레임 번호 건너뜀),
   신뢰도 낮은 관절 제외, 얼굴 관절 제외(따로 기록)
② gate_g3.py CLI: 판정 JSON · 종료 코드(PASS · CHECK 모두 0, 입력 오류는 0 아님), 이어 붙인 트랙(여러 트랙 키)
③ 오케스트레이터: S5 뒤 G3 명령(외형 · 동작), 기존 run(S5 완료 · G3 판정 없음)을 --resume 해도 G3 를 다시 돌리지
   않고 멈추지도 않는다, CHECK 여도 계속(구간 · 할 일 안내 · 기록), G3 오류는 멈춘다
"""
import contextlib
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import joblib
import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import g3_rules as R  # noqa: E402

OK = True
W, H, HPX = 1080.0, 1920.0, 1600.0          # 영상 크기 · 사람 키 px (bbox scale × 200)


def check(label, cond, got=""):
    global OK
    OK &= bool(cond)
    print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")


def scene(T=40, seed=0):
    """관절 17개 = 정점 17개 (회귀 행렬 = 단위행렬). 카메라 앞 3~4 단위."""
    rng = np.random.default_rng(seed)
    verts = np.zeros((T, 17, 3))
    verts[..., 0] = rng.uniform(-0.3, 0.3, (T, 17))
    verts[..., 1] = rng.uniform(-0.8, 0.8, (T, 17))
    verts[..., 2] = rng.uniform(3.0, 4.0, (T, 17))
    reg = np.eye(17)
    uv = R.project(verts, reg, W, H)
    kp = np.concatenate([uv, np.ones((T, 17, 1))], -1)
    return verts, reg, uv, kp


def shift(kp, frames, joints, frac):
    """프레임 · 관절의 검출을 키 대비 frac 만큼 x 로 민다."""
    kp = kp.copy()
    for f in frames:
        kp[f, joints, 0] += frac * HPX
    return kp


def rules():
    print("── ① 판정 로직 (순수 함수)")
    T = 40
    verts, reg, uv, kp = scene(T)
    fids = np.arange(T)
    e, used = R.errors(uv, kp, np.full(T, HPX))
    v, reasons, rec, fm = R.judge(e, used, fids)
    check("오차 0 → PASS, 0.05 초과 0프레임", v == "PASS" and rec["frames_over"] == 0 and rec["body"]["median"] == 0.0, rec["body"])
    f = (W * W + H * H) ** 0.5
    check("카메라 = WHAM(초점 √(W²+H²), 주점 중앙)", np.allclose(uv[0, 0], [f * verts[0, 0, 0] / verts[0, 0, 2] + W / 2,
                                                                   f * verts[0, 0, 1] / verts[0, 0, 2] + H / 2]))

    e, used = R.errors(uv, shift(kp, range(T), R.BODY, 0.03), np.full(T, HPX))
    v, _, rec, _ = R.judge(e, used, fids)
    check("알려진 오차 3% → 오차 0.03 · PASS (기준 0.05 아래)", v == "PASS" and abs(rec["body"]["median"] - 0.03) < 1e-9, rec["body"]["median"])

    body = list(range(5, 17))
    k5 = shift(kp, range(10, 15), body, 0.08)
    e, used = R.errors(uv, k5, np.full(T, HPX))
    v, reasons, rec, _ = R.judge(e, used, fids)
    check("5프레임 연속 0.08 → CHECK, 구간 f10~f14", v == "CHECK" and rec["check_spans"] == [{"start": 10, "end": 14, "frames": 5, "max": 0.08}],
          rec["check_spans"])
    check("  사유에 구간과 최대값", reasons and "f10~f14" in reasons[0] and "8.0%" in reasons[0], reasons)
    e, used = R.errors(uv, shift(kp, range(10, 14), body, 0.08), np.full(T, HPX))
    v, _, rec, _ = R.judge(e, used, fids)
    check("4프레임 연속 → PASS (최장 4 기록)", v == "PASS" and rec["longest_run"] == 4 and rec["longest_run_start"] == 10, rec["longest_run"])
    gap_ids = np.array(list(range(0, 12)) + list(range(20, 48)))        # f11 → f20 건너뜀
    e, used = R.errors(uv, shift(kp, range(9, 14), body, 0.08), np.full(T, HPX))
    v, _, rec, _ = R.judge(e, used, gap_ids)
    check("프레임 번호가 건너뛰면 연속이 끊긴다 (f9~f11 · f20~f21) → PASS", v == "PASS" and rec["longest_run"] == 3, rec["longest_run"])
    e, used = R.errors(uv, shift(kp, [10, 11, 12, 14, 15], body, 0.08), np.full(T, HPX))
    v, _, rec, _ = R.judge(e, used, fids)
    check("중간에 한 프레임 정상이면 끊긴다 → PASS", v == "PASS" and rec["frames_over"] == 5 and rec["longest_run"] == 3)

    kl = shift(kp, range(T), [9, 10, 15, 16, 13, 14, 7], 0.5)           # 7관절 크게 틀림 …
    kl[:, [9, 10, 15, 16, 13, 14, 7], 2] = 0.3                          # … 신뢰도 낮음
    e, used = R.errors(uv, kl, np.full(T, HPX))
    v, _, rec, _ = R.judge(e, used, fids)
    check("신뢰도 < 0.5 관절은 뺀다 → PASS", v == "PASS" and rec["body"]["max"] == 0.0 and rec["dropped_low_conf"] > 0, rec["body"])
    kn = kp.copy(); kn[3, :, 2] = 0.1
    e, used = R.errors(uv, kn, np.full(T, HPX))
    _, _, rec, fm = R.judge(e, used, fids)
    check("모든 관절이 낮은 프레임은 nan (넘은 것으로 세지 않는다)", np.isnan(fm[3]) and rec["frames_over"] == 0)

    kf = shift(kp, range(T), R.FACE, 0.2)
    e, used = R.errors(uv, kf, np.full(T, HPX))
    v, _, rec, _ = R.judge(e, used, fids)
    check("얼굴 5관절만 크게 틀려도 판정은 몸 관절 → PASS", v == "PASS" and rec["body"]["median"] == 0.0, rec["body"]["median"])
    check("  얼굴 오차는 따로 기록", abs(rec["face"]["median"] - 0.2) < 1e-9 and abs(rec["per_joint_median"]["nose"] - 0.2) < 1e-9, rec["face"])
    check("기준값 = 0.05 · 5프레임 · 신뢰도 0.5, 잠정 표기", (R.FRAME_MAX, R.RUN_MIN, R.CONF_MIN) == (0.05, 5, 0.5) and "잠정" in R.STATUS)


def fixtures(d, T=40, check_frames=(), split=False):
    """gate_g3 입력 파일. tracking 은 numpy 만 (torch 텐서 키 없음 — 판정이 쓰지 않는다)."""
    verts, reg, uv, kp = scene(T)
    kp = shift(kp, check_frames, list(range(5, 17)), 0.08)
    fids = np.arange(T)
    bbox = np.tile([W / 2, H / 2, HPX / 200.0], (T, 1))
    joblib.dump({0: {"verts": verts.astype(np.float32), "frame_ids": fids, "pose": np.zeros((T, 72))}}, d / "wham_output.pkl")
    if split:                                                          # 이어 붙인 트랙 — 2D 가 트랙 둘에 나뉜다
        tr = {0: {"frame_id": fids[:15], "bbox": bbox[:15], "keypoints": kp[:15].astype(np.float32)},
              3: {"frame_id": fids[15:], "bbox": bbox[15:], "keypoints": kp[15:].astype(np.float32)}}
    else:
        tr = {0: {"frame_id": fids, "bbox": bbox, "keypoints": kp.astype(np.float32)}}
    joblib.dump(tr, d / "tracking_results.pth")
    np.save(d / "reg.npy", np.eye(17))


def gate(d, *extra):
    cmd = [sys.executable, str(REPO / "scripts" / "gate_g3.py"), "--pkl", str(d / "wham_output.pkl"),
           "--tracking", str(d / "tracking_results.pth"), "--regressor", str(d / "reg.npy"),
           "--width", str(W), "--height", str(H), "--out", str(d / "gates"), *extra]
    r = subprocess.run(cmd, capture_output=True, text=True)
    j = d / "gates" / "gate_g3.json"
    return r, (json.loads(j.read_text()) if j.exists() else None)


def cli():
    print("── ② gate_g3.py")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t); fixtures(d)
        r, j = gate(d)
        check("PASS → 종료 코드 0 · 판정 JSON", r.returncode == 0 and j and j["verdict"] == "PASS", (r.returncode, r.stderr[-200:]))
        check("  JSON: 프레임 표 · 얼굴 기록 · 한계 · 기준값", j and len(j["frames"]["body_median"]) == 40 and "face" in j["metrics"]
              and len(j["limits"]) == 2 and j["thresholds"]["frame_max"] == 0.05)
    with tempfile.TemporaryDirectory() as t:
        d = Path(t); fixtures(d, check_frames=range(20, 27))
        r, j = gate(d)
        check("CHECK → 종료 코드 0 (멈추지 않는다) · 구간 f20~f26", r.returncode == 0 and j["verdict"] == "CHECK"
              and j["metrics"]["check_spans"][0]["start"] == 20 and j["metrics"]["check_spans"][0]["end"] == 26, j and j["metrics"]["check_spans"])
        check("  표준출력에 CHECK 와 사유", "[CHECK]" in r.stdout and "사유: f20~f26" in r.stdout, r.stdout[-300:])
    with tempfile.TemporaryDirectory() as t:
        d = Path(t); fixtures(d, split=True)
        r, j = gate(d)
        check("이어 붙인 트랙(2D 가 트랙 키 둘에 나뉨) → 40/40 프레임 맞춤", r.returncode == 0 and j["metrics"]["frames_2d"] == 40, j and j["metrics"]["frames_2d"])
    with tempfile.TemporaryDirectory() as t:
        d = Path(t); fixtures(d); np.save(d / "reg.npy", np.eye(24))
        r, j = gate(d)
        check("회귀 행렬이 17관절이 아니면 종료 코드 ≠ 0 (판정 없이 지나가지 않는다)", r.returncode != 0 and j is None, r.returncode)


# ---------------------------------------------------------------- ③ 오케스트레이터
def load(vol):
    os.environ["PIPELINE_VOL"] = str(vol)
    os.environ.pop("PIPELINE_ENV_ROOT", None)
    os.environ["BLENDER"] = str(Path(vol) / "없는_blender")
    import orchestrate
    return importlib.reload(orchestrate)


def make_run(tmp, done, name="smp", motion=False):
    vol = Path(tmp) / "vol"; d = vol / "data"
    sam2 = d / "02_sam2" / name
    (sam2 / "masks").mkdir(parents=True); (sam2 / "masks" / "00000.png").write_bytes(b"x")
    (sam2 / f"{name}_masked.mp4").write_bytes(b"x"); (sam2 / "keyframes").mkdir()
    (sam2 / "keyframes" / "candidates.json").write_text('{"topk": []}')
    (d / "04_wham" / f"{name}_masked").mkdir(parents=True)
    (d / "04_wham" / f"{name}_masked" / "wham_output.pkl").write_bytes(b"x")
    (d / "06_rig").mkdir(parents=True)
    if motion:
        c = d / "06_rig" / "lst"; c.mkdir()
        (c / "character.json").write_text(json.dumps({"version": 2, "character": "lst", "rig_dir": "06_rig/lst_w"}))
        (c / "clip_roles.json").write_text(json.dumps({"clips": {"walk_a": {"source": name, "role": "move",
                                                                            "bake": {"ground_align": True}}}}))
        (d / "06_rig" / "lst_w" / "motions").mkdir(parents=True)
    o = load(vol)
    (d / "runs").mkdir()
    run = o.Run.create(name, str(d / "00_raw" / f"{name}.mp4"), d / "runs")
    run.write_meta({"frames": 40, "width": 1080, "height": 1920, **({"motion_51": True} if motion else {})})
    for k in done:
        run.mark_done(k, [], 0)
    return vol, run


def orch(vol, *args, patch=None):
    o = load(vol)
    if patch:
        patch(o)
    buf = io.StringIO(); argv = sys.argv
    sys.argv = ["orchestrate.py", *args]
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


def orchestrator():
    print("── ③ 오케스트레이터 연결")
    with tempfile.TemporaryDirectory() as t:
        vol, run = make_run(t, done=("G0", "S2"))
        before = snapshot(run.root)
        rc, out = orch(vol, "--name", "smp", "--resume", "--dry-run", "--until", "S5")
        line = next((l for l in out.splitlines() if "gate_g3.py" in l), "")
        check("외형 트랙: S5 에서 gate_s5 뒤 G3 명령 (wham 환경)", rc == 0 and out.index("gate_s5.py") < out.index("gate_g3.py")
              and " run -n wham " in line, rc)
        check("  인자: tracking_results · 환경 루트의 회귀 행렬 · G0 영상 크기",
              "tracking_results.pth" in line and str(vol / "repos/WHAM/dataset/body_models/J_regressor_coco.npy") in line
              and "--width 1080 --height 1920" in line, line.strip()[-220:])
        check("  dry-run 은 run 폴더를 바꾸지 않는다", snapshot(run.root) == before)
    with tempfile.TemporaryDirectory() as t:
        vol, run = make_run(t, done=("G0", "S2"), motion=True)
        rc, out = orch(vol, "--motion", "--character", "lst", "--name", "smp", "--resume", "--dry-run", "--until", "S5")
        check("동작 트랙도 S5 뒤 G3", rc == 0 and "gate_g3.py" in out, rc)

    print("── 기존 run 호환 (S5 완료 · G3 판정 없음)")
    for motion in (False, True):
        with tempfile.TemporaryDirectory() as t:
            done = ("G0", "S2", "S5") if motion else ("G0", "S2", "S5")
            vol, run = make_run(t, done=done, motion=motion)
            o = load(vol)
            ctx = {"name": "smp", **({"track": "motion", "character": "lst", "rig_dir": "06_rig/lst_w",
                                      "clip_key": "walk_a"} if motion else {})}
            stages = o.stages_for(ctx)
            start, skipped, problem = o.resume_point(run, "smp", None, stages, ctx)
            tag = "동작" if motion else "외형"
            check(f"[{tag}] resume_point: S5 건너뜀, 정지 없음 (G3 판정은 S5 필수 산출물이 아니다)",
                  problem is None and "S5" in skipped and start["key"] != "S5", (start and start["key"], problem))
            args = (["--motion", "--character", "lst"] if motion else []) + ["--name", "smp", "--resume", "--dry-run"]
            rc, out = orch(vol, *args)
            check(f"[{tag}] --resume --dry-run 에 G3 가 없다", "gate_g3.py" not in out and "G3 재투영" not in out
                  and "마커는 있는데" not in out, rc)

    print("── G3 판정 처리 (g3_review)")
    for verdict, motion in (("CHECK", True), ("CHECK", False), ("PASS", True)):
        with tempfile.TemporaryDirectory() as t:
            vol, run = make_run(t, done=("G0", "S2"), motion=motion)
            o = load(vol)
            spans = [{"start": 110, "end": 129, "frames": 20, "max": 0.1015}] if verdict == "CHECK" else []

            def fake(argv, log, dry, _v=verdict, _s=spans, _run=run):
                (_run.gates / "gate_g3.json").write_text(json.dumps({
                    "verdict": _v, "reasons": [f"f110~f129 …"] if _s else [],
                    "metrics": {"check_spans": _s, "body": {"median": 0.02, "p95": 0.09}, "longest_run": 20 if _s else 0},
                    "thresholds": {"frame_max": 0.05}}))
                return 0
            o.run_cmd = fake
            c = {"name": "smp", "width": 1080, "height": 1920, "video": "v.mp4",
                 **({"track": "motion", "roles_path": str(vol / "data/06_rig/lst/clip_roles.json"), "clip_key": "walk_a"}
                    if motion else {})}
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = o.g3_review(o.STAGE_BY_KEY["S5"], c, run, "try1", False)
            out = buf.getvalue()
            tag = f"{verdict} · {'동작' if motion else '외형'}"
            att = json.loads((run.root / "attempts.json").read_text())
            meta = run.meta()
            check(f"[{tag}] 실행 계속 (EXIT_OK) · 판정 JSON 시도별 보존", rc == 0 and (run.gates / "gate_g3_try1.json").exists()
                  and not (run.gates / "gate_g3.json").exists(), rc)
            check(f"[{tag}] 시도 기록 · run.json g3", att[-1]["stage"] == "G3" and att[-1]["verdict"] == verdict
                  and meta.get("g3", {}).get("verdict") == verdict)
            if verdict == "CHECK":
                check(f"[{tag}] 안내: 구간 f110~f129 · 겹침 영상 명령", "f110~f129 (20프레임" in out and "overlay_vis.py" in out, out[-400:])
                if motion:
                    check(f"[{tag}] 안내: 역할표 ground_align 현재 값", "'walk_a' bake.ground_align 확인 (지금: True)" in out)
                else:
                    check(f"[{tag}] 외형 트랙은 ground_align 안내 없음", "ground_align" not in out)
            else:
                check(f"[{tag}] PASS 는 할 일 안내 없음", "할 일" not in out and "G3: PASS" in out)
    with tempfile.TemporaryDirectory() as t:
        vol, run = make_run(t, done=("G0", "S2"))
        o = load(vol)
        o.run_cmd = lambda argv, log, dry: 1
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = o.g3_review(o.STAGE_BY_KEY["S5"], {"name": "smp", "width": 1080, "height": 1920}, run, "try1", False)
        att = json.loads((run.root / "attempts.json").read_text())
        check("G3 가 판정을 못 내면 멈춘다 (EXIT_FAIL) · 오류 기록", rc == 1 and att[-1] == {**att[-1], "stage": "G3", "verdict": "ERROR"}
              and "[오류] G3" in buf.getvalue(), rc)
        try:
            o.g3_command({"name": "smp"}, run); raised = None
        except SystemExit as e:
            raised = str(e)
        check("G0 영상 크기가 없으면 추측하지 않고 멈춘다 (실제 실행)", raised and "width · height" in raised, raised)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = o.g3_review(o.STAGE_BY_KEY["S5"], {"name": "smp"}, run, "try1", True)
        check("  dry-run 은 멈추지 않고 사유만 출력", rc == 0 and "G0 영상 크기가 없어" in buf.getvalue(), rc)


def main():
    rules()
    cli()
    orchestrator()
    print("\n" + ("전부 통과" if OK else "실패 있음"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
