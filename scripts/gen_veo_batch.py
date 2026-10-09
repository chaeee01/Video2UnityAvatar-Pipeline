#!/usr/bin/env python3
"""Veo 3.1 (Gemini API) 로 좀비 동작 영상을 일괄 생성한다 — 파이프라인 입력(G0 앞단) 준비.

ORCHESTRATOR_DESIGN 의 S-1 구상을 수동 스크립트로 먼저 만든 것이다. 엑셀의 프롬프트와
레퍼런스 이미지를 편마다 한 번씩 보내고, 끝나는 즉시 내려받아 ffprobe 로 G0 수치를
잰다. 맥북에서 돈다 (GPU 불필요).

  PY=~/.venvs/veo-batch/bin/python        # 설치: pip install -r scripts/requirements-veo.txt
  X=~/Downloads/generated_video/promptys.xlsx
  R=~/Downloads/generated_video/zombie_reference_images

  $PY gen_veo_batch.py --xlsx $X --refs $R --count-tokens              # 프롬프트 토큰 수
  $PY gen_veo_batch.py --xlsx $X --refs $R --model fast --dry-run      # 요청 설정표만
  $PY gen_veo_batch.py --xlsx $X --refs $R --model fast --ids walker_idle,dog_idle
  $PY gen_veo_batch.py --xlsx $X --refs $R --model fast --mode reference --ids walker_roar

출력 (--out, 기본 ~/data/00_raw):
  <id>__<모델>-<방식>.mp4            예: walker_idle__fast-ff.mp4, walker_roar__fast-ref.mp4
  <id>__<모델>-<방식>.params.json    CONVENTIONS 3절 + 요청 설정·operation·결과·G0 실측
  _refs/<레퍼런스 파일>              입력 이미지 사본 (원본은 건드리지 않는다)
모델 태그는 std · fast, 방식 태그는 ff(시작 프레임) · ref(참조 이미지)다.

동작 규칙:
  - 이어하기: mp4 와 성공 기록이 함께 있으면 건너뛴다. mp4 만 있고 기록이 없거나, 기록된
    프롬프트가 이번 엑셀과 다르면 **멈춘다** — 기존 파일을 덮어쓰지 않는다.
  - 안전 필터 차단·오류는 기록하고 다음 편으로 넘어간다. 오류는 1회만 재시도하고 차단은
    재시도하지 않는다. 429 는 기다렸다 다시 보낸다 (재시도 횟수에 세지 않는다).
  - 생성 요청이 접수된 뒤(operation 이 생긴 뒤) 폴링·다운로드가 실패하면 **재생성하지
    않는다** — 서버에서는 완성돼 과금될 수 있어서다. operation 이름을 기록에 남긴다.
  - 인증·과금·등급 오류는 다음 편도 똑같이 실패하므로 "FATAL_STOP:" 과 원문을 찍고 즉시
    종료한다 (코드 2).
  - API 키는 레포 루트 .env 의 GEMINI_API_KEY 에서 읽고, 출력·기록에 쓰지 않는다.

종료 코드: 0 정상 (차단·오류가 섞여도 0, 요약 표를 본다) · 1 인자 오류 · 2 즉시 중단
(FATAL_STOP — 사람이 봐야 한다, 오케스트레이터의 EXIT_HUMAN 과 같은 값) · 3 토큰 한도 초과
(--count-tokens).
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orchestrate import probe_input  # G0 기준을 한 곳에 둔다  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

MODELS = {"std": "veo-3.1-generate-preview", "fast": "veo-3.1-fast-generate-preview"}
MODE_TAG = {"first_frame": "ff", "reference": "ref"}

# id 접두사 → 레퍼런스 파일. 엑셀의 ref_image 열이 비어 있어 여기서 정한다.
# dog 는 가로 구도인 dog_02 를 쓴다 (dog_01 은 세로 구도).
REF_BY_PREFIX = {
    "walker": "manor_walker_01_v4_1116.png",
    "listener": "manor_listener_01_v4_1116.png",
    "stalker": "manor_stalker_01_v4_1116.png",
    "dog": "dog_02.png",
}

# 엑셀 프롬프트는 웹 UI(10초) 용으로 쓰였다. API 는 1080p 에서 8초만 받으므로 길이 문구만
# 뗀다. 다른 문장은 건드리지 않는다.
PROMPT_SUFFIX = "10 seconds."
PROMPT_TOKEN_LIMIT = 1024  # 공식 문서 Model versions 표의 "Text input 1,024 tokens"

SAFETY_WORDS = ("safety", "responsible ai", "usage guidelines", "violat", "sensitive words")
BILLING_WORDS = ("billing", "free tier", "free_tier", "limit: 0", "paid tier", "upgrade your plan")
FATAL_STATUS = ("PERMISSION_DENIED", "UNAUTHENTICATED", "FAILED_PRECONDITION")

_KEY = ""


class Fatal(Exception):
    """다음 편도 똑같이 실패할 오류 — 배치를 멈춘다."""


class Parser(argparse.ArgumentParser):
    """argparse 기본 오류 코드 2 는 즉시 중단(FATAL_STOP)과 겹친다. 인자 오류는 1 로 낸다."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def scrub(s):
    s = str(s)
    return s.replace(_KEY, "***") if _KEY else s


def log(*a):
    print(time.strftime("%H:%M:%S"), *[scrub(x) for x in a], flush=True)


def load_key():
    env = REPO / ".env"
    if not env.is_file():
        sys.exit(f"[중단] {env} 가 없다")
    for line in env.read_text().splitlines():
        if line.startswith("GEMINI_API_KEY="):
            key = line.split("=", 1)[1].strip().strip("'\"")
            if key:
                return key
    sys.exit("[중단] .env 에 GEMINI_API_KEY 가 없다")


def git_state():
    """실행 시점의 HEAD 와 미커밋 변경 여부 — 어느 코드로 만든 영상인지 기록에 남긴다."""
    def git(*a):
        r = subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"[중단] git {' '.join(a)} 실패: {r.stderr.strip()[:200]}")
        return r.stdout.strip()
    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain"))


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit(f"[중단] PNG 가 아니다: {path}")
    return struct.unpack(">II", head[16:24])


def strip_prompt(raw, rid):
    p = raw.rstrip()
    if not p.endswith(PROMPT_SUFFIX):
        sys.exit(f"[중단] {rid}: 프롬프트가 '{PROMPT_SUFFIX}' 로 끝나지 않는다")
    return p[:-len(PROMPT_SUFFIX)].rstrip()


def read_rows(xlsx):
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)["prompts"]
    it = ws.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(it)][:4]
    if header != ["id", "ref_image", "prompt", "conti"]:
        sys.exit(f"[중단] 엑셀 머리행이 다르다: {header}")
    rows = {}
    for r in it:
        if not r or not r[0]:
            continue
        rid = str(r[0]).strip()
        if rid in rows:
            sys.exit(f"[중단] id 중복: {rid}")
        if not r[2]:
            sys.exit(f"[중단] {rid}: 프롬프트가 비었다")
        rows[rid] = str(r[2])
    return rows


def stem_of(rid, model_tag, mode):
    return f"{rid}__{model_tag}-{MODE_TAG[mode]}"


def build_jobs(args, rows):
    if args.ids:
        ids = [s.strip() for s in args.ids.split(",") if s.strip()]
        missing = [i for i in ids if i not in rows]
        if missing:
            sys.exit(f"[중단] 엑셀에 없는 id: {missing}")
    else:
        ids = list(rows)
    jobs = []
    for rid in ids:
        prefix = rid.split("_")[0]
        if prefix not in REF_BY_PREFIX:
            sys.exit(f"[중단] {rid}: 접두사 '{prefix}' 에 대응하는 레퍼런스가 없다")
        src = args.refs / REF_BY_PREFIX[prefix]
        if not src.is_file():
            sys.exit(f"[중단] 레퍼런스가 없다: {src}")
        w, h = png_size(src)
        stem = stem_of(rid, args.model, args.mode)
        jobs.append({
            "id": rid, "stem": stem,
            "prompt": strip_prompt(rows[rid], rid),
            "ref_src": src, "ref": args.out / "_refs" / src.name, "ref_size": [w, h],
            # Veo 는 16:9 · 9:16 만 받는다. 레퍼런스 구도를 따른다.
            "aspect_ratio": "9:16" if h > w else "16:9",
            "mp4": args.out / f"{stem}.mp4", "json": args.out / f"{stem}.params.json",
        })
    return jobs


def prepare_refs(jobs):
    """레퍼런스를 <out>/_refs 로 복사한다 (이동 아님). 이미 있는데 내용이 다르면 멈춘다."""
    for src, dst in sorted({(j["ref_src"], j["ref"]) for j in jobs}):
        if dst.exists():
            if sha256(dst) != sha256(src):
                sys.exit(f"[중단] {dst} 가 이미 있고 원본과 내용이 다르다 — 덮어쓰지 않는다")
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            log(f"[refs] 복사 {src} → {dst}")


def request_config(args, job):
    return {"aspect_ratio": job["aspect_ratio"], "resolution": args.resolution,
            "duration_seconds": args.duration, "person_generation": "allow_adult",
            "number_of_videos": 1}


def api_error_text(e):
    return f"{getattr(e, 'code', '?')} {getattr(e, 'status', '?')}: {getattr(e, 'message', e)}"


def is_fatal(e):
    msg = str(getattr(e, "message", e)).lower()
    return (getattr(e, "code", None) in (401, 403) or getattr(e, "status", None) in FATAL_STATUS
            or any(w in msg for w in BILLING_WORDS))


def probe(mp4):
    """G0 실측. 프레임·fps·해상도와 판정은 orchestrate.probe_input, 길이만 따로 잰다."""
    m, bad = probe_input(mp4, False)
    if m is None:
        return {"verdict": "FAIL", "reasons": bad}
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(mp4)], capture_output=True, text=True)
    m["duration_s"] = round(float(r.stdout.strip()), 3) if r.returncode == 0 else None
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                        "stream=codec_name", "-of", "csv=p=0", str(mp4)], capture_output=True, text=True)
    m["audio"] = bool(r.stdout.strip()) if r.returncode == 0 else None
    m["verdict"] = "FAIL" if bad else "PASS"
    m["reasons"] = bad
    return m


def attempt(client, types, errors, args, job, cfg):
    """생성 1회. (기록 dict, 재시도해도 되는가) 를 돌려준다."""
    a = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "operation": None, "waits_429": 0}
    image = types.Image.from_file(location=str(job["ref"]))
    kw = dict(cfg)
    if args.mode == "reference":
        kw["reference_images"] = [types.VideoGenerationReferenceImage(image=image, reference_type="asset")]
    call = dict(model=MODELS[args.model], prompt=job["prompt"], config=types.GenerateVideosConfig(**kw))
    if args.mode == "first_frame":
        call["image"] = image

    t0 = time.time()
    wait = 60
    while True:
        try:
            op = client.models.generate_videos(**call)
            break
        except errors.APIError as e:
            text = api_error_text(e)
            if is_fatal(e):
                raise Fatal(text)
            if getattr(e, "code", None) == 429 and a["waits_429"] < args.max_429_waits:
                a["waits_429"] += 1
                log(f"  [{job['stem']}] 429 — {wait}s 대기 ({a['waits_429']}/{args.max_429_waits}): {text[:200]}")
                time.sleep(wait)
                wait = min(wait * 2, 480)
                continue
            a.update(status="error", message=text)
            # 400 은 같은 요청을 다시 보내도 같은 답이 온다
            return a, getattr(e, "code", None) != 400
    a["operation"] = op.name
    log(f"  [{job['stem']}] 접수 {op.name}")

    poll_fail = 0
    while not op.done:
        if time.time() - t0 > args.timeout:
            a.update(status="error", message=f"{args.timeout}s 안에 끝나지 않았다 (operation 은 살아 있을 수 있다)")
            return a, False
        time.sleep(args.poll)
        try:
            op = client.operations.get(op)
            poll_fail = 0
        except Exception as e:  # 접수된 뒤에는 재생성하지 않고 폴링만 다시 한다
            poll_fail += 1
            log(f"  [{job['stem']}] 폴링 실패 {poll_fail}/5: {e}")
            if poll_fail >= 5:
                a.update(status="error", message=f"폴링 5회 연속 실패: {scrub(e)}")
                return a, False
    a["generate_s"] = round(time.time() - t0, 1)

    if op.error:
        msg = json.dumps(op.error, ensure_ascii=False) if isinstance(op.error, dict) else str(op.error)
        blocked = any(w in msg.lower() for w in SAFETY_WORDS)
        a.update(status="blocked" if blocked else "error", message=msg)
        return a, not blocked
    resp = op.response
    vids = (resp.generated_videos or []) if resp else []
    if not vids:
        if resp and resp.rai_media_filtered_count:
            a.update(status="blocked", rai_reasons=resp.rai_media_filtered_reasons,
                     message=f"rai_media_filtered_count={resp.rai_media_filtered_count}")
            return a, False
        a.update(status="error", message="완료됐지만 영상이 없다 (차단 사유도 없다)")
        return a, True

    # 서버 보관은 2일이다. 끝나는 즉시 받는다. 임시 이름으로 받아 완성본만 제자리에 둔다.
    t1 = time.time()
    tmp = job["mp4"].with_name(job["mp4"].name + ".part")
    last = None
    for n in range(3):
        try:
            client.files.download(file=vids[0].video)
            vids[0].video.save(str(tmp))
            last = None
            break
        except Exception as e:
            last = e
            log(f"  [{job['stem']}] 다운로드 실패 {n + 1}/3: {e}")
            time.sleep(10)
    if last is not None:
        a.update(status="error", message=f"다운로드 실패 (2일 안에 operation 으로 회수할 것): {scrub(last)}")
        return a, False
    if job["mp4"].exists():
        raise Fatal(f"{job['mp4']} 가 생성 도중 생겼다 — 덮어쓰지 않는다. 받은 파일은 {tmp}")
    os.replace(tmp, job["mp4"])
    a.update(status="success", download_s=round(time.time() - t1, 1))
    return a, False


def run_one(client, types, errors, args, job, sdk_version, stop):
    """한 편을 끝까지 처리하고 요약 행을 돌려준다."""
    row = {"id": job["id"], "stem": job["stem"], "mode": args.mode, "model": args.model}
    prior = json.loads(job["json"].read_text()) if job["json"].exists() else None
    if job["mp4"].exists():
        if prior and prior.get("result", {}).get("status") == "success":
            if prior.get("prompt") != job["prompt"]:
                raise Fatal(f"{job['mp4']} 의 기록된 프롬프트가 이번 엑셀과 다르다 — 건너뛰지도 "
                            f"덮어쓰지도 않는다. 옛 결과를 옮긴 뒤 다시 실행할 것")
            g0 = prior.get("g0", {})
            row.update(status="skip", g0=g0, total_s=None)
            log(f"[{job['stem']}] 건너뜀 — 이미 있다")
            return row
        raise Fatal(f"{job['mp4']} 가 이미 있는데 이 스크립트의 성공 기록이 없다 — 덮어쓰지 않는다")
    if stop.is_set():
        row.update(status="not_run", g0={}, total_s=None)
        return row

    cfg = request_config(args, job)
    log(f"[{job['stem']}] 생성 시작 — {MODELS[args.model]} {args.mode} {cfg['aspect_ratio']} {cfg['resolution']}")
    t0 = time.time()
    attempts = list(prior.get("attempts", [])) if prior else []
    for n in range(2):  # 오류 재시도는 1회까지
        a, retry = attempt(client, types, errors, args, job, cfg)
        attempts.append(a)
        log(f"  [{job['stem']}] {a['status']}" + (f" — {a.get('message')}" if a["status"] != "success" else ""))
        if a["status"] == "success" or not retry or n == 1:
            break
        log(f"  [{job['stem']}] 재시도 1회")
    g0 = probe(job["mp4"]) if a["status"] == "success" else {}
    total = round(time.time() - t0, 1)
    params = {
        "name": job["stem"],
        "inputs": [str(args.xlsx), str(job["ref"])],
        "xlsx_sha256": args.xlsx_sha256,
        "id": job["id"],
        "model": MODELS[args.model],
        "mode": args.mode,
        "prompt": job["prompt"],
        "prompt_removed_suffix": PROMPT_SUFFIX,
        "ref_image": str(job["ref"]),
        "ref_image_source": str(job["ref_src"]),
        "ref_image_sha256": sha256(job["ref"]),
        "ref_image_size": job["ref_size"],
        "request": cfg,
        "operation": a.get("operation"),
        "result": {k: a[k] for k in ("status", "message", "rai_reasons") if k in a},
        "attempts": attempts,
        "output": str(job["mp4"]) if a["status"] == "success" else None,
        "g0": g0,
        "google_genai": sdk_version,
        "git_commit": args.git_commit,
        "git_dirty": args.git_dirty,
        "time_s": {"generate": a.get("generate_s"), "download": a.get("download_s"), "total": total},
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    job["json"].write_text(scrub(json.dumps(params, indent=2, ensure_ascii=False)) + "\n")
    if g0:
        log(f"  [{job['stem']}] G0 {g0.get('verdict')} — {g0.get('frames')}프레임 {g0.get('fps')}fps "
            f"{g0.get('width')}x{g0.get('height')} {g0.get('duration_s')}s 오디오 {g0.get('audio')}")
    row.update(status=a["status"], g0=g0, total_s=total, message=a.get("message"))
    return row


def print_plan(args, jobs):
    print(f"\n요청 설정표 — {len(jobs)}편 (생성 요청은 보내지 않았다)")
    print("| 출력 파일 | model | mode | 이미지 전달 | aspectRatio | resolution | durationSeconds "
          "| personGeneration | 레퍼런스 (WxH) | 프롬프트 글자 수 | 이미 있음 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for j in jobs:
        c = request_config(args, j)
        how = "image" if args.mode == "first_frame" else "referenceImages[asset] x1"
        print(f"| {j['mp4'].name} | {MODELS[args.model]} | {args.mode} | {how} | {c['aspect_ratio']} "
              f"| {c['resolution']} | {c['duration_seconds']} | {c['person_generation']} "
              f"| {j['ref'].name} ({j['ref_size'][0]}x{j['ref_size'][1]}) | {len(j['prompt'])} "
              f"| {'예' if j['mp4'].exists() else '아니오'} |")


def count_tokens(client, args, rows):
    """Veo 는 countTokens 를 지원하지 않아 Gemini 텍스트 모델의 토크나이저로 잰다 — 근사다."""
    print(f"\n토큰 수 — 모델 {args.token_model}, '{PROMPT_SUFFIX}' 제거 후, 한도 {PROMPT_TOKEN_LIMIT}")
    print("| id | 글자 수 | 토큰 수 |")
    print("|---|---|---|")
    out = []
    for rid, raw in rows.items():
        p = strip_prompt(raw, rid)
        n = client.models.count_tokens(model=args.token_model, contents=p).total_tokens
        out.append((rid, len(p), n))
        print(f"| {rid} | {len(p)} | {n} |", flush=True)
    top = max(out, key=lambda x: x[2])
    over = [o for o in out if o[2] > PROMPT_TOKEN_LIMIT]
    print(f"\n최댓값: {top[0]} {top[2]}토큰 ({top[1]}자) · 최솟값: {min(o[2] for o in out)}토큰 · {len(out)}편")
    if over:
        print(f"[중단] 한도 초과 {len(over)}편: {[o[0] for o in over]}")
        sys.exit(3)
    print("한도 초과 없음")


def main():
    global _KEY
    ap = Parser(description=__doc__.split("\n")[0])
    ap.add_argument("--xlsx", type=Path, required=True, help="프롬프트 엑셀 (시트 prompts)")
    ap.add_argument("--refs", type=Path, required=True, help="레퍼런스 이미지 폴더")
    ap.add_argument("--out", type=Path, default=Path("~/data/00_raw"), help="출력 폴더 (기본 ~/data/00_raw)")
    ap.add_argument("--model", choices=sorted(MODELS), help="std=Veo 3.1, fast=Veo 3.1 Fast (생성 시 필수)")
    ap.add_argument("--mode", choices=sorted(MODE_TAG), default="first_frame",
                    help="first_frame=레퍼런스를 시작 프레임으로, reference=참조 이미지로")
    ap.add_argument("--ids", help="쉼표로 구분한 id. 생략하면 엑셀 전체")
    ap.add_argument("--resolution", default="1080p", choices=["720p", "1080p"])
    ap.add_argument("--duration", type=int, default=8, choices=[4, 6, 8],
                    help="1080p 와 reference 는 8초만 된다")
    ap.add_argument("--concurrency", type=int, default=1)
    ap.add_argument("--poll", type=int, default=10, help="폴링 간격(초)")
    ap.add_argument("--timeout", type=int, default=900, help="편당 생성 대기 한도(초)")
    ap.add_argument("--max-429-waits", type=int, default=5, help="편당 429 대기 횟수 한도")
    ap.add_argument("--dry-run", action="store_true", help="요청 설정표만 찍는다. 아무것도 쓰지 않는다")
    ap.add_argument("--count-tokens", action="store_true", help="전 편 프롬프트 토큰 수만 잰다 (무과금)")
    ap.add_argument("--token-model", default="gemini-3.8-flash", help="countTokens 에 쓸 모델")
    args = ap.parse_args()
    args.xlsx = args.xlsx.expanduser().resolve()
    args.refs = args.refs.expanduser().resolve()
    args.out = args.out.expanduser().resolve()

    rows = read_rows(args.xlsx)
    if not args.count_tokens:
        if not args.model:
            ap.error("--model 이 필요하다")
        if args.duration != 8 and (args.resolution == "1080p" or args.mode == "reference"):
            ap.error("1080p 와 reference 는 --duration 8 만 된다")
        jobs = build_jobs(args, rows)
        if args.dry_run:
            print_plan(args, jobs)
            return

    warnings.filterwarnings("ignore")  # google-auth 의 Python 3.9 EOL 경고가 로그를 덮는다
    from google import genai
    from google.genai import errors, types
    _KEY = load_key()
    client = genai.Client(api_key=_KEY)

    if args.count_tokens:
        count_tokens(client, args, rows)
        return

    args.git_commit, args.git_dirty = git_state()
    args.xlsx_sha256 = sha256(args.xlsx)
    args.out.mkdir(parents=True, exist_ok=True)
    prepare_refs(jobs)
    log(f"시작 — {len(jobs)}편, {MODELS[args.model]}, {args.mode}, 동시 {args.concurrency}, "
        f"HEAD {args.git_commit[:7]}{' (dirty)' if args.git_dirty else ''}")
    stop = threading.Event()
    fatal = []

    def guarded(job):
        try:
            return run_one(client, types, errors, args, job, genai.__version__, stop)
        except Fatal as e:
            stop.set()
            fatal.append(scrub(e))
            log(f"FATAL_STOP: [{job['stem']}] {e}")
            return {"id": job["id"], "stem": job["stem"], "mode": args.mode, "model": args.model,
                    "status": "fatal", "g0": {}, "total_s": None, "message": scrub(e)}

    with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        results = list(ex.map(guarded, jobs))

    print("\n| id | model | mode | 결과 | 프레임 수 | fps | 해상도 | 길이(s) | G0 | 소요(s) |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        g = r["g0"]
        res = f"{g.get('width')}x{g.get('height')}" if g.get("width") else "-"
        print(f"| {r['id']} | {r['model']} | {r['mode']} | {r['status']} | {g.get('frames', '-')} "
              f"| {g.get('fps', '-')} | {res} | {g.get('duration_s', '-')} | {g.get('verdict', '-')} "
              f"| {r['total_s'] if r['total_s'] is not None else '-'} |")
    for label, key in (("안전 필터 차단", "blocked"), ("오류", "error")):
        hit = [r for r in results if r["status"] == key]
        if hit:
            print(f"\n{label} {len(hit)}편:")
            for r in hit:
                print(f"  {r['stem']}: {scrub(r.get('message'))}")
    g0_fail = [r for r in results if r["g0"].get("verdict") == "FAIL"]
    if g0_fail:
        print(f"\nG0 미달 {len(g0_fail)}편:")
        for r in g0_fail:
            print(f"  {r['stem']}: {r['g0'].get('reasons')}")
    if fatal:
        print(f"\nFATAL_STOP: {fatal[0]}", flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
