#!/usr/bin/env python3
"""pipeline_v4_current.png 을 그린다 — 지금 구현된 파이프라인 v4 구조도의 원본 (2026-11-21~).

  python3 docs/assets/make_pipeline_v4_current.py --font <NotoSansKR[wght].ttf> [--out 출력.png] [--jpg 웹용.jpg]

- 글꼴: Noto Sans KR 가변 글꼴(Google Fonts, OFL)을 --font 로 준다. 레포에는 넣지 않는다.
  --font 를 주지 않으면 macOS 의 Apple SD Gothic Neo 로 그리고 그 사실을 출력한다.
- 원본 PNG 는 3000px 폭. --jpg 를 주면 웹페이지용 1600px 폭 JPG(q85)도 만든다 — tools/site/site_assemble.py 와
  같은 sips 명령이라 두 경로의 결과가 바이트 동일하다(맥 전용).
- 배치와 색은 11/14 의 pipeline_v4_final.png(외부에서 만든 그림, 원본 파일 없음)를 실측해 따랐다.
  그 그림과 달라진 내용 18곳은 docs/PROJECT_STATUS.md 2026-11-21 항목에 있다. 그림은 "지금 구현된 모습" 의
  개요다 — 외형 트랙 · 동작 트랙의 구분(G4 는 동작 트랙에서 클립마다)은 RUNBOOK 1.5 · 5.6절이 원본이다.
- 옛 원본 make_pipeline_v4.py(docs/assets/pipeline_v4.png, 10/08)는 기록으로 그대로 둔다.

그림이 말하는 것은 코드가 하는 것이어야 한다 — 단계 · 게이트 · 시도 횟수 · 종료 코드의 근거:
  scripts/orchestrate.py STAGES · MOTION_MAC · S2_MAX_TRIES/G2_MAX_TRIES · EXIT_HUMAN, RUNBOOK 0 · 1.5 · 5.5~5.7절.

배치 규칙 (그릴 때 assert 로 검사한다):
  - 가운데 줄기 상자는 모두 가로 중심이 축 C 에 있다.
  - 왼쪽 열 · 오른쪽 열은 C 에서 같은 거리, 그림 좌우 여백이 같다.
  - 오른쪽 열(S5 · G1 추적 판정 · G3)은 왼쪽 열 전체 높이의 세로 가운데에 놓는다.
  - 두 전달선(pose · SMPL 몸)은 두 열 사이 정중앙의 세로선 하나를 위 · 아래로 나눠 쓴다.
좌표는 1500 폭 논리 단위이고 S 배로 키워 그린다.
"""
import argparse
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("--font", help="Noto Sans KR 가변 글꼴 파일 (없으면 Apple SD Gothic Neo)")
ap.add_argument("--out", default=str(Path(__file__).with_name("pipeline_v4_current.png")))
ap.add_argument("--jpg", help="웹페이지용 1600px JPG 출력 경로")
a = ap.parse_args()

S = 2.0
W, H = 1500, 1825
APPLE = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
if a.font:
    print(f"글꼴: {a.font}")
else:
    print(f"글꼴: --font 없음 — Apple SD Gothic Neo ({APPLE})")

_cache = {}


def font(size, bold=False):
    k = (size, bold)
    if k not in _cache:
        if a.font:
            f = ImageFont.truetype(a.font, int(round(size * S)))
            f.set_variation_by_name("Bold" if bold else "Regular")
        else:
            f = ImageFont.truetype(APPLE, int(round(size * S)), index=6 if bold else 0)
        _cache[k] = f
    return _cache[k]


# 11/14 그림 실측 색 — (채움, 테두리, 제목 글자). 본문 글자는 모두 BODY.
PAL = {
    "gate":   ((253, 240, 217), (223, 161, 79), (122, 76, 18)),
    "plain":  ((238, 240, 242), (154, 161, 171), (34, 38, 46)),
    "seg":    ((234, 231, 251), (139, 127, 224), (58, 51, 128)),
    "shape":  ((226, 243, 233), (88, 173, 125), (29, 92, 58)),
    "motion": ((253, 231, 234), (217, 115, 126), (124, 39, 51)),
    "merge":  ((228, 237, 250), (111, 151, 221), (30, 63, 122)),
}
BODY = (60, 65, 75)
LINE = (111, 118, 129)
NOTE = (91, 100, 113)
POSE = (47, 99, 201)
BODYTX = (193, 53, 120)        # SMPL 몸 전달 (11/14 그림의 betas 선 색)
DARK = (34, 38, 46)

img = Image.new("RGB", (int(W * S), int(H * S)), "white")
d = ImageDraw.Draw(img)
BOXES = []                     # 검사용 (x0, y0, x1, y1, 제목, 글자 최대 폭, 글자 높이)
EXTENT = []                    # 그림 요소의 가로 범위 — 좌우 여백 검사


def P(*xy):
    return [int(round(v * S)) for v in xy]


def tw(text, f):
    return d.textlength(text, font=f) / S


def box(x0, y0, x1, y1, kind, title, lines=(), sub=None, tsize=20, bsize=14.5, width=2.0):
    """제목 + 본문. sub 는 제목 뒤에 작게 붙는 단계 번호 · 구현 이름 (예: "(S2)")."""
    fill, edge, ink = PAL[kind]
    d.rounded_rectangle(P(x0, y0, x1, y1), radius=int(8 * S), fill=fill, outline=edge,
                        width=int(width * S))
    cx = (x0 + x1) / 2
    lh = bsize * 1.52
    total = tsize * 1.15 + (6 + lh * len(lines) if lines else 0)
    y = (y0 + y1) / 2 - total / 2
    ty = y + tsize * 0.575
    ft = font(tsize, True)
    if sub:
        fs = font(tsize * 0.68, True)
        gap = tsize * 0.3
        wt, ws = tw(title, ft), tw(sub, fs)
        left = cx - (wt + gap + ws) / 2
        d.text(P(left, ty), title, font=ft, fill=ink, anchor="lm")
        d.text(P(left + wt + gap, ty + tsize * 0.04), sub, font=fs, fill=ink, anchor="lm")
        title_w = wt + gap + ws
    else:
        d.text(P(cx, ty), title, font=ft, fill=ink, anchor="mm")
        title_w = tw(title, ft)
    y += tsize * 1.15 + 6
    for ln in lines:
        d.text(P(cx, y + lh / 2), ln, font=font(bsize), fill=BODY, anchor="mm")
        y += lh
    widest = max([title_w] + [tw(t, font(bsize)) for t in lines])
    BOXES.append((x0, y0, x1, y1, title, widest, total))
    EXTENT.append((x0, x1))


def head(x, y, direction, color=LINE, size=8):
    dx, dy = {"d": (0, 1), "u": (0, -1), "l": (-1, 0), "r": (1, 0)}[direction]
    px, py = -dy, dx
    pts = [(x, y), (x - dx * size * 1.5 + px * size * 0.8, y - dy * size * 1.5 + py * size * 0.8),
           (x - dx * size * 1.5 - px * size * 0.8, y - dy * size * 1.5 - py * size * 0.8)]
    d.polygon([tuple(P(*p)) for p in pts], fill=color)


def path(points, arrow=None, color=LINE, width=2.0, dash=None):
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if dash is None:
            d.line(P(x0, y0, x1, y1), fill=color, width=int(width * S))
            continue
        on, off = dash
        length = abs(x1 - x0) + abs(y1 - y0)
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        t = 0
        while t < length:
            e = min(t + on, length)
            d.line(P(x0 + ux * t, y0 + uy * t, x0 + ux * e, y0 + uy * e), fill=color,
                   width=int(width * S))
            t += on + off
    if arrow:
        head(points[-1][0], points[-1][1], arrow, color)
    EXTENT.append((min(p[0] for p in points), max(p[0] for p in points)))


def note(x, y, text, size=13.5, color=NOTE, anchor="mm", bold=False, bg=None):
    f = font(size, bold)
    w = tw(text, f)
    if bg:                     # 선 위에 얹히는 글자는 바탕을 깔아 선을 가린다
        d.rectangle(P(x - (w + 10) / 2, y - size * 0.8, x + (w + 10) / 2, y + size * 0.8), fill=bg)
    d.text(P(x, y), text, font=f, fill=color, anchor=anchor)
    x0 = {"m": x - w / 2, "l": x, "r": x - w}[anchor[0]]
    EXTENT.append((x0, x0 + w))


def tag(cx, cy, text, color, size=15):
    f = font(size, True)
    w = tw(text, f) + 18
    d.rounded_rectangle(P(cx - w / 2, cy - 15, cx + w / 2, cy + 15), radius=int(6 * S),
                        fill="white", outline=color, width=int(1.6 * S))
    d.text(P(cx, cy), text, font=f, fill=color, anchor="mm")


def badge(x, y, n):
    d.ellipse(P(x - 15, y - 15, x + 15, y + 15), fill=DARK)
    d.text(P(x, y), str(n), font=font(16, True), fill="white", anchor="mm")
    EXTENT.append((x - 15, x + 15))


C = 750                      # 가운데 축
CW = 180                     # 가운데 줄기 상자 반폭
OFF = 419.5                  # 열 중심의 축에서의 거리
COLW = 379                   # 열 상자 폭
LC, RC = C - OFF, C + OFF
L0, L1 = LC - COLW / 2, LC + COLW / 2    # 왼쪽 열 — 외형 경로
R0, R1 = RC - COLW / 2, RC + COLW / 2    # 오른쪽 열 — 동작 경로
MID = (L1 + R0) / 2          # 두 열 사이 정중앙 — 전달선의 세로 구간
assert MID == C
DASH = (12, 7)
GAP = 42                     # 상자 사이 세로 간격


def cbox(y0, y1, kind, title, lines=(), sub=None, half=CW, **kw):
    """가운데 줄기 상자 — 가로 중심이 C."""
    box(C - half, y0, C + half, y1, kind, title, lines, sub, **kw)


# ── 실행 순서 상자 (오른쪽 위)
EX0, EX1 = R0 - 20, R1 + 40
d.rounded_rectangle(P(EX0, 30, EX1, 116), radius=int(8 * S), fill=PAL["plain"][0],
                    outline=PAL["plain"][1], width=int(1.4 * S))
EXTENT.append((EX0, EX1))
note((EX0 + EX1) / 2, 58, "실행 순서  ① S2 → ② S5 → ③ G1a → ④ S3", 16, DARK, bold=True)
note((EX0 + EX1) / 2, 88, "키프레임 선정에 WHAM pose 가 필요해 동작 경로가 먼저", 13.5, BODY)

# ── 가운데 줄기 (위)
cbox(31, 85, "plain", "입력 영상", tsize=20)
cbox(126, 204, "gate", "G0 · 입력 검증", ["프레임 수 · fps · 해상도 실측"])
cbox(245, 323, "seg", "SAM2 분할 · 트래킹", ["마스크와 원본 클립 모두 보존 · 키프레임 1차 후보"], sub="(S2)")
cbox(364, 466, "gate", "G1 · 분할 판정", ["마스크 커버리지 · 빈 프레임 · 조각 수",
                                        "불합격 시 프롬프트 바꿔 다시 시도 (시도 최대 3회)"], sub="(gate_s2)")
for y0, y1 in ((85, 126), (204, 245), (323, 364)):
    path([(C, y0), (C, y1)], "d")

# ── 왼쪽: 외형 경로 — 상자 5개
LROWS = [(536, 638), (680, 766), (808, 910), (952, 1078), (1120, 1222)]
(g1a, s3, g2, s4, g2r) = LROWS
box(L0, *g1a[:1], L1, g1a[1], "gate", "G1 · 키프레임 선정",
    ["마스크: 다리 벌어짐 + WHAM pose: 시선각", "다리 움직임 없는 클립은 붙은 다리 허용"], sub="(G1a)")
box(L0, s3[0], L1, s3[1], "shape", "TRELLIS.2 외형 생성", ["단일 뷰(키프레임 1장) 입력", "메쉬 + 텍스처 생성"],
    sub="(S3)")
box(L0, g2[0], L1, g2[1], "gate", "G2 · 메쉬 품질",
    ["유효 metallic · 데시메이션 비율", "불합격 시 seed 바꿔 다시 생성 (시도 최대 2회)"])
box(L0, s4[0], L1, s4[1], "shape", "SMPL 골격 직접 리깅",
    ["WHAM 키프레임 정점으로 SMPL 메쉬 (5-1)", "TRELLIS 메쉬와 정렬 (스케일, 회전)",
     "웨이트 전이 3단 → 경계 스무딩"], sub="(S4)", width=2.6)
box(L0, g2r[0], L1, g2r[1], "gate", "G2 · 리깅 검증",
    ["정렬 스케일 · bbox IoU · 관절 거리", "말단 본 · 좌우 교차 · 부위 잇는 엣지 · 폴백 분포"], sub="(G2r)")
for (_, y0), (y1, _) in zip(LROWS, LROWS[1:]):
    path([(LC, y0), (LC, y1)], "d")

# ── 오른쪽: 동작 경로 — 상자 3개, 왼쪽 열 전체 높이의 세로 가운데
RH = [102, 86, 102]
rtotal = sum(RH) + GAP * (len(RH) - 1)
LTOP, LBOT = LROWS[0][0], LROWS[-1][1]
rtop = (LTOP + LBOT) / 2 - rtotal / 2
RROWS = []
y = rtop
for h in RH:
    RROWS.append((y, y + h))
    y += h + GAP
(s5, g1t, g3) = RROWS
box(R0, s5[0], R1, s5[1], "motion", "WHAM 동작 복원",
    ["고정 카메라 (local only, DPVO 미설치)", "betas, pose, transl 추정"], sub="(S5)")
box(R0, g1t[0], R1, g1t[1], "gate", "G1 · 추적 판정", ["트랙 연속성 — 끊김 없이 전 프레임 추적"], sub="(gate_s5)")
box(R0, g3[0], R1, g3[1], "gate", "G3 · 재투영 일관성",
    ["몸 관절 12개 재투영 오차 (키 대비)", "PASS · CHECK 기록 · 안내 (불합격 없음)"])
for (_, y0), (y1, _) in zip(RROWS, RROWS[1:]):
    path([(RC, y0), (RC, y1)], "d")

# ── G1 분할 판정에서 두 경로로
SPLIT = 500
path([(C, 466), (C, SPLIT)])
path([(LC, SPLIT), (RC, SPLIT)])
path([(LC, SPLIT), (LC, LTOP)], "d")
path([(RC, SPLIT), (RC, rtop)], "d")
note(LC + 95, SPLIT - 15, "마스크 + 원본 프레임")
note(RC - 70, SPLIT - 15, "마스크 영상")

# ── S5 → 외형 경로 전달 2개 — 세로선 x = MID 하나를 위(pose) · 아래(SMPL 몸)로 나눠 쓴다
y_pose_src, y_body_src = s5[0] + 30, s5[1] - 24
y_pose_dst = (g1a[0] + g1a[1]) / 2
y_body_dst = (s4[0] + s4[1]) / 2
assert y_pose_dst < y_pose_src < y_body_src < y_body_dst    # 두 세로 구간이 겹치지 않는다
path([(R0, y_pose_src), (MID, y_pose_src), (MID, y_pose_dst), (L1, y_pose_dst)], "l",
     color=POSE, width=2.2, dash=DASH)
ty = (y_pose_dst + y_pose_src) / 2
tag(MID, ty - 10, "pose 전달", POSE)
note(MID, ty + 20, "(시선각 · 다리 움직임)", 13, POSE, bg="white")
path([(R0, y_body_src), (MID, y_body_src), (MID, y_body_dst), (L1, y_body_dst)], "l",
     color=BODYTX, width=2.2, dash=DASH)
ty = (y_body_src + y_body_dst) / 2
tag(MID, ty - 10, "SMPL 몸 전달", BODYTX)
note(MID, ty + 20, "(체형 betas · 키프레임 자세 반영)", 13, BODYTX, bg="white")

# ── 합류 → 가운데 줄기 (아래): S7 → G4 → 에셋 반입 완료
JOIN = LBOT + 46
path([(LC, LBOT), (LC, JOIN), (RC, JOIN), (RC, g3[1])])
note(RC + 14, (g3[1] + JOIN) / 2, "pose 시퀀스 (θ, transl)", 13, NOTE, anchor="lm")
S7 = (JOIN + 32, JOIN + 32 + 132)
path([(C, JOIN), (C, S7[0])], "d")
cbox(*S7, "merge", "동작 결합 · 베이킹",
     ["골격이 동일하므로 리타게팅 없음", "SMPL pose 를 리깅 메쉬에 직접 적용 (Y-up, TRELLIS 정규화 단위)",
      "베이킹(클립 전 프레임) · 바닥 정렬"], sub="(S7)", half=260, width=2.6)
G4 = (S7[1] + GAP, S7[1] + GAP + 90)
cbox(*G4, "gate", "G4 · 클립 품질", ["동작 클립마다 — 늘어남 · 발 쓸기 · 바닥 수치 판정"], half=220)
DONE = (G4[1] + GAP, G4[1] + GAP + 54)
cbox(*DONE, "plain", "에셋 반입 완료", tsize=20)
path([(C, S7[1]), (C, G4[0])], "d")
path([(C, G4[1]), (C, DONE[0])], "d")

# ── G4 옆 글 상자: CHECK · FAIL → 사람 (종료 코드 2)
NB0, NB1 = R0 + 40, R1 + 40
nb_y0, nb_y1 = G4[0] - 6, G4[1] + 6
d.rounded_rectangle(P(NB0, nb_y0, NB1, nb_y1), radius=int(8 * S), fill="white",
                    outline=PAL["plain"][1], width=int(1.4 * S))
EXTENT.append((NB0, NB1))
path([(C + 220, (G4[0] + G4[1]) / 2), (NB0, (G4[0] + G4[1]) / 2)], "r", dash=(8, 6))
ncx, ncy = (NB0 + NB1) / 2, (nb_y0 + nb_y1) / 2
note(ncx, ncy - 24, "CHECK · FAIL 이면 클립 FBX 를 내보내지 않음", 13, NOTE, bold=True)
note(ncx, ncy, "사람 확인 · 수용 기록 → G4 만 다시 판정", 13, NOTE)
note(ncx, ncy + 24, "(종료 코드 2)", 13, NOTE)

# ── R. 오케스트레이터 — 흐름의 한 칸이 아니라 위 전체를 돌리는 것
R_ = (DONE[1] + 36, DONE[1] + 36 + 98)
cbox(*R_, "motion", "R. 오케스트레이터",
     ["명령 하나로 전 구간 · 사람 개입 0~1회",
      "단계별 자동 시도 S2 최대 3회 · S3 최대 2회 (그 밖 1회) → 넘으면 사람 개입 (종료 코드 2)"],
     sub="(orchestrate.py)", half=500)
assert R_[1] <= H - 25, R_

# ── 실행 순서 표시
badge(C - CW - 26, 284, 1)                     # S2
badge(R1 + 26, (s5[0] + s5[1]) / 2, 2)          # S5
badge(L0 - 26, (g1a[0] + g1a[1]) / 2, 3)        # G1a
badge(L0 - 26, (s3[0] + s3[1]) / 2, 4)          # S3

# ── 검사
bad = [(t, round(w, 1), x1 - x0) for x0, y0, x1, y1, t, w, h in BOXES if w > (x1 - x0) - 24 or h > (y1 - y0) - 10]
for b in bad:
    print("넘침:", b)
assert not bad, "상자 안 글자가 넘친다"
xmin, xmax = min(e[0] for e in EXTENT), max(e[1] for e in EXTENT)
print(f"좌우 여백: 왼쪽 {xmin:.1f} · 오른쪽 {W - xmax:.1f} (논리 단위)")
print(f"열 중심: 왼쪽 {LC} · 오른쪽 {RC} — 축 {C} 에서 {C - LC} · {RC - C}")
print(f"세로: 왼쪽 열 {LTOP}~{LBOT} (중앙 {(LTOP + LBOT) / 2}), 오른쪽 열 {rtop}~{RROWS[-1][1]} "
      f"(중앙 {(rtop + RROWS[-1][1]) / 2}) — 위 여백 {rtop - LTOP} · 아래 여백 {LBOT - RROWS[-1][1]}")
print(f"전달선 세로 구간 x={MID}: pose {y_pose_dst}~{y_pose_src}, SMPL 몸 {y_body_src}~{y_body_dst}")

out = Path(a.out)
img.save(out, optimize=True)
print(f"저장: {out}  {img.size[0]}x{img.size[1]}")
if a.jpg:   # site_assemble.py 의 OPTS["pipeline_v4"] 와 같은 값 · 같은 명령
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "85", "--resampleWidth", "1600",
                    str(out), "--out", a.jpg], check=True, capture_output=True)
    print(f"저장: {a.jpg}  (sips, 폭 1600, q85)")
