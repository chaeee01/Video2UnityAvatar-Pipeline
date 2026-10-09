"""gen_veo_batch 의 요청 조립·판정 로직 시험 — API 를 부르지 않는다.

  A. 프롬프트 전처리 — 끝의 "10 seconds." 만 떼고 나머지는 한 글자도 바꾸지 않는가.
  B. 요청 조립 — 접두사별 레퍼런스·비율·출력 이름이 맞는가 (임시 PNG 로 만든다).
  C. 치명 오류 판정 — 인증·과금 오류는 멈추고, 일반 429·400 은 멈추지 않는가.
  D. 이어하기 — 기록 없는 mp4 를 만나면 덮어쓰지 않고 멈추는가.

실제 생성(과금)은 시험하지 않는다. 그것은 시험 5편으로 사람이 본다.
"""
import argparse
import json
import os
import struct
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
             git_commit="0" * 40, git_dirty=False)
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


def run_fatal():
    cases = [
        ("403 PERMISSION_DENIED", Err(403, "PERMISSION_DENIED", "denied"), True),
        ("401", Err(401, "UNAUTHENTICATED", "API key not valid"), True),
        ("400 FAILED_PRECONDITION", Err(400, "FAILED_PRECONDITION", "enable billing"), True),
        ("429 무료 등급", Err(429, "RESOURCE_EXHAUSTED", "Quota exceeded ... free_tier_requests, limit: 0"), True),
        ("429 일반 속도 제한", Err(429, "RESOURCE_EXHAUSTED", "Resource has been exhausted (e.g. check quota)."), False),
        ("400 INVALID_ARGUMENT", Err(400, "INVALID_ARGUMENT", "resolution not supported"), False),
        ("500", Err(500, "INTERNAL", "internal error"), False),
    ]
    ok = 0
    for name, e, expect in cases:
        good = g.is_fatal(e) == expect
        ok += good
        print(f"   {name:28s} 기대 {'중단' if expect else '계속'}  {'✅' if good else '❌'}")
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
    job["json"].write_text(json.dumps({"result": {"status": "success"}, "g0": {"frames": 192}}))
    r = g.run_one(None, None, None, args, job, "t", stop)
    b = r["status"] == "skip" and job["mp4"].read_bytes() == b"foreign"
    print(f"   {'성공 기록 있는 mp4 → 건너뜀':40s} {'✅' if b else '❌'}")
    return a and b


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
    good = a and b and c and d
    print(f"\n{'✅ 전체 통과' if good else '❌ 실패 있음'}")
    sys.exit(0 if good else 1)
