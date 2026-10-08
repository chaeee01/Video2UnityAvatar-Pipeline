#!/usr/bin/env python3
"""
파이프라인 오케스트레이터 (v1 골격) — 영상 1편 → Unity 반입용 FBX.

설계: docs/ORCHESTRATOR_DESIGN.md (2026-09-29 승인본). 이 파일은 그 설계의 구현이고,
설계는 RUNBOOK 의 코드화다 — 새 절차를 만들지 않는다.

  # Pod 구간
  python orchestrate.py --video /workspace/data/00_raw/zombie_walker.mp4 --name zombie_walker
  # 맥북 구간 (run 폴더·산출물 회수 후)
  python orchestrate.py --name zombie_walker --resume

  --dry-run      실행할 명령과 분기만 출력한다 (아무것도 실행하지 않는다)
  --keyframe     S3 에 넣을 키프레임을 직접 지정 (기본: G1a 재선정 1위). G1a 를 건너뛴다
  --force-keyframe  G1a 가 "다리 벌린 프레임 없음 + 다리 움직임" 으로 인계할 때 강행한다
  --point x,y    S2 시작 좌표 (기본: 프레임 중앙)

종료 코드: 0 성공 / 1 실패 / 2 사람 개입 필요

구간이 둘인 이유는 GPU 작업(Pod)과 Blender 작업(맥북)이 갈리기 때문이다. 같은 스크립트를
양쪽에서 돌리고 완료 마커로 이어받는다 — 실행 환경을 추정하지 않고, 마커가 가리키는
다음 단계가 이 기계에서 돌 수 없으면 그 자리에서 멈춘다.

이 파일은 **골격**이다. 게이트 분기·재시도(설계 3-4절)는 다음 단계에서 붙인다.
"""
import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

VOL = Path(os.environ.get("PIPELINE_VOL", "/workspace"))
POD, MAC = "pod", "mac"

EXIT_OK, EXIT_FAIL, EXIT_HUMAN = 0, 1, 2


# ---------------------------------------------------------------- 단계 정의
# 설계 2절의 단계 정의표를 그대로 옮긴 것이다. 표에 있는 것만 여기 있고,
# 여기 없는 것은 v1 범위 밖이다 (설계 7절).
#
#   key      마커 파일 이름이자 단계 식별자
#   section  pod | mac — 어느 기계에서 도는가
#   env      micromamba 환경 이름. None 이면 환경 없이 실행한다
#            (맥북 구간은 Blender --background 나 시스템 python3 라 전부 None)
#   gate     이 단계 뒤에 돌릴 게이트. None 이면 게이트 없음
#   outputs  완료 판정에 쓰는 산출물. 마커가 있어도 이게 없으면 정지한다 (설계 5절)
STAGES = [
    dict(key="G0",   section=POD, env=None,       gate="self",
         desc="입력 검증 (프레임·fps·해상도 실측)"),
    dict(key="S2",   section=POD, env="sam2",     gate="gate_s2",
         desc="SAM2 분할·트래킹"),
    # 2026-10-08: S5 를 S3 앞으로 옮기고 G1a 를 단계로 세웠다. 키프레임을 고르는 데
    # WHAM pose(시선각·다리 움직임)가 필요해서다. 같은 Pod 에서 직렬로 도므로 순서를
    # 바꿔도 총 시간은 같다. G3 가 생기면 S5 와 G1a 사이에 들어간다 — 동작을 먼저
    # 확정해야 G3 재시도가 S3 를 무효화하지 않는다.
    dict(key="S5",   section=POD, env="wham",     gate=None,
         desc="WHAM 동작 복원 (G3 미구현 — 설계 7절)"),
    dict(key="G1a",  section=POD, env="wham",     gate=None,
         desc="키프레임 재선정 (마스크 + WHAM 시선각·다리 움직임)"),
    dict(key="S3",   section=POD, env="trellis2", gate="gate_g2",
         desc="TRELLIS.2 외형 복원"),
    dict(key="5-1",  section=POD, env="wham",     gate=None,
         desc="SMPL 메쉬 생성"),
    dict(key="5-2",  section=MAC, env=None,       gate=None,
         desc="TRELLIS-SMPL 정렬"),
    dict(key="5-3",  section=MAC, env=None,       gate=None,
         desc="아마추어 생성·바인딩"),
    dict(key="5-4",  section=MAC, env=None,       gate="gate_g2r",
         desc="웨이트 전이 (G2r 은 5-2~5-4 산출물을 모두 받는다)"),
    dict(key="5-5",  section=MAC, env=None,       gate=None,
         desc="WHAM pose 베이킹"),
    dict(key="FBX",  section=MAC, env=None,       gate=None,
         desc="Unity 반입용 FBX export"),
]
STAGE_BY_KEY = {s["key"]: s for s in STAGES}

# G1a 는 2026-10-08 부터 단계다 (설계 10절 개정). S2 가 마스크만으로 1차 후보를 내고,
# S5 뒤의 G1a(select_keyframes.py)가 WHAM pose 로 다시 매긴다. 별도 gate_g1a.py 는
# 없다 — 판정(진행 / 사람에게 인계)을 단계 자신이 종료 코드로 낸다.


# ---------------------------------------------------------------- 경로
def data(*parts):
    return VOL.joinpath("data", *parts)


def stage_outputs(key, name):
    """단계별 필수 산출물. 마커 검증(설계 5절 규칙 4)에 쓴다."""
    sam2 = data("02_sam2", name)
    rig = data("06_rig", name)
    return {
        "G0":  [],
        "S2":  [sam2 / "masks", sam2 / f"{name}_masked.mp4", sam2 / "keyframes"],
        "S5":  [data("04_wham", f"{name}_masked", "wham_output.pkl")],
        "G1a": [sam2 / "keyframes" / "candidates.json"],
        "S3":  [data("03_trellis2", name, f"{name}.glb")],
        "5-1": [data("05_smpl_mesh", name)],
        "5-2": [rig / "aligned.blend", rig / "aligned_params.json"],
        "5-3": [rig / "rigged.blend", rig / "rigged_params.json"],
        "5-4": [rig / "transferred.blend", rig / "transferred_params.json"],
        "5-5": [rig / "animated.blend"],
        "FBX": [data("07_unity", name, f"{name}_wham.fbx")],
    }[key]


# ---------------------------------------------------------------- run 폴더
class Run:
    """run_<샘플>_<일시>/ — 실행 기록만 담는다.

    산출물은 규약 경로(data/02_sam2/… 등)에 그대로 쓴다. run 폴더로 옮기면 기존
    절차와 게이트 인자 경로가 전부 깨진다 (설계 5절).
    """

    def __init__(self, root: Path, name: str):
        self.root, self.name = root, name
        self.done = root / "done"
        self.gates = root / "gates"
        self.logs = root / "logs"

    @classmethod
    def create(cls, name, video, runs_dir):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        r = cls(Path(runs_dir) / f"run_{name}_{stamp}", name)
        for d in (r.root, r.done, r.gates, r.logs):
            d.mkdir(parents=True, exist_ok=True)
        r.write_meta({"name": name, "video": str(video) if video else None,
                      "started": datetime.now().isoformat(timespec="seconds"),
                      "vol": str(VOL)})
        (r.root / "attempts.json").write_text("[]\n")
        return r

    @classmethod
    def latest(cls, name, runs_dir):
        cands = sorted(Path(runs_dir).glob(f"run_{name}_*"))
        if not cands:
            return None
        return cls(cands[-1], name)

    # --- 메타 ---
    def write_meta(self, d):
        cur = self.meta()
        cur.update(d)
        (self.root / "run.json").write_text(json.dumps(cur, indent=2, ensure_ascii=False))

    def meta(self):
        f = self.root / "run.json"
        return json.loads(f.read_text()) if f.exists() else {}

    # --- 마커 ---
    # 규칙(설계 5절): 마커는 **게이트 PASS 까지 끝난 뒤에만** 쓴다. 단계는 돌았지만
    # 게이트가 FAIL 이면 쓰지 않는다 — 그래야 재개가 그 단계부터 다시 시작한다.
    def mark_done(self, key, outputs, elapsed_s):
        (self.done / f"{key}.done").write_text(json.dumps({
            "stage": key,
            "finished": datetime.now().isoformat(timespec="seconds"),
            "elapsed_s": round(elapsed_s, 1),
            "outputs": [str(o) for o in outputs],
        }, indent=2, ensure_ascii=False))

    def is_done(self, key):
        return (self.done / f"{key}.done").exists()

    def marker(self, key):
        f = self.done / f"{key}.done"
        return json.loads(f.read_text()) if f.exists() else None

    # --- 시도 이력 ---
    def add_attempt(self, rec):
        f = self.root / "attempts.json"
        hist = json.loads(f.read_text()) if f.exists() else []
        hist.append(rec)
        f.write_text(json.dumps(hist, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------- 실행
def build_cmd(env, argv):
    """환경이 지정돼 있으면 micromamba run 으로 감싼다.

    활성화 상태에 의존하지 않기 위해서다 — 오케스트레이터 자신이 어느 환경에서 돌든
    각 단계는 제 환경에서 실행된다.

    맥북 구간은 env=None 이다. Blender 는 --background 로 자체 python 을 쓰고
    convert_wham_npz.py 는 시스템 python3 을 쓴다 (2026-09-30 실측: 맥북에
    micromamba 자체가 없고 필요도 없다).
    """
    if env is None:
        # 환경 밖에서는 "python" 이 없을 수 있다 — 맥북에는 python3 만 있다.
        # 지금 이 스크립트를 돌리는 인터프리터를 그대로 쓴다.
        if argv and argv[0] in ("python", "python3"):
            return [sys.executable] + argv[1:]
        return argv
    mm = str(VOL / "micromamba" / "bin" / "micromamba")
    return [mm, "run", "-n", env] + argv


def run_cmd(argv, log_path, dry):
    if dry:
        print(f"    $ {' '.join(shlex.quote(a) for a in argv)}")
        return 0
    with open(log_path, "w") as f:
        return subprocess.run(argv, stdout=f, stderr=subprocess.STDOUT).returncode


# ---------------------------------------------------------------- 명령 조립
# 각 단계가 실제로 무엇을 부르는지. RUNBOOK 의 명령을 그대로 옮긴 것이고,
# 인자 이름은 CONVENTIONS 2 의 CLI 규약을 따른다.
BLENDER = os.environ.get("BLENDER", "/Applications/Blender4.5.app/Contents/MacOS/Blender")


def scripts_dir():
    return Path(__file__).resolve().parent


def blender(script, *args):
    return [BLENDER, "--background", "--python", str(scripts_dir() / script), "--", *args]


def stage_command(key, c):
    """단계 → 실행할 argv. c 는 실행 맥락(ctx)."""
    n, S = c["name"], scripts_dir()
    sam2, rig = data("02_sam2", n), data("06_rig", n)
    if key == "G0":
        return None                                   # 자체 처리 (probe_input)
    if key == "S2":
        cmd = ["python", str(S / "run_sam2.py"), "--video", str(c["video"]),
               "--out", str(sam2)]
        if c.get("point"):
            cmd += ["--point", c["point"]]
        return cmd
    if key == "S3":
        return ["python", str(S / "run_trellis2.py"), "--image", str(c["keyframe"]),
                "--out", str(data("03_trellis2", n)), "--name", n,
                "--seed", str(c.get("seed", 0))]
    if key == "S5":
        return ["bash", str(S / "run_wham.sh"), str(sam2 / f"{n}_masked.mp4")]
    if key == "G1a":
        cmd = ["python", str(S / "select_keyframes.py"), "--sam2-dir", str(sam2),
               "--video", str(c["video"]),
               "--wham-pkl", str(data("04_wham", f"{n}_masked", "wham_output.pkl"))]
        if c.get("force_keyframe"):
            cmd.append("--allow-closed-legs")
        return cmd
    if key == "5-1":
        return ["python", str(S / "generate_smpl_mesh.py"),
                "--pkl", str(data("04_wham", f"{n}_masked", "wham_output.pkl")),
                "--frame", str(c["frame"]), "--name", n]
    if key == "5-2":
        return blender("align_smpl_to_trellis.py",
                       "--trellis", str(data("03_trellis2", n, f"{n}.glb")),
                       "--smpl", str(data("05_smpl_mesh", n, f"smpl_frame{c['frame']}.obj")),
                       "--out", str(rig / "aligned.blend"))
    if key == "5-3":
        return blender("create_smpl_armature.py",
                       "--blend", str(rig / "aligned.blend"),
                       "--joints", str(data("05_smpl_mesh", n, f"joints_frame{c['frame']}.json")),
                       "--out", str(rig / "rigged.blend"))
    if key == "5-4":
        return blender("transfer_weights.py",
                       "--blend", str(rig / "rigged.blend"),
                       "--out", str(rig / "transferred.blend"))
    if key == "5-5":
        return blender("apply_wham_pose.py",
                       "--blend", str(rig / "transferred.blend"),
                       "--npz", str(rig / "wham_pose.npz"),
                       "--out", str(rig / "animated.blend"),
                       "--frame", str(c["frame"]))
    if key == "FBX":
        return blender("export_unity_fbx.py",
                       "--blend", str(rig / "animated.blend"),
                       "--out", str(data("07_unity", n, f"{n}_wham.fbx")))
    raise KeyError(key)


def pre_command(key, c):
    """단계 앞에 먼저 돌려야 하는 것. 없으면 None."""
    if key == "5-5":
        # wham_output.pkl -> wham_pose.npz (RUNBOOK 5-5)
        return ["python3", str(scripts_dir() / "convert_wham_npz.py"),
                "--pkl", str(data("04_wham", f"{c['name']}_masked", "wham_output.pkl")),
                "--out", str(data("06_rig", c["name"], "wham_pose.npz"))]
    return None


def gate_command(key, c, run: "Run", tag):
    """단계 뒤 게이트 → argv. 판정 JSON 은 run/gates/ 에 쌓는다."""
    n, S = c["name"], scripts_dir()
    out = run.gates
    if key == "S2":
        cmd = ["python", str(S / "gate_s2.py"),
               "--masks", str(data("02_sam2", n, "masks")),
               "--out", str(out), "--name", f"{n}_{tag}"]
        if c.get("frames"):
            # G0 가 실측한 프레임 수. 없으면 붙이지 않는다 (0 을 넘기면 오판한다).
            cmd += ["--frames", str(c["frames"])]
        return cmd
    if key == "S3":
        return ["python", str(S / "gate_g2.py"),
                "--glb", str(data("03_trellis2", n, f"{n}.glb")),
                "--out", str(out), "--name", f"{n}_{tag}"]
    if key == "5-4":
        # G2r 은 5-2·5-3·5-4 산출물을 모두 받는다 (설계 8절 ①).
        rig = data("06_rig", n)
        cmd = ["python", str(S / "gate_g2r.py"),
               "--params", str(rig / "aligned_params.json"),
               "--out", str(out), "--name", f"{n}_{tag}"]
        for flag, src, field in [("--joint-dist", "rigged_params.json", "joint_dist"),
                                 ("--fallback-pct", "transferred_params.json", "fallback_pct"),
                                 ("--unassigned-pct", "transferred_params.json", "unassigned_pct")]:
            f = rig / src
            if f.exists():
                cmd += [flag, str(json.loads(f.read_text())[field])]
        # 폴백 분포 — G2r 이 폴백 총량과 무관하게 이것으로 분포를 판정한다.
        if (rig / "transferred_params.json").exists():
            cmd += ["--transferred", str(rig / "transferred_params.json")]
        return cmd
    return None


# ---------------------------------------------------------------- G0 (자체 게이트)
G0_FRAMES = (90, 600)
G0_FPS = (24, 30)
G0_MIN_HEIGHT = 720


def probe_input(video, dry):
    """ffprobe 로 실측한다. 표기를 믿지 않는다 (RUNBOOK 0절 흔한 실패)."""
    if dry:
        return {"dry": True}, []
    q = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames,avg_frame_rate,width,height",
         "-of", "json", str(video)]
    r = subprocess.run(q, capture_output=True, text=True)
    if r.returncode != 0:
        return None, [f"ffprobe 실패: {r.stderr.strip()[:200]}"]
    st = json.loads(r.stdout)["streams"][0]
    num, den = (st["avg_frame_rate"].split("/") + ["1"])[:2]
    m = {"frames": int(st["nb_read_frames"]), "fps": round(int(num) / int(den), 2),
         "width": int(st["width"]), "height": int(st["height"])}
    bad = []
    if not (G0_FRAMES[0] <= m["frames"] <= G0_FRAMES[1]):
        bad.append(f"프레임 {m['frames']} 이 {G0_FRAMES[0]}-{G0_FRAMES[1]} 밖")
    if not (G0_FPS[0] <= m["fps"] <= G0_FPS[1]):
        bad.append(f"fps {m['fps']} 가 {G0_FPS[0]}-{G0_FPS[1]} 밖")
    if m["height"] < G0_MIN_HEIGHT:
        bad.append(f"세로 {m['height']}px 가 {G0_MIN_HEIGHT} 미만")
    return m, bad


# ---------------------------------------------------------------- 재시도 전략
# 설계 3절. 상한은 제안값이고 근거는 설계 문서에 있다.
S2_MAX_TRIES, G2_MAX_TRIES = 3, 2

# 비율 좌표다 — 해상도가 달라져도 같은 전략이 성립한다.
# 1번은 지정값(또는 중앙), 2번 이후가 대안이다.
S2_OFFSETS = [(0.50, 0.50), (0.50, 0.38), (0.50, 0.62), (0.46, 0.45), (0.54, 0.45)]


def s2_point(try_n, c):
    """시도 번호 → '--point x,y'. 1번은 사용자 지정이 있으면 그것."""
    if try_n == 1 and c.get("point"):
        return c["point"], "지정값"
    rx, ry = S2_OFFSETS[min(try_n - 1, len(S2_OFFSETS) - 1)]
    w, h = c.get("width"), c.get("height")
    if not w:
        return None, "해상도 미상 — 스크립트 기본값(중앙)"
    return f"{int(w * rx)},{int(h * ry)}", f"비율 ({rx}, {ry})"


def preserve_probe(path: Path, tag, dry):
    """실패 산출물을 지우지 않고 _probe 로 옮긴다.

    9/10 교훈 — listener 1·2차가 rm -rf 로 사라져 게이트 시험을 만들지 못했다.
    실패 산출물은 게이트 시험지이고 재생성에 비용이 든다.
    """
    if not path.exists():
        return None
    dst = path.with_name(f"{path.name}_probe{tag}")
    print(f"    보존: {path.name} → {dst.name}")
    if not dry:
        if dst.exists():
            return str(dst)
        path.rename(dst)
    return str(dst)


# ---------------------------------------------------------------- 재개 판정
def has_output(p) -> bool:
    """산출물이 실제로 있는가. 빈 폴더는 없는 것으로 본다."""
    p = Path(p)
    if not p.exists():
        return False
    return any(p.iterdir()) if p.is_dir() else True


def resume_point(run: Run, name, section_filter=None):
    """어디서부터 시작할지 정한다. (시작 단계, 건너뛴 목록, 문제) 를 돌려준다.

    설계 5절 규칙 4 — 마커는 있는데 산출물이 없으면 **정지한다.** 조용히 다시
    돌리지 않는다. 어느 쪽이 맞는 상태인지는 사람이 정해야 한다 (회수 누락일 수도,
    산출물 삭제일 수도 있다).
    """
    skipped = []
    for s in STAGES:
        if section_filter and s["section"] != section_filter:
            continue
        if not run.is_done(s["key"]):
            return s, skipped, None
        missing = [p for p in stage_outputs(s["key"], name) if not has_output(p)]
        if missing:
            return None, skipped, {
                "stage": s["key"],
                "reason": "마커는 있는데 산출물이 없다",
                "missing": [str(m) for m in missing],
            }
        skipped.append(s["key"])
    return None, skipped, None


# ---------------------------------------------------------------- main
def parse_args():
    ap = argparse.ArgumentParser(description="파이프라인 오케스트레이터 (v1 골격)")
    ap.add_argument("--video", help="입력 영상 (첫 실행에 필수)")
    ap.add_argument("--name", required=True, help="샘플명")
    ap.add_argument("--resume", action="store_true", help="최신 run 을 이어받는다")
    ap.add_argument("--run", help="이어받을 run 폴더를 직접 지정")
    ap.add_argument("--runs-dir", default=None,
                    help="run 폴더 위치. 기본 <vol>/data/runs")
    ap.add_argument("--point", help="S2 시작 좌표 'x,y' (기본: 프레임 중앙)")
    ap.add_argument("--keyframe", help="S3 에 넣을 키프레임 PNG (기본: G1a 재선정 1위). "
                                       "파일명에 _f<프레임번호> 가 있어야 한다")
    ap.add_argument("--force-keyframe", action="store_true",
                    help="G1a 인계(다리 벌린 프레임 없음 + 다리 움직임)를 강행한다")
    ap.add_argument("--section", choices=[POD, MAC],
                    help="이 구간만 돈다 (기본: 마커가 가리키는 다음 단계부터)")
    ap.add_argument("--until", metavar="STAGE",
                    help="이 단계까지만 돌고 멈춘다 (단계별 확인용, 예: 5-2)")
    ap.add_argument("--dry-run", action="store_true",
                    help="실행할 명령과 분기만 출력한다")
    return ap.parse_args()


def main():
    a = parse_args()
    runs_dir = Path(a.runs_dir) if a.runs_dir else data("runs")
    runs_dir.mkdir(parents=True, exist_ok=True)

    # --- run 폴더 확보 ---
    if a.run:
        run = Run(Path(a.run), a.name)
        if not run.root.exists():
            print(f"[오류] run 폴더가 없다: {run.root}")
            return EXIT_FAIL
    elif a.resume:
        run = Run.latest(a.name, runs_dir)
        if run is None:
            print(f"[오류] 이어받을 run 이 없다: {runs_dir}/run_{a.name}_*")
            return EXIT_FAIL
    else:
        if not a.video:
            print("[오류] 첫 실행에는 --video 가 필요하다 (이어받으려면 --resume)")
            return EXIT_FAIL
        run = Run.create(a.name, a.video, runs_dir)

    print(f"run: {run.root}")
    print(f"샘플: {a.name}   모드: {'dry-run' if a.dry_run else '실행'}")

    # --- 어디서부터? ---
    start, skipped, problem = resume_point(run, a.name, a.section)
    if skipped:
        print(f"건너뜀 (완료됨): {', '.join(skipped)}")
    if problem:
        print(f"\n[정지] {problem['stage']}: {problem['reason']}")
        for m in problem["missing"]:
            print(f"  없음: {m}")
        print("\n  Pod 에서 회수하지 않았거나 산출물이 지워졌다.")
        print(f"  회수했다면 다시 --resume, 다시 돌리려면 {run.done}/{problem['stage']}.done 을 지운다.")
        return EXIT_HUMAN
    if start is None:
        print("\n모든 단계 완료. Unity 반입은 수동이다 (RUNBOOK 6절).")
        return EXIT_OK

    # --- 구간 확인 ---
    # 실행 환경을 추정하지 않는다. 다음 단계가 이 기계에서 돌 수 없으면 멈추고 알린다.
    print(f"\n다음 단계: [{start['key']}] {start['desc']}  (구간 {start['section']})")
    remaining = [s for s in STAGES if not run.is_done(s["key"])]
    sections = list(dict.fromkeys(s["section"] for s in remaining))  # 파이프라인 순서 유지
    if len(sections) > 1:
        print(f"남은 구간: {' → '.join(sections)} — 구간이 바뀌는 지점에서 회수가 필요하다")

    # --- 실행 ---
    print("\n" + "=" * 62)
    ctx = dict(name=a.name, video=a.video or run.meta().get("video"),
               point=a.point, keyframe=a.keyframe, seed=0,
               force_keyframe=a.force_keyframe)
    ctx.update({k: v for k, v in run.meta().items()
                if k in ("frames", "width", "height", "frame", "keyframe")})
    if a.keyframe:
        # 사람이 고른 키프레임이 run 기록보다 우선한다. 프레임 번호는 파일명에서 읽는다
        # — 5-1·5-5 가 같은 프레임의 SMPL 메쉬를 써야 하므로 추측하지 않는다.
        frame = frame_from_name(a.keyframe)
        if frame is None:
            print(f"[오류] --keyframe 파일명에서 프레임 번호를 읽지 못했다: {a.keyframe}")
            print("  key<순위>_f<프레임번호>.png 꼴이어야 한다 (예: key2_f00006.png)")
            return EXIT_FAIL
        ctx["keyframe"], ctx["frame"] = a.keyframe, frame
        ctx["keyframe_by_user"] = True

    here = a.section or remaining[0]["section"]
    for s in remaining:
        if s["section"] != here:
            # 구간 경계. 다음 단계는 다른 기계에서 돈다 — 여기서 끊고 인계한다.
            print("=" * 62)
            print(f"\n[인계] {here} 구간 완료. 다음 [{s['key']}] 은 {s['section']} 구간이다.")
            if here == POD:
                print("\n  아래를 맥북으로 회수한 뒤 이어받는다:")
                print(f"    {run.root}")
                for d in ("02_sam2", "03_trellis2", "04_wham", "05_smpl_mesh"):
                    print(f"    {data(d, a.name)}")
                print(f"\n    python scripts/orchestrate.py --name {a.name} --resume")
            else:
                print(f"\n    python scripts/orchestrate.py --name {a.name} --resume")
            return EXIT_HUMAN
        code = run_stage(s, ctx, run, a.dry_run)
        if code != EXIT_OK:
            return code
        # 기록을 --until 정지보다 먼저 한다. 순서가 반대였을 때는 --until 로 멈춘 run 을
        # 이어받으면 키프레임·프레임 번호가 남아 있지 않았다 (2026-10-08 시험에서 발견).
        run.write_meta({k: ctx[k] for k in ("frames", "width", "height", "frame", "keyframe")
                        if ctx.get(k) is not None})
        if a.until and s["key"] == a.until:
            print("=" * 62)
            print(f"\n[정지] --until {a.until} 에 도달했다. 이어서 돌리려면 --resume.")
            return EXIT_OK

    print("=" * 62)
    print("\n모든 단계 완료. Unity 반입은 수동이다 (RUNBOOK 6절):")
    print("  Rig → Animation Type: Generic  (Humanoid 로 두면 동작이 왜곡된다)")
    print("  Material → URP Base Map 에 textures/<샘플>_tex_0.png 연결")
    return EXIT_OK


def run_stage(s, c, run: Run, dry) -> int:
    """단계 하나를 게이트·재시도까지 처리한다. 종료 코드를 돌려준다."""
    key = s["key"]
    print(f"\n[{key}] {s['desc']}")

    # ---- G0: 자체 게이트. FAIL 이면 즉시 종료 (설계 3절) ----
    if key == "G0":
        m, bad = probe_input(c["video"], dry)
        if m is None:
            print(f"    실패: {bad}")
            return EXIT_FAIL
        if not dry:
            print(f"    실측 {m['frames']}프레임 {m['fps']}fps {m['width']}x{m['height']}")
            c.update(m)
        if bad:
            print("\n[종료] G0 불합격 — 입력이 조건을 만족하지 않는다")
            for b in bad:
                print(f"  - {b}")
            print("\n  영상 재소싱·재생성은 파이프라인 밖의 일이다. 조건은 RUNBOOK 0절.")
            run.add_attempt({"stage": "G0", "verdict": "FAIL", "reasons": bad, "metrics": m})
            return EXIT_FAIL
        run.add_attempt({"stage": "G0", "verdict": "PASS", "metrics": m})
        run.mark_done(key, [], 0)
        return EXIT_OK

    # ---- G1a: 사람이 키프레임을 지정했으면 재선정하지 않는다 ----
    if key == "G1a" and c.get("keyframe_by_user"):
        print(f"    건너뜀: --keyframe 지정 ({Path(c['keyframe']).name}, frame={c['frame']})")
        run.add_attempt({"stage": key, "verdict": "SKIP(--keyframe)",
                         "params": {"keyframe": str(c["keyframe"])}})
        run.mark_done(key, [], 0)
        return EXIT_OK

    # ---- S3 앞: 키프레임 결정 ----
    if key == "S3" and not c.get("keyframe"):
        kf, frame = pick_keyframe(c["name"], dry)
        if kf is None and not dry:
            print("    실패: 키프레임 후보를 찾지 못했다")
            return EXIT_FAIL
        c["keyframe"], c["frame"] = kf, frame
        print(f"    키프레임: {Path(kf).name if kf else '(dry)'}  frame={frame}")

    max_tries = {"S2": S2_MAX_TRIES, "S3": G2_MAX_TRIES}.get(key, 1)
    for n in range(1, max_tries + 1):
        tag = f"try{n}"
        note = ""
        # 재시도 파라미터 (설계 3절)
        if key == "S2":
            pt, how = s2_point(n, c)
            c["point"], note = pt, f"point={pt} ({how})"
        elif key == "S3" and n > 1:
            c["seed"] = n - 1
            note = f"seed={c['seed']}"
            # 덮어쓰기 금지 — 이전 산출물을 _probe 로 보존한다
            saved = preserve_probe(data("03_trellis2", c["name"]), n - 1, dry)
            c["preserved"] = saved
        if note:
            print(f"    시도 {n}/{max_tries}: {note}")

        if not dry:
            for o in stage_outputs(key, c["name"]):
                Path(o).parent.mkdir(parents=True, exist_ok=True)
        pre = pre_command(key, c)
        if pre:
            prc = run_cmd(build_cmd(s["env"], pre), run.logs / f"{key}_pre.log", dry)
            if prc != 0 and not dry:
                print(f"    실패: 선행 명령이 종료 코드 {prc} — {run.logs / f'{key}_pre.log'}")
                run.add_attempt({"stage": key, "n": n, "verdict": "PRE_ERROR", "rc": prc})
                return EXIT_FAIL
        cmd = build_cmd(s["env"], stage_command(key, c))
        t0 = datetime.now()
        rc = run_cmd(cmd, run.logs / f"{key}_{tag}.log", dry)
        elapsed = (datetime.now() - t0).total_seconds()
        if key == "G1a" and rc == EXIT_HUMAN and not dry:
            # 재선정이 사람에게 넘겼다 — 실패가 아니라 정지다. 사유는 로그에 있다.
            log = run.logs / f"{key}_{tag}.log"
            run.add_attempt({"stage": key, "n": n, "verdict": "HUMAN",
                             "elapsed_s": round(elapsed, 1)})
            print("\n[정지] G1a — 이 클립에는 다리가 벌어진 프레임이 없는데 동작은 다리를 움직인다")
            for line in log.read_text(errors="replace").splitlines():
                if line.startswith("[인계]"):
                    print(f"  {line}")
            print("\n  다리가 붙은 채 만든 메쉬는 리깅에서 좌우가 갈리지 않는다 (char_shuffle f60).")
            print("  권고: 다리가 벌어진 프레임이 있는 영상으로 다시 만든다.")
            print(f"  강행: python orchestrate.py --name {c['name']} --resume --force-keyframe")
            print(f"  직접 지정: python orchestrate.py --name {c['name']} --resume "
                  f"--keyframe <후보.png>")
            print(f"  후보: {data('02_sam2', c['name'], 'keyframes')}   로그: {log}")
            return EXIT_HUMAN
        if rc != 0 and not dry:
            print(f"    실패: 단계가 종료 코드 {rc} 로 끝났다 — {run.logs / f'{key}_{tag}.log'}")
            run.add_attempt({"stage": key, "n": n, "verdict": "ERROR", "rc": rc,
                             "elapsed_s": round(elapsed, 1)})
            return EXIT_FAIL

        # 산출물 확인. Blender 는 --python 스크립트가 예외로 죽어도 종료 코드 0 을
        # 내므로 rc 만으로는 실패를 잡지 못한다 (2026-09-30 시험 c 에서 5-5·FBX 가
        # 그렇게 "통과" 했다). 선언한 산출물이 실제로 생겼는지가 완료 판정이다.
        if not dry:
            miss = [o for o in stage_outputs(key, c["name"]) if not has_output(o)]
            if miss:
                print(f"    실패: 단계는 끝났는데 산출물이 없다 (종료 코드 {rc})")
                for m in miss:
                    print(f"      없음: {m}")
                print(f"      로그: {run.logs / f'{key}_{tag}.log'}")
                run.add_attempt({"stage": key, "n": n, "verdict": "NO_OUTPUT", "rc": rc,
                                 "missing": [str(m) for m in miss],
                                 "elapsed_s": round(elapsed, 1)})
                return EXIT_FAIL

        # ---- 게이트 ----
        gc = gate_command(key, c, run, tag)
        if gc is None:
            run.add_attempt({"stage": key, "n": n, "verdict": "OK(게이트 없음)",
                             "params": gate_params(key, c), "elapsed_s": round(elapsed, 1)})
            run.mark_done(key, stage_outputs(key, c["name"]), elapsed)
            return EXIT_OK

        grc = run_cmd(build_cmd(s["env"], gc), run.logs / f"{key}_{tag}_gate.log", dry)
        gj = run.gates / f"gate_{gc[1].split('gate_')[1].split('.py')[0]}.json"
        if not dry and grc not in (0, 1):
            # 게이트 규약은 PASS 0 / FAIL 1 이다. 그 밖은 게이트가 깨진 것이다.
            print(f"    [오류] 게이트가 종료 코드 {grc} 로 죽었다 — 판정이 아니다")
            print(f"    로그: {run.logs / f'{key}_{tag}_gate.log'}")
            run.add_attempt({"stage": key, "n": n, "verdict": "GATE_ERROR", "rc": grc,
                             "params": gate_params(key, c)})
            return EXIT_FAIL
        # 게이트는 고정 파일명으로 쓴다. 재시도가 덮어쓰지 않게 시도별로 보존한다.
        kept = gj.with_name(f"{gj.stem}_{tag}.json")
        if gj.exists() and not dry:
            gj.replace(kept)
            gj = kept
        verdict, reasons = read_verdict(gj, dry, grc)
        print(f"    게이트: {verdict}" + (f" — {'; '.join(reasons)}" if reasons else ""))
        run.add_attempt({"stage": key, "n": n, "verdict": verdict, "reasons": reasons,
                         "params": gate_params(key, c), "gate_json": str(gj),
                         "preserved": c.pop("preserved", None),
                         "elapsed_s": round(elapsed, 1),
                         "at": datetime.now().isoformat(timespec="seconds")})
        if verdict == "PASS" or dry:
            run.mark_done(key, stage_outputs(key, c["name"]), elapsed)
            return EXIT_OK

        # ---- G2r: 재시도하지 않는다 (이상 탐지 지표) ----
        if key == "5-4":
            print("\n[정지] G2r 불합격 — 자동 재시도 대상이 아니다")
            for r in reasons:
                print(f"  - {r}")
            print("\n  스케일 이탈은 이상 탐지 신호다 (9/22 재정의). 같은 입력을 다시 돌려도")
            print("  같은 값이 나온다. 상류를 봐야 한다 — 메쉬 잘림, 부유 지오메트리로 인한")
            print("  높이 부풀음, WHAM 체형 추정 이상.")
            print(f"  판정: {gj}")
            return EXIT_HUMAN

    # ---- 상한 도달 → 사람 개입 ----
    return exhausted(key, c, run)


def gate_params(key, c):
    if key == "S2":
        return {"point": c.get("point")}
    if key == "S3":
        return {"seed": c.get("seed"), "keyframe": str(c.get("keyframe"))}
    return {}


def read_verdict(gate_json: Path, dry, rc):
    """게이트 판정. JSON 을 우선 읽고, 없으면 종료 코드로 판단한다.

    종료 코드만으로도 분기는 되지만(PASS 0 / FAIL 1), 사유를 남기려면 JSON 이 필요하다.
    """
    if dry:
        return "PASS(dry)", []
    if gate_json.exists():
        d = json.loads(gate_json.read_text())
        return d.get("verdict", "?"), d.get("reasons", [])
    return ("PASS" if rc == 0 else "FAIL"), [f"판정 JSON 없음 (종료 코드 {rc})"]


def exhausted(key, c, run: Run):
    """자동 재시도를 다 썼다. 실패가 아니라 정지다 (설계 4절)."""
    hist = json.loads((run.root / "attempts.json").read_text())
    mine = [h for h in hist if h.get("stage") == key]
    print(f"\n[정지] {key} 게이트를 통과하지 못했다 ({len(mine)}회 시도)")
    for h in mine:
        print(f"  시도 {h.get('n')}  {h.get('params')}  {h.get('verdict')}"
              + (f"  {'; '.join(h.get('reasons', []))}" if h.get("reasons") else ""))
    if key == "S2":
        # 좌표를 눈으로 읽을 수 있게 격자 이미지를 만들어 둔다. 사람 개입 지점의
        # 실전 보완이다 — 좌표를 물어보면서 그림을 주지 않으면 답할 수가 없다.
        grid = data("02_sam2", c["name"], "_grid.png")
        rc = run_cmd(build_cmd("sam2", ["python", str(scripts_dir() / "frame_grid.py"),
                                        "--video", str(c["video"]), "--out", str(grid)]),
                     run.logs / "frame_grid.log", False)
        print(f"\n  좌표 격자: {grid}" if rc == 0 else
              f"\n  (격자 생성 실패 — {run.logs / 'frame_grid.log'})")
        print(f"  이 그림에서 대상 몸통의 픽셀 좌표를 읽어:")
        print(f"    python orchestrate.py --name {c['name']} --resume --point <x>,<y>")
        print("  층진 의상(겉옷 안 속옷)이면 단일 포인트로는 어렵다 — listener 사례.")
        print("  다중 포인트는 v1 범위 밖이다 (설계 7절).")
    elif key == "S3":
        print(f"\n  seed 를 바꿔도 같은 실패가 반복됐다. 모델이 이 입력에서 일관되게")
        print("  실패하는 것이라 다른 키프레임을 시도하는 편이 낫다:")
        print(f"    python orchestrate.py --name {c['name']} --resume --keyframe <다른 후보.png>")
        print(f"  후보 목록: {data('02_sam2', c['name'], 'keyframes', 'candidates.json')}")
    print(f"\n  시도 이력: {run.root / 'attempts.json'}")
    return EXIT_HUMAN


def frame_from_name(path):
    """key2_f00006.png → "6". 못 읽으면 None."""
    stem = Path(path).stem
    if "_f" not in stem:
        return None
    tail = stem.rsplit("_f", 1)[1]
    return str(int(tail)) if tail.isdigit() else None


def pick_keyframe(name, dry):
    """candidates.json 의 1위를 고른다.

    선정은 G1a 단계(select_keyframes.py)가 끝냈고 여기서는 그 결과를 읽기만 한다.
    사람이 바꾸려면 --keyframe 으로 덮어쓴다.

    **파일 목록이 아니라 candidates.json 을 읽는다.** 2026-10-08 까지는
    `key1_f*.png` 를 이름순으로 나열해 첫 장을 집었는데, S2 재시도마다 key1 이
    쌓여 있어(char_shuffle 에 4장) 1위가 아닌 것을 집을 수 있었다. 9/30 E2E 에서
    그것이 실제 1위(f60)와 같았던 것은 우연이다.
    """
    kd = data("02_sam2", name, "keyframes")
    if dry:
        return str(kd / "key1_fXXXXX.png"), "XXXXX"
    cj = kd / "candidates.json"
    if not cj.exists():
        return None, None
    top = json.loads(cj.read_text()).get("topk") or []
    if not top:
        return None, None
    frame = int(top[0]["frame"])
    kf = kd / f"key1_f{frame:05d}.png"
    if not kf.exists():
        return None, None
    return str(kf), str(frame)


if __name__ == "__main__":
    sys.exit(main())
