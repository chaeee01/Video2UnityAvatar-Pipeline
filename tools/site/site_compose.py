# -*- coding: utf-8 -*-
"""공개 페이지용 합성 원본 3종을 SITE_RAW 에 만든다 — site_assemble.py 가 이것을 웹용으로 인코딩한다.
  python3 site_compose.py
  lineup10.png        메쉬 10종 라인업 (5×2) — 좀비 6종(walker · listener · stalker · lurker · oiler · dog) 뒤에 플레이어 4종
  slide_still_row.png 디딘 발 근접 비교 4장 — 패널마다 빈 좌우 여백을 잘라 한 줄 (3200×800 → 1920×800)
  bake_walker_hit_eq.mp4 원본(좌) · 리그(우) — 리그 패널의 몸을 원본과 같은 키로 키우고 발 높이를 맞춘다"""
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

# 3) 원본 · 리그 — 1080×960(좌우 540 패널). 프레임 0~144 측정: 원본 몸 키 ≈817px(발 ≈922), 리그 몸 키 중앙값 476 · 합집합 x 152~354 · y 238~725
#    → 배율 1.72: 리그 패널에서 314×558 (x 96, y 189) 를 잘라 540×960 으로 키운다(발 725 → 922)
src = f"{E}/review_1026/08_final/walker/walker_hit_01_original_vs_rig.mp4"
ff("-i", src, "-filter_complex", "[0]crop=540:960:0:0[l];[0]crop=314:558:636:189,scale=540:960:flags=lanczos[r];[l][r]hstack=2",
   "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", "-an", f"{X}/bake_walker_hit_eq.mp4")
print("COMPOSE_DONE", X)
