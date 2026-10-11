"""gen_veo_batch 의 요청 조립·판정 로직 시험 — API 를 부르지 않는다.

  A. 프롬프트 전처리 — 끝의 "10 seconds." 만 떼고 나머지는 한 글자도 바꾸지 않는가.
  B. 요청 조립 — 접두사별 레퍼런스·비율·출력 이름이 맞는가 (임시 PNG 로 만든다).
  C. 오류 분류 — 인증·과금 오류는 FATAL, "quota" 가 든 429 는 QUOTA, 일반 429·400 은 계속.
  D. 이어하기 — 기록 없는 mp4, 프롬프트가 바뀐 mp4 를 만나면 덮어쓰지 않고 멈추는가.
  E. 종료 코드 — 인자 오류가 1 로 나가는가 (2 는 즉시 중단 전용).
  F. --daily-cap — 한도만큼만 보내고, 이미 있는 편은 세지 않으며, 재시도도 1건으로 세는가.

실제 생성(과금)은 시험하지 않는다. 그것은 시험 5편으로 사람이 본다.
"""
import argparse
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import gen_veo_batch as g


def png(path, w, h):
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h))


class Err(Exception):
    def __init__(self, code, status, message):
        self.code, self.status, self.message = code, status, message


def run_prompt():
    body = "Plain motion reference footage.  Two  spaces kept. No other objects."
    cases = [
        ("끝 문구 제거", body + " 10 seconds.", body),
        ("뒤 공백·개행", body + " 10 seconds. \n", body),
        ("본문 안의 10 seconds 는 보존", "Holds for 10 seconds. Then stops. 10 seconds.", "Holds for 10 seconds. Then stops."),
    ]
    ok = 0
    for name, raw, expect in cases:
        good = g.strip_prompt(raw, "t") == expect
        ok += good
        print(f"   {name:28s} {'✅' if good else '❌'}")
    try:
        g.strip_prompt(body, "t")
        print(f"   {'끝 문구 없음 → 중단':28s} ❌ (통과시켰다)")
    except SystemExit:
        ok += 1
        print(f"   {'끝 문구 없음 → 중단':28s} ✅")
    return ok == len(cases) + 1


def make_args(tmp, **kw):
    refs = Path(tmp) / "refs"
    refs.mkdir(exist_ok=True)
    for name in g.REF_BY_PREFIX.values():
        png(refs / name, *((2752, 1536) if name.startswith("dog") else (1116, 2000)))
    d = dict(ids=None, model="fast", mode="first_frame", refs=refs, out=Path(tmp) / "out",
             resolution="1080p", duration=8, xlsx=Path(tmp) / "p.xlsx",
             git_commit="0" * 40, git_dirty=False, xlsx_sha256="0" * 64,
             daily_cap=None, budget=g.Budget(None))
    d.update(kw)
    return argparse.Namespace(**d)


def run_jobs(tmp):
    rows = {i: "x. 10 seconds." for i in ("walker_idle", "listener_roar_02", "stalker_attack", "dog_idle")}
    expect = {"walker_idle": ("manor_walker_01_v4_1116.png", "9:16"),
              "listener_roar_02": ("manor_listener_01_v4_1116.png", "9:16"),
              "stalker_attack": ("manor_stalker_01_v4_1116.png", "9:16"),
              "dog_idle": ("dog_02.png", "16:9")}
    ok = True
    for j in g.build_jobs(make_args(tmp), rows):
        good = (j["ref"].name, j["aspect_ratio"]) == expect[j["id"]] and j["ref"].parent.name == "_refs"
        ok &= good
        print(f"   {j['id']:18s} {j['ref'].name:32s} {j['aspect_ratio']:5s} {'✅' if good else '❌'}")
    names = {(m, mode): g.build_jobs(make_args(tmp, model=m, mode=mode, ids="walker_idle"), rows)[0]["mp4"].name
             for m in ("fast", "std") for mode in ("first_frame", "reference")}
    good = (names[("fast", "first_frame")] == "walker_idle__fast-ff.mp4"
            and names[("std", "first_frame")] == "walker_idle__std-ff.mp4"
            and names[("fast", "reference")] == "walker_idle__fast-ref.mp4"
            and len(set(names.values())) == 4)
    print(f"   {'출력 이름 4조합이 서로 다르다':40s} {'✅' if good else '❌'}")
    return ok and good


def classify(e):
    """attempt() 와 같은 순서: quota 가 먼저다."""
    return "QUOTA" if g.is_quota(e) else "FATAL" if g.is_fatal(e) else "계속"


def run_fatal():
    # 2026-10-11 본생성 11번째 요청이 받은 원문
    real = ("You exceeded your current quota, please check your plan and billing details. For more "
            "information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits.")
    cases = [
        ("403 PERMISSION_DENIED", Err(403, "PERMISSION_DENIED", "denied"), "FATAL"),
        ("401", Err(401, "UNAUTHENTICATED", "API key not valid"), "FATAL"),
        ("400 FAILED_PRECONDITION", Err(400, "FAILED_PRECONDITION", "enable billing"), "FATAL"),
        ("403 인데 quota 문구", Err(403, "PERMISSION_DENIED", "quota project not set"), "FATAL"),
        ("429 일일 한도 (10/11 원문)", Err(429, "RESOURCE_EXHAUSTED", real), "QUOTA"),
        ("429 Quota exceeded", Err(429, "RESOURCE_EXHAUSTED", "Quota exceeded for metric ..."), "QUOTA"),
        ("429 quota 문구 없음", Err(429, "RESOURCE_EXHAUSTED", "Too many requests, slow down."), "계속"),
        ("400 INVALID_ARGUMENT", Err(400, "INVALID_ARGUMENT", "resolution not supported"), "계속"),
        ("500", Err(500, "INTERNAL", "internal error"), "계속"),
    ]
    ok = 0
    for name, e, expect in cases:
        good = classify(e) == expect
        ok += good
        print(f"   {name:28s} 기대 {expect:5s}  {'✅' if good else '❌'}")
    return ok == len(cases)


def run_resume(tmp):
    args = make_args(tmp, ids="walker_idle")
    job = g.build_jobs(args, {"walker_idle": "x. 10 seconds."})[0]
    args.out.mkdir(exist_ok=True)
    job["mp4"].write_bytes(b"foreign")
    stop = threading.Event()
    try:
        g.run_one(None, None, None, args, job, "t", stop)
        a = False
    except g.Fatal:
        a = job["mp4"].read_bytes() == b"foreign"
    print(f"   {'기록 없는 mp4 → 중단, 파일 그대로':40s} {'✅' if a else '❌'}")
    rec = {"result": {"status": "success"}, "g0": {"frames": 192}, "prompt": job["prompt"]}
    job["json"].write_text(json.dumps(rec))
    r = g.run_one(None, None, None, args, job, "t", stop)
    b = r["status"] == "skip" and job["mp4"].read_bytes() == b"foreign"
    print(f"   {'성공 기록 + 같은 프롬프트 → 건너뜀':40s} {'✅' if b else '❌'}")
    rec["prompt"] = "turned about 45 degrees."
    job["json"].write_text(json.dumps(rec))
    try:
        g.run_one(None, None, None, args, job, "t", stop)
        c = False
    except g.Fatal:
        c = job["mp4"].read_bytes() == b"foreign" and json.loads(job["json"].read_text()) == rec
    print(f"   {'성공 기록 + 다른 프롬프트 → 중단, 파일·기록 그대로':40s} {'✅' if c else '❌'}")
    return a and b and c


def run_exit_code():
    script = os.path.join(os.path.dirname(__file__), "..", "scripts", "gen_veo_batch.py")
    cases = [("필수 인자 누락", []), ("없는 선택지", ["--xlsx", "x", "--refs", "r", "--model", "nope"])]
    ok = 0
    for name, argv in cases:
        r = subprocess.run([sys.executable, script] + argv, capture_output=True, text=True)
        good = r.returncode == 1 and "FATAL_STOP" not in r.stdout + r.stderr
        ok += good
        print(f"   {name:28s} 종료 코드 {r.returncode}  {'✅' if good else '❌'}")
    return ok == len(cases)


def run_daily_cap(tmp):
    """attempt() 를 가짜로 바꿔 API 없이 한도 계산만 본다."""
    ids = ["walker_idle", "walker_idle_02", "walker_walk_fwd", "walker_run_fwd", "walker_roar"]
    rows = {i: "x. 10 seconds." for i in ids}
    real_attempt, real_probe = g.attempt, g.probe
    calls = []

    def fake_attempt(client, types, errors, args, job, cfg):
        calls.append(job["id"])
        if job["id"] == "walker_walk_fwd" and calls.count(job["id"]) == 1:
            return {"status": "error", "message": "500", "operation": "op", "waits_429": 0}, True
        job["mp4"].write_bytes(b"v")
        return {"status": "success", "operation": "op", "waits_429": 0}, False

    g.attempt, g.probe = fake_attempt, lambda mp4: {"verdict": "PASS", "frames": 192}
    try:
        out = Path(tmp) / "cap"
        out.mkdir()
        args = make_args(tmp, out=out, daily_cap=3, budget=g.Budget(3))
        jobs = g.build_jobs(args, rows)
        (out / "_refs").mkdir()
        for j in jobs:
            j["ref"].write_bytes(j["ref_src"].read_bytes())
        # 첫 편은 이미 있다 — 한도에 세지 않아야 한다
        jobs[0]["mp4"].write_bytes(b"v")
        jobs[0]["json"].write_text(json.dumps({"result": {"status": "success"}, "prompt": jobs[0]["prompt"], "g0": {}}))
        stop = threading.Event()
        st = [g.run_one(None, None, None, args, j, "t", stop)["status"] for j in jobs]
    finally:
        g.attempt, g.probe = real_attempt, real_probe
    # idle=skip, idle_02=1건, walk_fwd=오류+재시도 2건 → 한도 3 소진, 나머지 not_run
    expect = ["skip", "success", "success", "not_run", "not_run"]
    a = st == expect
    b = calls == ["walker_idle_02", "walker_walk_fwd", "walker_walk_fwd"] and args.budget.sent == 3
    c = not jobs[3]["mp4"].exists() and not jobs[3]["json"].exists()
    print(f"   {'한도 3: ' + ' '.join(st):60s} {'✅' if a else '❌'}")
    print(f"   {'건너뛴 편은 세지 않고 재시도는 1건으로 센다':40s} {'✅' if b else '❌'}")
    print(f"   {'안 보낸 편은 파일·기록이 없다':40s} {'✅' if c else '❌'}")
    bud = g.Budget(1)
    d = bud.take() and not bud.take()
    bud.give_back()
    d = d and bud.take()
    print(f"   {'접수 전 거절은 되돌린다':40s} {'✅' if d else '❌'}")
    return a and b and c and d


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        print("A. 프롬프트 전처리")
        a = run_prompt()
        print("B. 요청 조립")
        b = run_jobs(tmp)
        print("C. 치명 오류 판정")
        c = run_fatal()
        print("D. 이어하기")
        d = run_resume(tmp)
        print("E. 종료 코드")
        e = run_exit_code()
        print("F. --daily-cap")
        f = run_daily_cap(tmp)
    good = a and b and c and d and e and f
    print(f"\n{'✅ 전체 통과' if good else '❌ 실패 있음'}")
    sys.exit(0 if good else 1)
