# -*- coding: utf-8 -*-
"""공개 페이지 소재 조립 — 원본을 웹용으로 인코딩해 site/assets/ 에 두고 manifest.json · manifest.md 를 쓴다.
  python3 tools/site/site_assemble.py <레포 루트>        (SITE_RAW=<생성 매체 폴더>, 기본 ~/data/site_raw_1106)
생성 매체: tools/site/site_mesh_overlay.py (WHAM 정점 투영 — SMPL 모델 없이) · site_render_glb.py (TRELLIS.2 GLB 정지 · 턴테이블).
원본 경로는 맥 로컬(~/data, ~/Desktop/3D_avatar_work/experiments/e2e_check, docs/assets) — 레포에는 웹용 결과만 넣는다.
영상: mp4 H.264 · 높이 540 · CRF 28 · 최대 6초 · 무음 · faststart. 스틸: JPEG q80 · 긴 변 1200px 이하."""
import hashlib, json, os, subprocess, sys

REPO = sys.argv[1]
OUT = os.path.join(REPO, "site", "assets")
H = os.path.expanduser("~")
X = os.environ.get("SITE_RAW", f"{H}/data/site_raw_1106")   # site_mesh_overlay.py · site_render_glb.py 산출물
E = f"{H}/Desktop/3D_avatar_work/experiments/e2e_check"
R = f"{REPO}/docs/assets"
D = f"{H}/data"

# (id, 종류, 원본, 캐릭터, 단계, 캡션, 전후 쌍(그룹, 역할) 또는 None, 시작 초)
ITEMS = [
    ("pipeline_v4", "image", f"{R}/pipeline_v4.png", "-", "개요", "파이프라인 v4 — 영상 한 편에서 외형(TRELLIS.2)과 동작(WHAM)을 따로 뽑아 SMPL 골격 하나로 합친다", None, 0),
    ("lineup_meshes", "image", f"{X}/lineup10.png", "walker · listener · stalker · lurker · oiler · dog · player_01~04", "S3 외형", "납품 캐릭터 10종의 TRELLIS 메쉬 — 좀비 6종(위 5 · 아래 첫 칸 dog) 뒤에 플레이어 4종 (정면, 같은 조명)", None, 0),
    ("input_ref_walker", "image", f"{D}/00_raw/_refs_clean/manor_walker_01_v4_1116_clean.png", "walker", "입력", "입력 ① 캐릭터 참조 이미지 (영상 생성의 시작 프레임)", None, 0),
    ("input_video_walker", "video", f"{D}/00_raw/walker_walk_02__fast-ff.mp4", "walker", "입력", "입력 ② 생성 영상 — 걷기 (9:16, 24fps)", None, 0),
    ("s2_mask_walker", "video", f"{D}/02_sam2/walker_walk_02/walker_walk_02_masked.mp4", "walker", "S2 분할", "SAM2 마스크 — 배경을 지우고 몸만 남긴 클립을 다음 단계로 넘긴다", None, 0),
    ("s5_wham_overlay_walker", "video", f"{X}/walker_wham_mesh_overlay.mp4", "walker", "S5 동작", "WHAM 이 추정한 3D 몸(SMPL 정점)을 원본 영상에 투영 — 프레임마다 자세 · 위치를 복원", None, 0),
    ("s3_mesh_walker_turntable", "video", f"{X}/turn_walker_v/f_%04d.png", "walker", "S3 외형", "TRELLIS.2 메쉬 턴테이블 — 키프레임 한 장에서 만든 PBR 메쉬 (세로 9:16, 회전 전체에서 전신이 보이게 카메라 맞춤)", None, 0),
    ("s3_mesh_walker", "image", f"{X}/mesh_walker.png", "walker", "S3 외형", "walker 메쉬", None, 0),
    ("s3_mesh_listener", "image", f"{X}/mesh_listener.png", "listener", "S3 외형", "listener 메쉬", None, 0),
    ("s3_mesh_stalker", "image", f"{X}/mesh_stalker.png", "stalker", "S3 외형", "stalker 메쉬", None, 0),
    ("s3_mesh_lurker", "image", f"{X}/mesh_lurker.png", "lurker", "S3 외형", "lurker 메쉬", None, 0),
    ("s3_mesh_oiler", "image", f"{X}/mesh_oiler.png", "oiler", "S3 외형", "oiler 메쉬", None, 0),
    ("s3_mesh_player_01", "image", f"{X}/mesh_player_01.png", "player_01", "S3 외형", "플레이어 캐릭터 1 메쉬 (char1.glb)", None, 0),
    ("s3_mesh_player_02", "image", f"{X}/mesh_player_02.png", "player_02", "S3 외형", "플레이어 캐릭터 2 메쉬 (char2.glb)", None, 0),
    ("s3_mesh_player_03", "image", f"{X}/mesh_player_03.png", "player_03", "S3 외형", "플레이어 캐릭터 3 메쉬 (char3.glb) — 구 s3_mesh_player(player_apose)와 같은 캐릭터", None, 0),
    ("s3_mesh_player_04", "image", f"{X}/mesh_player_04.png", "player_04", "S3 외형", "플레이어 캐릭터 4 메쉬 (char4.glb) — 구 s3_mesh_char_shuffle 과 같은 캐릭터", None, 0),
    ("s3_mesh_dog", "image", f"{X}/mesh_dog.png", "dog", "S3 외형", "dog 메쉬 (골격 · 동작은 Mixamo)", None, 0),
    ("s4_align_walker", "image", f"{R}/align_check_frame.png", "walker", "S4 리깅", "SMPL 몸을 TRELLIS 메쉬에 정렬한 결과 — 골격이 메쉬 안에 들어오는지 확인", None, 0),
    ("s4_transfer_walker", "image", f"{R}/transfer_constraint_f138.png", "walker", "S4 리깅", "웨이트 전이의 부위 제약 — 팔 · 다리가 서로 붙지 않게", None, 0),
    ("bake_walker_hit", "video", f"{X}/bake_walker_hit_eq.mp4", "walker", "S7 결합", "원본 영상(왼쪽)과 리그에 구운 동작(오른쪽, 고해상도 재렌더에서 원본과 같은 몸 키 · 발 높이 창을 잘라냄) — 리타게팅 없이 같은 SMPL 골격", None, 0),
    ("unity_ingame_1", "video", f"{H}/Downloads/sweetpotato_20261105.mov", "walker", "Unity · 게임", "실제 게임 내 플레이 장면 — 플레이어 시점, 워커가 다가와 피격 · 쓰러짐 (16:34~16:39)", None, 994, 5, 30),
    ("unity_ingame_2", "video", f"{H}/Downloads/sweetpotato_20261105.mov", "walker", "Unity · 게임", "실제 게임 내 플레이 장면 — 쓰러진 워커가 일어나 걷기 (16:22~16:28)", None, 982, 6, 30),
    ("unity_ingame_3", "video", f"{H}/Downloads/sweetpotato_20261105.mov", "listener · walker", "Unity · 게임", "실제 게임 내 플레이 장면 — 리스너와 워커, 가격 · 쓰러짐 (15:57~16:02)", None, 957, 5, 30),
    ("unity_ingame_4", "video", f"{H}/Downloads/sweetpotato_20261105.mov", "stalker", "Unity · 게임", "실제 게임 내 플레이 장면 — 스토커 접근 · 피격 · 쓰러짐 (21:32.5~21:38.5, 21:30~21:40 중 하이라이트)", None, 1292.5, 6, 30),
    ("ba_weight_listener", "video", f"{E}/review_1021/05_collar/collar_attack_original_wfix_c10.mp4", "listener", "문제 해결 · 웨이트", "가랑이 · 겨드랑이 · 쇄골 경계 스무딩 — 원본 | 1차 수리 | 쇄골 추가 수리", ("weight_smoothing", "both — 가운데 before · 오른쪽 after (왼쪽은 원본 영상)"), 0),
    ("ba_weight_listener_still", "image", f"{E}/review_1021/05_collar/collar_attack_f163_f96_wfix_vs_c10.png", "listener", "문제 해결 · 웨이트", "늘어난 막이 사라진 프레임 비교 (f163 · f96)", ("weight_smoothing", "both — 왼쪽 before · 오른쪽 after"), 0),
    ("ba_weight_walker", "video", f"{E}/review_1021/07_walker/walker_attack_cur_vs_arm20.mp4", "walker", "문제 해결 · 웨이트", "walker 겨드랑이 스무딩 — 팔을 들 때 옆구리 막", ("weight_smoothing", "both — 왼쪽 before · 오른쪽 after"), 0),
    ("ba_slide_listener", "video", f"{E}/review_1019/01_listener_run_slide/compare_L04b_M_stalker_R_transplant.mp4", "listener · stalker", "문제 해결 · 미끄러짐", "달리기 미끄러짐 — 발이 뒤로 쓸리지 않던 판 | stalker 동작 | listener 리그에 이식한 판", ("foot_slide", "both — 왼쪽 before · 오른쪽 after (가운데는 동작 출처)"), 0),
    ("ba_slide_listener_still", "image", f"{X}/slide_still_row.png", "listener", "문제 해결 · 미끄러짐", "디딘 발 위치 비교 클로즈업 (4장, 패널 좌우 여백을 잘라 한 줄)", ("foot_slide", "both — 왼쪽 before · 오른쪽 after"), 0),
    ("ba_floor_walker", "video", f"{E}/review_1026/09_ga_replace/walker_idle_lurch_전후.mp4", "walker", "문제 해결 · 바닥", "바닥 정렬 — 깊이 숙일 때 몸 전체가 바닥 아래로 내려가던 것", ("floor_align", "both — 왼쪽 before · 오른쪽 after"), 2.5),
    ("ba_floor_stalker", "video", f"{E}/review_1026/09_ga_replace/stalker_crawl_loop_전후.mp4", "stalker", "문제 해결 · 바닥", "바닥 정렬 — 엎드린 몸이 바닥에서 떠 있던 것", ("floor_align", "both — 왼쪽 before · 오른쪽 after"), 0),
    ("ba_gait_stalker", "video", f"{E}/review_1102/09_sweeptest/원본_walk01_walk01s_run01_run01s.mp4", "stalker", "문제 해결 · 보행", "프롬프트 한 줄의 효과 — 걷기 | 걷기+러닝머신 문장 | 달리기 | 달리기+러닝머신 문장 (쓸기 −0.26 → −0.57, 대신 자세가 바뀜)", ("gait_prompt", "both — 각 쌍의 왼쪽 before · 오른쪽 after"), 3),
]

# 항목별 인코딩 예외 — 표시 폭이 줄어든 구조도 · 세로 영상은 선명도 우선, 라인업은 10칸이라 긴 변을 늘린다
OPTS = {
    "pipeline_v4": {"width": 1400, "q": 88},
    "lineup_meshes": {"long": 1600, "q": 85},
    "input_video_walker": {"h": 720, "crf": 26},
    "s2_mask_walker": {"h": 720, "crf": 26},
    "s5_wham_overlay_walker": {"h": 720, "crf": 26},
    "s3_mesh_walker_turntable": {"h": 720, "crf": 26},
    "bake_walker_hit": {"h": 720, "crf": 26},
}
REPLACES = {"s3_mesh_player_03": "assets/s3_mesh_player.jpg", "s3_mesh_player_04": "assets/s3_mesh_char_shuffle.jpg"}

def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"실패: {' '.join(cmd[:6])} …\n{r.stderr[-400:]}")

def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height", "-of", "csv=p=0", path], capture_output=True, text=True)
    w, h = r.stdout.strip().split("\n")[0].split(",")[:2]
    return int(w), int(h)

os.makedirs(OUT, exist_ok=True)
man = []
for it in ITEMS:
    iid, kind, src, char, stage, cap, pair, ss = it[:8]
    dur = it[8] if len(it) > 8 else 6
    fps = it[9] if len(it) > 9 else None
    o = OPTS.get(iid, {})
    if kind == "video":
        dst = f"{OUT}/{iid}.mp4"
        inp = ["-framerate", "24", "-i", src] if "%04d" in src else ["-ss", str(ss), "-i", src]
        vf = (f"fps={fps}," if fps else "") + f"scale=-2:{o.get('h', 540)},format=yuv420p"
        sh(["ffmpeg", "-y", "-loglevel", "error", *inp, "-t", str(dur), "-vf", vf, "-c:v", "libx264", "-crf", str(o.get("crf", 28)), "-preset", "slow", "-an", "-movflags", "+faststart", dst])
    else:
        dst = f"{OUT}/{iid}.jpg"
        size = ["--resampleWidth", str(o["width"])] if "width" in o else ["-Z", str(o.get("long", 1200))]
        sh(["sips", "-s", "format", "jpeg", "-s", "formatOptions", str(o.get("q", 80)), *size, src, "--out", dst])
    w, h = probe(dst)
    srcp = src.replace(H, "~")
    man.append({"id": iid, "file": f"assets/{os.path.basename(dst)}", "kind": kind, "width": w, "height": h,
                "bytes": os.path.getsize(dst), "sha256_16": hashlib.sha256(open(dst, "rb").read()).hexdigest()[:16],
                "source": srcp, "character": char, "stage": stage, "caption": cap,
                "pair": {"group": pair[0], "role": pair[1]} if pair else None,
                "placeholder": False, "encoding_override": o or None, "replaces": REPLACES.get(iid)})
    print(f"{iid:28s} {kind:5s} {w}x{h} {os.path.getsize(dst)/1e6:.2f} MB")

tot = sum(m["bytes"] for m in man)
json.dump({"generated": "2026-11-06", "encoding": {"video": "H.264 mp4, height 540, CRF 28, ≤6 s, no audio, faststart", "image": "JPEG q80, long side ≤1200 px", "overrides": "items[].encoding_override"},
           "total_bytes": tot, "items": man}, open(f"{OUT}/manifest.json", "w"), ensure_ascii=False, indent=1)
L = ["# site/assets — 공개 페이지 소재 매니페스트 (2026-11-06)", "",
     f"총 {len(man)}개 · {tot/1e6:.2f} MB. 영상 H.264 · 높이 540 · CRF 28 · ≤6초 · 무음, 스틸 JPEG q80 · 긴 변 ≤1200px. 예외: 구조도 폭 1400 · q88, 라인업 긴 변 1600 · q85, 세로 영상 3편 · 턴테이블 · bake 높이 720 · CRF 26.", "",
     "구 파일 대체: `s3_mesh_player.jpg` → `s3_mesh_player_03.jpg`(char3), `s3_mesh_char_shuffle.jpg` → `s3_mesh_player_04.jpg`(char4) — 렌더 비교로 같은 캐릭터 확인(메쉬는 다른 판: 구 TRELLIS.2 · 신 char*.glb).", "",
     "| 파일 | 종류 | 크기 | 캐릭터 | 단계 | 캡션 | 전후 쌍 | 원본 |", "|---|---|---|---|---|---|---|---|"]
for m in man:
    pr = f"{m['pair']['group']} · {m['pair']['role']}" if m["pair"] else "-"
    L.append(f"| `{m['file']}`{' **[자리]**' if m['placeholder'] else ''} | {m['kind']} {m['width']}×{m['height']} | {m['bytes']/1e6:.2f} MB | {m['character']} | {m['stage']} | {m['caption'].replace('|', chr(92) + '|')} | {pr} | `{m['source']}` |")
open(f"{OUT}/manifest.md", "w").write("\n".join(L) + "\n")
print(f"TOTAL {len(man)} items {tot/1e6:.2f} MB")
