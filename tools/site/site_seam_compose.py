"""5-4b 수리 전후 근접 그림 합성 (2026-11-21) — site_seam_closeup.py 렌더에 라벨 · 위치 상자만 더한다 (픽셀 보정 없음).

  python3 tools/site/site_seam_compose.py <렌더 폴더> <출력 폴더(site/assets)>

(가) 전신 소형 컷 + 근접 2칸(수리 전 · 수리 후), 1596×638 — README · 포트폴리오   → seam_<부위>_listener.jpg
(나) 근접 2칸, 1200×750 (16:10) — 웹페이지 칸                                   → seam_<부위>_listener_s.jpg
JPEG q85 (manifest 예외 — slide_listener_seq(_s) 와 같은 판정).
"""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

WS = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
# 라벨 · 구분선은 기존 site/assets/slide_listener_seq(_s).jpg 실측에 맞춘다 (2026-11-21):
#   상자 (20, 20, 20) 불투명, 패널 왼쪽 위 모서리에 붙임 · 글자 Apple SD Gothic Neo Bold, 색 (250, 235, 160)
#   (나) 1200×750 = slide_listener_seq_s 와 같은 크기 — 40px, 안쪽 여백 11, 상자 137×58, 구분선 흰색 6px
#   (가) 1596 폭 = slide_listener_seq 와 같은 폭 — 26px, 안쪽 여백 9, 상자 90×42, 구분선 흰색 10px
SEP_COLOR = (255, 255, 255)
LBOX = (20, 20, 20)
LTEXT = (250, 235, 160)
BOX = (255, 190, 40)      # 전신 컷의 근접 위치 상자 (기존 그림에 대응 요소 없음)


def ink_box(text, f):
    """글자 잉크의 실제 범위 (textbbox 는 글리프 여백을 포함한다)."""
    m = Image.new("L", (size_guess := f.size * 8, f.size * 3), 0)
    ImageDraw.Draw(m).text((f.size, f.size), text, font=f, fill=255)
    x0, y0, x1, y1 = m.point(lambda v: 255 if v > 100 else 0).getbbox()
    return x0 - f.size, y0 - f.size, x1 - x0, y1 - y0


def label(im, text, size, pad, box_wh):
    """왼쪽 위 모서리에 붙은 불투명 상자(box_wh) + 글자 (잉크가 (pad, pad) 에서 시작)."""
    f = ImageFont.truetype(FONT, size, index=6)                              # index 6 = Bold
    ox, oy, _, _ = ink_box(text, f)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, box_wh[0] - 1, box_wh[1] - 1], fill=LBOX)
    d.text((pad - ox, pad - oy), text, font=f, fill=LTEXT)
    return im


def rect_in_full(close, full, width_full=1.1, res=800):
    """근접 카메라 화면이 전신 화면(같은 방향 직교)에서 차지하는 사각형 (픽셀)."""
    s = res / width_full
    (cx, cz, w), (fx, fz) = close, full
    return (res / 2 + (cx - fx - w / 2) * s, res / 2 - (cz - fz + w / 2) * s,
            res / 2 + (cx - fx + w / 2) * s, res / 2 - (cz - fz - w / 2) * s)


SPECS = {
    # 이름: (수리 전 근접, 수리 후 근접, 전신(수리 전), 근접 중심 x · z · 폭, 전신 중심 x · z, 웹 칸 잘라내기 x 시작,
    #        전신 컷 잘라내기 x 시작 — 몸 전체와 위치 상자가 다 들어가게)
    "crotch": (WS / "crotch/pre.png", WS / "crotch/post.png", WS / "crotch/pre_full.png",
                   (0.0283, -0.1029, 0.4), (0.0083, 0.0371), 82, 212),
    "armpit": (WS / "armpit/pre.png", WS / "armpit/post.png", WS / "armpit/pre_full.png",
                   (0.1122, 0.2124, 0.4), (0.0207, 0.0457), 164, 245),
}
log = {}
for name, (pre, post, full, close_c, full_c, web_x, fx0) in SPECS.items():
    A, B, F = (Image.open(p).convert("RGB") for p in (pre, post, full))
    # (가) — 전신 컷: 몸 둘레 375×800 을 300×640 으로, 근접 영역에 상자
    r = rect_in_full(close_c, full_c)
    assert fx0 <= r[0] and r[2] <= fx0 + 375, f"{name}: 위치 상자가 전신 컷 밖이다 {r}"
    Fd = F.copy(); ImageDraw.Draw(Fd).rectangle(r, outline=BOX, width=4)
    Fc = Fd.crop((fx0, 0, fx0 + 375, 800)).resize((300, 638), Image.LANCZOS)
    a = label(A.resize((638, 638), Image.LANCZOS), "수리 전", 26, 9, (90, 42))
    b = label(B.resize((638, 638), Image.LANCZOS), "수리 후", 26, 9, (90, 42))
    W = 300 + 10 + 638 + 10 + 638                      # = 1596
    ga = Image.new("RGB", (W, 638), SEP_COLOR)
    ga.paste(Fc, (0, 0)); ga.paste(a, (310, 0)); ga.paste(b, (310 + 648, 0))
    ga.save(OUT / f"seam_{name}_listener.jpg", quality=85, optimize=True)
    # (나) — 근접 2칸 16:10: 637×800 창을 597×750 으로, 가운데 구분선 6px
    def web(im, text):
        return label(im.crop((web_x, 0, web_x + 637, 800)).resize((597, 750), Image.LANCZOS), text, 40, 11, (137, 58))
    gb = Image.new("RGB", (1200, 750), SEP_COLOR)
    gb.paste(web(A, "수리 전"), (0, 0)); gb.paste(web(B, "수리 후"), (603, 0))
    gb.save(OUT / f"seam_{name}_listener_s.jpg", quality=85, optimize=True)
    log[name] = {"pre": str(pre), "post": str(post), "full": str(full), "box_in_full_px": [round(v, 1) for v in r],
                 "full_crop_x": [fx0, fx0 + 375], "web_crop_x": [web_x, web_x + 637],
                 "outputs": [f"seam_{name}_listener.jpg", f"seam_{name}_listener_s.jpg"]}
print(json.dumps(log, ensure_ascii=False, indent=1))
