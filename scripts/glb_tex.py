"""
GLB 에 임베드된 텍스처를 PNG 로 추출한다 (S3 보조).

  python glb_tex.py <glb> [출력폴더]

인자는 위치 인자다 — run_trellis.py 가 이 순서로 호출하고 RUNBOOK 예시도 같다.
여러 GLB 를 돌릴 때는 캐릭터별로 출력 폴더를 나눠야 파일명이 겹치지 않는다.
"""
import argparse, os, io, json, struct
from PIL import Image

ap = argparse.ArgumentParser(description="GLB 임베드 텍스처를 PNG 로 추출")
ap.add_argument("glb", help="입력 GLB 파일")
ap.add_argument("out", nargs="?", default="~/Desktop/zombie_textures",
                help="출력 폴더 (기본: ~/Desktop/zombie_textures)")
a = ap.parse_args()

glb = os.path.expanduser(a.glb)
out = os.path.expanduser(a.out)
os.makedirs(out, exist_ok=True)
prefix = os.path.splitext(os.path.basename(glb))[0]

with open(glb, "rb") as f:
    data = f.read()

# GLB 헤더 12바이트 이후 청크들
off = 12
js, bin_ = None, None
while off < len(data):
    ln, typ = struct.unpack_from("<II", data, off)
    body = data[off+8: off+8+ln]
    if typ == 0x4E4F534A:
        js = json.loads(body.decode("utf-8"))
    elif typ == 0x004E4942:
        bin_ = body
    off += 8 + ln + ((4 - ln % 4) % 4)

for i, img in enumerate(js.get("images", [])):
    bv = js["bufferViews"][img["bufferView"]]
    o = bv.get("byteOffset", 0)
    chunk = bin_[o: o + bv["byteLength"]]
    im = Image.open(io.BytesIO(chunk))
    if im.mode not in ("RGB", "RGBA"):   # 알파가 있으면 보존한다
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    p = os.path.join(out, f"{prefix}_tex_{i}.png")
    im.save(p)
    print("저장:", p, im.size)
