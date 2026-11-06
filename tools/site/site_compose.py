# -*- coding: utf-8 -*-
"""공개 페이지용 합성 원본 3종을 SITE_RAW 에 만든다 — site_assemble.py 가 이것을 웹용으로 인코딩한다.
  python3 site_compose.py
  lineup10.png        메쉬 10종 라인업 (5×2) — 좀비 6종(walker · listener · stalker · lurker · oiler · dog) 뒤에 플레이어 4종
  slide_still_row.png 디딘 발 근접 비교 4장 — 패널마다 빈 좌우 여백을 잘라 한 줄 (3200×800 → 1920×800)
  bake_walker_hit_eq.mp4 원본(좌) · 리그(우) — 리그를 고해상도로 다시 렌더해 원본과 같은 몸 키 · 발 높이 창을 잘라 맞춘다(업스케일 없음)"""
import os, subprocess

H = os.path.expanduser("~")
X = os.environ.get("SITE_RAW", f"{H}/data/site_raw_1106")
E = f"{H}/Desktop/3D_avatar_work/experiments/e2e_check"

def ff(*a):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"실패: {r.stderr[-400:]}")

# 1) 라인업 — 렌더 해상도가 900(기존 8종) · 1200(플레이어 char1~4)으로 섞여 있어 900 으로 맞춘다. 자르지 않는다 — dog 의 벌린 팔 · 플레이어 T포즈 손끝이 칸 끝까지 온다
names = ["walker", "listener", "stalker", "lurker", "oiler", "dog", "player_01", "player_02", "player_03", "player_04"]
inp = sum((["-i", f"{X}/mesh_{n}.png"] for n in names), [])
cells = "".join(f"[{i}]scale=900:900[c{i}];" for i in range(10))
ff(*inp, "-filter_complex", cells + "".join(f"[c{i}]" for i in range(5)) + "hstack=5[r1];"
   + "".join(f"[c{i}]" for i in range(5, 10)) + "hstack=5[r2];[r1][r2]vstack=2", "-frames:v", "1", f"{X}/lineup10.png")

# 2) 접지 근접 비교 — 4패널(각 800×800)의 몸은 패널 안 x 192~576 에 있다 → 손끝 여유를 두고 x 160~640 만 남긴다
src = f"{E}/review_1019/01_listener_run_slide/closeup_04b_f34_vs_transplant_f60_f50.png"
ff("-i", src, "-filter_complex", "".join(f"[0]crop=480:800:{800 * i + 160}:0[p{i}];" for i in range(4)) + "[p0][p1][p2][p3]hstack=4",
   "-frames:v", "1", f"{X}/slide_still_row.png")

# 3) 원본 · 리그 — 업스케일 없이. 리그는 render_playback.py 를 같은 정사영 카메라 · 2.296배 해상도(1240×2204)로 다시 렌더해 두었다:
#      Blender --background --python scripts/render_playback.py -- --blend ~/data/06_rig/walker_walk_02_wfix/motions/walker_hit_01/animated.blend \
#        --out $SITE_RAW/bake_rig_hi --res 1240 2204
#    기존 540×960 판에서 잰 몸 영역(프레임 0~144: 원본 몸 키 ≈817/960 · 발 ≈922, 리그 몸 키 476 · x 152~354 · y 238~725)으로
#    고른 창 314×558 (x 96, y 189) 을 ×2.296 하면 720×1280 (x 221, y 434) — 원본 1080×1920 은 720×1280 으로 줄여 나란히 둔다.
src = f"{H}/data/00_raw/walker_hit_01__omni-ff.mp4"
ff("-i", src, "-framerate", "24", "-i", f"{X}/bake_rig_hi/%04d.png", "-filter_complex",
   "[0]scale=720:1280:flags=lanczos,setsar=1[l];[1]crop=720:1280:221:434,setsar=1[r];[l][r]hstack=2",
   "-c:v", "libx264", "-crf", "12", "-preset", "slow", "-pix_fmt", "yuv420p", "-an", f"{X}/bake_walker_hit_eq.mp4")
print("COMPOSE_DONE", X)
