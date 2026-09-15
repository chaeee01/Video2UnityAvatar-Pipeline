"""G2 게이트: TRELLIS 산출 GLB 의 외형 품질을 판정한다.

2026-09-10 에 4샘플 중 2건이 metallic 오판으로 망가졌는데(stalker 는 Unity 에서
빛을 삼키는 검은 덩어리가 된다) 전부 육안으로만 잡혔다. 이 게이트가 그 판정을
자동화한다.

  python gate_g2.py --glb ~/data/03_trellis/gen2/<샘플>/<샘플>.glb --out <폴더>

metallic 은 텍스처 B 채널 평균과 material 의 metallicFactor 를 함께 본다 —
최종 metallic 은 둘의 곱이므로 factor 가 0 이면 텍스처가 포화해도 무해하다
(--force-dielectric 처리본이 이 경우다).

출력: <out>/gate_g2.json (gate_s2 와 같은 스키마) + 표준출력 요약.
"""
import argparse
import glob
import json
import os
import struct
import sys

import numpy as np
from PIL import Image

# ── 임계값과 근거 ────────────────────────────────────────────────────────────
# 잠정(표본 6건). 재보정 조건: 신규 10건 누적 시 / PASS 후 하류 실패 발생 시.
#
# METALLIC_MAX = 32
#   2026-09-10~11 실측 (MR 텍스처 B 채널 평균, 0-255):
#     walker 512    0.2   양호        zombie1 512     1.0   양호
#     dog 512      51.5   번들거림    walker 1024   143.4   중간
#     stalker 512 254.7   전신 금속   zombie1 1024  254.7   전신 금속
#   인간형 좀비 도메인에서 metallic 은 항상 0 에 가까워야 한다. 양호 사례가
#   0.2~1.0 이고 열화 사례의 최저가 51.5 이므로 그 사이면 어디든 가르지만,
#   32(=255의 12.5%)로 잡은 것은 PBR 관례상 비금속을 0.05 이하로 보는 것과
#   여유를 함께 고려한 값이다. 경계 사례가 아직 없어 정밀한 근거는 없다.
# VERTEX_MIN / VERTEX_MAX
#   절대값은 쓰지 않는다. to_glb 의 decimation_target 이 상한으로 작동해
#   산출물이 그 근처로 수렴하기 때문이다 — 2026-09-11 실측에서 4샘플이
#   629,699 / 638,166 / 671,643 / 796,400 (1.27배) 로 몰렸고 면 수는
#   934,754~996,953 (1.07배) 였다. 판별력이 없다.
#   대신 decimation_target 대비 비율로 본다. 지나치게 낮으면(<20%) 생성이
#   빈약했다는 신호이고, 상한을 넘으면 데시메이션이 동작하지 않은 것이다.
# FLOAT_AREA_MAX_PCT
#   부유 조각 — 본체에서 떨어진 작은 껍질들. Q2'(찢어진 옷의 부유 조각이
#   어깨 회전 시 부채꼴로 늘어남)의 원인이다. 면적 비율로만 재고 조건부
#   경고에 그친다 — 좀비 도메인에서 찢어진 천 조각은 정상 산출물이기도 해서
#   불합격시킬 근거가 아직 없다.
METALLIC_MAX = 32.0
METALLIC_WARN = 8.0
DECIMATION_RATIO_MIN = 0.20
DECIMATION_RATIO_MAX = 1.10
FLOAT_AREA_WARN_PCT = 5.0

THRESHOLD_STATUS = "잠정 (표본 6건). 재보정: 신규 10건 누적 시 / PASS 후 하류 실패 발생 시"


def read_glb_json(path):
    with open(path, "rb") as f:
        raw = f.read()
    magic, _, total = struct.unpack("<III", raw[:12])
    if magic != 0x46546C67:
        raise RuntimeError(f"glTF 바이너리가 아님: {path}")
    off = 12
    while off < total:
        ln, typ = struct.unpack_from("<II", raw, off)
        if typ == 0x4E4F534A:
            return json.loads(raw[off + 8: off + 8 + ln].decode("utf-8"))
        off += 8 + ln
    raise RuntimeError(f"JSON 청크를 찾지 못함: {path}")


def mesh_counts(js):
    acc = js.get("accessors", [])
    v = f_ = 0
    for m in js.get("meshes", []):
        for prim in m.get("primitives", []):
            pi = prim.get("attributes", {}).get("POSITION")
            if pi is not None:
                v += acc[pi]["count"]
            ii = prim.get("indices")
            if ii is not None:
                f_ += acc[ii]["count"] // 3
    return v, f_


def texture_slot_index(js, slot):
    """slot('metallicRoughness'/'baseColor') 이 쓰는 이미지 인덱스."""
    key = {"metallicRoughness": "metallicRoughnessTexture",
           "baseColor": "baseColorTexture"}[slot]
    for mat in js.get("materials", []):
        pbr = mat.get("pbrMetallicRoughness", {})
        node = pbr.get(key)
        if not node:
            continue
        t = js["textures"][node["index"]]
        src = t.get("source")
        if src is None:                       # EXT_texture_webp 등 확장
            for ext in (t.get("extensions") or {}).values():
                if isinstance(ext, dict) and "source" in ext:
                    src = ext["source"]
                    break
        return src
    return None


def measure(glb_path, tex_dir, decimation_target):
    js = read_glb_json(glb_path)
    verts, faces = mesh_counts(js)
    factors = [m.get("pbrMetallicRoughness", {}).get("metallicFactor", 1.0)
               for m in js.get("materials", [])]
    mf = max(factors) if factors else 1.0

    tex_b = None
    idx = texture_slot_index(js, "metallicRoughness")
    if idx is not None and tex_dir and os.path.isdir(tex_dir):
        # glb_tex.py 는 <이름>_tex_<i>.png 로 뽑는데, 후처리 사본은 GLB 파일명이
        # 달라져 이름으로만 찾으면 빗나간다 (zombie1_1024_dielectric.glb 가
        # zombie1_1024_tex_1.png 를 쓴다). 이름 규칙을 먼저 보고, 없으면 폴더에서
        # 같은 인덱스를 가진 파일을 찾는다.
        name = os.path.splitext(os.path.basename(glb_path))[0]
        cands = [os.path.join(tex_dir, f"{name}_tex_{idx}.png")]
        cands += sorted(glob.glob(os.path.join(tex_dir, f"*_tex_{idx}.png")))
        for c in cands:
            if os.path.exists(c):
                a = np.array(Image.open(c).convert("RGB"))
                tex_b = float(a[:, :, 2].mean())
                break

    # metallicFactor 가 0 이면 최종 metallic 은 텍스처와 무관하게 0 이다.
    # 이때는 텍스처를 못 읽어도 "측정 불가" 가 아니라 확정 0 이다.
    if mf == 0.0:
        effective = 0.0
    else:
        effective = None if tex_b is None else round(tex_b * mf, 3)
    return {
        "vertices": verts,
        "faces": faces,
        "decimation_target": decimation_target,
        "decimation_ratio": round(verts / float(decimation_target), 4) if decimation_target else None,
        "metallic_factor": mf,
        "metallic_texture_b_mean": None if tex_b is None else round(tex_b, 3),
        "metallic_effective": effective,
        "glb_mb": round(os.path.getsize(glb_path) / 2 ** 20, 2),
    }


def judge(m):
    reasons, warnings = [], []
    eff = m.get("metallic_effective")
    if eff is None:
        # 측정 실패를 통과로 처리하면 게이트가 조용히 무력해진다. 텍스처가 없는
        # 산출물은 그 자체로 불완전하므로 불합격시킨다 (2026-09-15 오탐 시험에서
        # 후처리 사본이 "측정 불가" 덕에 통과하던 것을 잡아 고쳤다).
        reasons.append(
            "metallicRoughness 텍스처를 읽지 못해 metallic 을 판정할 수 없다 — "
            "측정 불가를 통과로 처리하지 않는다. --textures 경로를 확인할 것")
    elif eff > METALLIC_MAX:
        reasons.append(
            f"유효 metallic {eff} > {METALLIC_MAX} — 모델이 재질을 금속으로 오판했다. "
            f"다른 seed 로 재생성을 먼저 시도할 것 (--force-dielectric 은 밝기만 되돌리고 "
            f"표면 디테일·채도는 복구하지 못한다)")
    elif eff > METALLIC_WARN:
        warnings.append(f"유효 metallic {eff} 이 {METALLIC_WARN} 을 넘는다 — 눈으로 확인할 것")
    r = m.get("decimation_ratio")
    if r is not None:
        if r < DECIMATION_RATIO_MIN:
            reasons.append(
                f"정점이 데시메이션 목표의 {r:.1%} 뿐이다 (< {DECIMATION_RATIO_MIN:.0%}) — "
                f"생성이 빈약했다는 신호")
        elif r > DECIMATION_RATIO_MAX:
            reasons.append(
                f"정점이 데시메이션 목표의 {r:.1%} 다 (> {DECIMATION_RATIO_MAX:.0%}) — "
                f"데시메이션이 동작하지 않았다")
    return ("FAIL" if reasons else "PASS"), reasons, warnings


def parse_args():
    ap = argparse.ArgumentParser(description="G2 게이트 — TRELLIS GLB 외형 품질 판정")
    ap.add_argument("--glb", required=True, help="판정할 GLB")
    ap.add_argument("--out", required=True, help="판정 결과를 쓸 폴더")
    ap.add_argument("--name", default=None, help="샘플 이름. 기본값: --out 폴더 이름")
    ap.add_argument("--textures", default=None,
                    help="텍스처 폴더. 기본값: GLB 와 같은 폴더의 textures/")
    ap.add_argument("--decimation-target", type=int, default=1000000,
                    help="생성 때 쓴 값. params.json 이 있으면 그쪽을 우선한다")
    return ap.parse_args()


def main():
    a = parse_args()
    glb = os.path.expanduser(a.glb)
    out = os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)
    name = a.name or os.path.basename(os.path.normpath(out))
    tex_dir = os.path.expanduser(a.textures) if a.textures else os.path.join(os.path.dirname(glb), "textures")

    target = a.decimation_target
    pj = os.path.join(os.path.dirname(glb), "params.json")
    if os.path.exists(pj):
        try:
            target = json.load(open(pj)).get("decimation_target", target)
        except Exception:
            pass

    metrics = measure(glb, tex_dir, target)
    verdict, reasons, warnings = judge(metrics)
    result = {
        "gate": "G2", "version": 1, "name": name, "verdict": verdict,
        "reasons": reasons, "warnings": warnings, "metrics": metrics,
        "thresholds": {
            "metallic_max": METALLIC_MAX, "metallic_warn": METALLIC_WARN,
            "decimation_ratio_min": DECIMATION_RATIO_MIN,
            "decimation_ratio_max": DECIMATION_RATIO_MAX,
            "status": THRESHOLD_STATUS,
        },
        "source": {"type": "glb", "path": a.glb},
    }
    path = os.path.join(out, "gate_g2.json")
    with open(path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    mark = "✅" if verdict == "PASS" else "❌"
    print(f"{mark} [{verdict}] {name}  metallic(유효) {metrics['metallic_effective']} "
          f"(텍스처B {metrics['metallic_texture_b_mean']} x factor {metrics['metallic_factor']})  "
          f"정점 {metrics['vertices']:,} ({metrics['decimation_ratio']:.0%})")
    for r in reasons:
        print(f"    사유: {r}")
    for w in warnings:
        print(f"    주의: {w}")
    print(f"    → {path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
