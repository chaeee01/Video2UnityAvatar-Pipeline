import sys, os, io, json, struct
from PIL import Image

glb = sys.argv[1]
out = os.path.expanduser("~/Desktop/zombie_textures")
os.makedirs(out, exist_ok=True)

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
    im = Image.open(io.BytesIO(chunk)).convert("RGB")
    p = os.path.join(out, f"zombie_tex_{i}.png")
    im.save(p)
    print("저장:", p, im.size)
