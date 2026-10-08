#!/usr/bin/env python3
"""pipeline_v4.png 을 그린다 — 구조도의 원본이다. 그림을 고치려면 이 파일을 고친다.

  python3 docs/assets/make_pipeline_v4.py [출력.png]      # 기본: 이 폴더의 pipeline_v4.png

2026-10-08 에 만들었다. 그전의 pipeline_v4.png 는 원본 파일 없이 PNG 만 있어서, 단계
순서를 S2 → S5 → G1a → S3 으로 바꾸면서 같은 모양으로 다시 그렸다. 달라진 것:
  - G1a 가 "외형용 클립 평가" 에서 "키프레임 재선정" 으로, G3 → G1a 의 pose 전달 선 추가
  - 실행 순서 표기(①~④)와 안내 상자
  - S6 의 "미터 단위" → "TRELLIS 정규화 단위" (2026-09-22 문서 정합 때 글은 고쳤으나
    그림에는 남아 있었다)
v1~v3 그림은 지난 설계의 기록이라 손대지 않는다.

좌표는 1164x2000 기준이고 S 배로 키워 그린다. 글꼴은 macOS 의 Apple SD Gothic Neo.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2.56
W, H = 1164, 2000
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
BOLD, REG = 6, 0

PAL = {   # 채움, 테두리, 글자
    "gate":   ("#F9E4C8", "#E5A65A", "#7A4A10"),
    "plain":  ("#EEEDE6", "#B5B5AA", "#2B2B2B"),
    "seg":    ("#E3E1F9", "#9A8FE0", "#3B2FA0"),
    "shape":  ("#D4EDE3", "#6DC2A0", "#17694A"),
    "motion": ("#FBDFE0", "#E59A9E", "#A8232B"),
    "merge":  ("#D9E8F7", "#8FB5E0", "#1F5A99"),
}
LINE = "#8A8A84"
BETAS = "#C2307A"
POSE = "#2B6CB0"

img = Image.new("RGB", (int(W * S), int(H * S)), "white")
d = ImageDraw.Draw(img)


def font(size, bold=False):
    return ImageFont.truetype(FONT, int(size * S), index=BOLD if bold else REG)


def P(*xy):
    return [int(v * S) for v in xy]


def box(x0, y0, x1, y1, kind, title, lines=(), tsize=19, width=1.4):
    fill, edge, ink = PAL[kind]
    d.rounded_rectangle(P(x0, y0, x1, y1), radius=int(7 * S), fill=fill, outline=edge,
                        width=int(width * S))
    cx = (x0 + x1) / 2
    lh = 18
    total = tsize + 4 + lh * len(lines)
    y = (y0 + y1) / 2 - total / 2
    d.text(P(cx, y + tsize / 2), title, font=font(tsize, True), fill=ink, anchor="mm")
    y += tsize + 6
    for ln in lines:
        d.text(P(cx, y + lh / 2), ln, font=font(13.5), fill=ink, anchor="mm")
        y += lh


def head(x, y, direction, color=LINE, size=7):
    dx, dy = {"d": (0, 1), "u": (0, -1), "l": (-1, 0), "r": (1, 0)}[direction]
    px, py = -dy, dx
    pts = [(x, y), (x - dx * size * 1.4 + px * size * 0.7, y - dy * size * 1.4 + py * size * 0.7),
           (x - dx * size * 1.4 - px * size * 0.7, y - dy * size * 1.4 - py * size * 0.7)]
    d.polygon([tuple(P(*p)) for p in pts], fill=color)


def path(points, arrow=None, color=LINE, width=1.6, dash=None):
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


def note(x, y, text, size=13, color="#555555", anchor="mm", bold=False, bg=None):
    f = font(size, bold)
    if bg:                     # 선 위에 얹히는 글자는 바탕을 깔아 선을 가린다
        w = d.textlength(text, font=f) / S + 8
        d.rectangle(P(x - w / 2, y - size * 0.75, x + w / 2, y + size * 0.75), fill=bg)
    d.text(P(x, y), text, font=f, fill=color, anchor=anchor)


def tag(cx, cy, text, color):
    f = font(15, True)
    w = d.textlength(text, font=f) / S + 14
    d.rounded_rectangle(P(cx - w / 2, cy - 13, cx + w / 2, cy + 13), radius=int(5 * S),
                        fill="white", outline=color, width=int(1.4 * S))
    d.text(P(cx, cy), text, font=f, fill=color, anchor="mm")


def badge(x, y, n):
    d.ellipse(P(x - 13, y - 13, x + 13, y + 13), fill="#2B2B2B")
    d.text(P(x, y), str(n), font=font(15, True), fill="white", anchor="mm")


C = 582                      # 가운데 축
L0, L1 = 90, 480             # 왼쪽 열 (외형 경로)
R0, R1 = 685, 1076           # 오른쪽 열 (동작 경로)
LC, RC = (L0 + L1) / 2, (R0 + R1) / 2
MID = 583                    # 두 열 사이 통로 — 전달선이 지나간다

# ── 가운데 줄기
box(442, 42, 722, 94, "plain", "입력 영상", tsize=18)
box(371, 145, 793, 219, "gate", "G0. 입력 검증", ["해상도, 압축 아티팩트, 대상 존재"])
box(371, 270, 793, 344, "plain", "S0. 전처리", ["fps, 해상도, 색공간 정규화"])
box(371, 395, 793, 469, "seg", "S1. PySceneDetect", ["컷 감지, 클립 분할"])
box(371, 520, 793, 594, "seg", "S2. SAM2 분할, 트래킹",
    ["마스크와 원본 클립 모두 보존 · 키프레임 1차 후보"])
for y0, y1 in ((94, 145), (219, 270), (344, 395), (469, 520)):
    path([(C, y0), (C, y1)], "d")

# ── S2 에서 두 경로로
path([(C, 594), (C, 630)])
path([(LC, 630), (RC, 630)])
path([(LC, 630), (LC, 640)], "d")
path([(RC, 630), (RC, 640)], "d")
note(365, 609, "마스크 사용")
note(805, 609, "원본 사용")

# ── 왼쪽: 외형 경로
box(L0, 640, L1, 730, "gate", "G1a. 키프레임 재선정",
    ["마스크: 다리 벌어짐  +  WHAM pose: 시선각", "다리 움직임 없는 클립은 붙은 다리 허용"])
box(L0, 783, L1, 868, "shape", "S3. TRELLIS", ["단일 또는 다중 뷰 입력", "메쉬 + 텍스처 생성"])
box(L0, 924, L1, 1043, "gate", "G2. 메쉬 품질",
    ["재렌더 LPIPS, CLIP-I", "실루엣 IoU, 대칭, 파편", "UV 왜곡, 뒷면 뭉개짐"])
box(L0, 1116, L1, 1241, "shape", "S4. SMPL 골격 직접 리깅",
    ["betas + pose 로 SMPL 메쉬 생성", "TRELLIS 메쉬와 정렬 (스케일, 회전)", "최근접 대응으로 웨이트 전이"],
    width=2.2)
box(L0, 1298, L1, 1399, "gate", "G2r. 리깅 검증",
    ["SMPL 24본 계층, 웨이트 이상치", "정렬 오차, 폴백 분포"])
for y0, y1 in ((730, 783), (868, 924), (1043, 1116), (1241, 1298)):
    path([(LC, y0), (LC, y1)], "d")

# ── 오른쪽: 동작 경로
box(R0, 640, R1, 730, "gate", "G1m. 동작용 클립 평가",
    ["bbox 높이, 가림, 인원수", "카메라 고정 또는 이동 분기"])
box(R0, 783, R1, 868, "motion", "S5. WHAM",
    ["고정은 local only, 이동은 DPVO", "betas, pose, transl 추정"])
box(R0, 924, R1, 1043, "gate", "G3. 동작 품질",
    ["재투영 PCK, MPJPE, 발 미끄러짐", "저크, 접지, 좀비 자세 플래그", "betas 시간 안정성, 대표값 확정"])
box(R0, 1128, R1, 1229, "motion", "S6. 좌표 변환",
    ["Y-up, TRELLIS 정규화 단위", "SMPL pose 시퀀스 (θ, transl)"])
for y0, y1 in ((730, 783), (868, 924), (1043, 1128)):
    path([(RC, y0), (RC, y1)], "d")

# ── 동작 경로 → 외형 경로 전달 2개
# pose: G3 → G1a (키프레임을 고르는 데 쓴다)   — 2026-10-08 신규
path([(R0, 955), (MID, 955), (MID, 685), (L1, 685)], "l", color=POSE, width=2.0, dash=(12, 7))
tag(MID, 822, "pose 전달", POSE)
note(MID, 846, "(시선각 · 다리 움직임)", 12.5, POSE, bg="white")
# betas: G3 → S4 (골격을 SMPL 로 통일한다)     — v4 의 핵심
path([(R0, 1005), (MID, 1005), (MID, 1178), (L1, 1178)], "l", color=BETAS, width=2.0, dash=(12, 7))
tag(MID, 1088, "betas 전달", BETAS)
note(MID, 1112, "(동일 체형 파라미터 공유)", 12.5, BETAS, bg="white")

# ── 합류
path([(LC, 1399), (LC, 1461), (RC, 1461), (RC, 1229)])
path([(C, 1461), (C, 1486)], "d")
box(332, 1486, 832, 1587, "merge", "S7. 동작 결합",
    ["골격이 동일하므로 리타게팅 없음", "SMPL pose 를 리깅 메쉬에 직접 적용"], width=2.0)
box(332, 1622, 832, 1723, "gate", "G4. 최종 통합 평가",
    ["메쉬 관통, 발 접지, 실루엣 유지", "렌더 결과와 원본 클립 대조"])
box(442, 1774, 722, 1825, "plain", "에셋 반입 완료", tsize=18)
box(332, 1855, 832, 1956, "motion", "R. 재시도 오케스트레이터",
    ["실패 원인별 재진입 지점 결정", "게이트별 횟수 제한, 전체 상한"])
for y0, y1 in ((1587, 1622), (1723, 1774), (1825, 1855)):
    path([(C, y0), (C, y1)], "d")

# ── 재시도 고리
path([(832, 1672), (1121, 1672), (1121, 1905), (832, 1905)], "l")
note(1086, 1807, "불합격")
path([(332, 1905), (68, 1905), (68, 685), (L0, 685)], "r")
note(184, 1968, "클립 재선정")
note(C, 1968, "시드 또는 키프레임 교체")
note(982, 1968, "스무딩 후 재평가")

# ── 실행 순서 (2026-10-08~): 동작 경로가 먼저 돈다
badge(371 - 22, 557, 1)       # S2
badge(R1 + 22, 825, 2)        # S5
badge(L0 - 22 + 44, 652, 3)   # G1a (재시도 고리 선을 피해 상자 안쪽 모서리)
badge(L0 + 22, 795, 4)        # S3
d.rounded_rectangle(P(826, 30, 1136, 118), radius=int(7 * S), fill="#F7F7F4",
                    outline="#B5B5AA", width=int(1.2 * S))
note(981, 52, "실행 순서", 15, "#2B2B2B", bold=True)
note(981, 76, "① S2 → ② S5 → ③ G1a → ④ S3", 14.5, "#2B2B2B", bold=True)
note(981, 99, "키프레임 선정에 WHAM pose 가 필요해 동작 경로가 먼저", 11.5)

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("pipeline_v4.png")
img.save(out, optimize=True)
print(f"저장: {out}  {img.size[0]}x{img.size[1]}")
