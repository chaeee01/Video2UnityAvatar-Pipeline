#!/usr/bin/env python3
"""톤 매칭: 메쉬 텍스처의 색 분포를 레퍼런스 이미지에 맞춘 사본을 만든다 (원본 텍스처는 건드리지 않는다).

  python3 tonematch.py --flat <정면 텍스처 렌더 PNG (render_diag.py --mode flat)> --ref <레퍼런스 PNG> \
      --tex <…/textures/<샘플>_tex_0.png> --out <…/textures/<샘플>_tex_0_tonematch_<날짜>.png>

정면에서 본 메쉬의 인물 픽셀과 레퍼런스의 인물 픽셀을 LAB 로 옮겨, 채널별 평균 · 표준편차를
맞추는 변환(Reinhard)을 구한 뒤 아틀라스 전체에 건다. 색은 돌아오지만 뭉개진 세부(얼굴 주름 ·
누비 무늬)는 돌아오지 않는다.

**자동 적용하지 않는다.** 원본과 톤 매칭판을 같은 조명으로 렌더해 나란히 보고 사람이 고른다
(2026-10-13 listener_apose_05: 수치는 레퍼런스 대비 ΔE 27.4 → 3.2 였으나 사용자가 원본을 골랐다).
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import silhouette


def _stats(im, m):
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB).astype(np.float32)
    return lab[m].mean(0), lab[m].std(0)


def match(tex, flat, ref):
    """tex(BGR 또는 BGRA 아틀라스)를 flat 의 인물 색 통계 → ref 의 인물 색 통계로 옮긴 사본."""
    bg = flat[5, 5].astype(int)
    ms, ss = _stats(flat, np.abs(flat.astype(int) - bg).sum(2) > 25)
    ref = cv2.resize(ref, (900, int(ref.shape[0] * 900 / ref.shape[1])))
    mr, sr = _stats(ref, silhouette.foreground(ref))
    lab = cv2.cvtColor(tex[:, :, :3], cv2.COLOR_BGR2LAB).astype(np.float32)
    out = cv2.cvtColor(np.clip((lab - ms) / np.maximum(ss, 1e-3) * sr + mr, 0, 255).astype(np.uint8),
                       cv2.COLOR_LAB2BGR)
    if tex.shape[2] == 4:
        out = np.dstack([out, tex[:, :, 3]])
    return out


def main():
    ap = argparse.ArgumentParser(description="텍스처 톤 매칭 사본 만들기")
    for x in ("--flat", "--ref", "--tex", "--out"):
        ap.add_argument(x, required=True)
    a = ap.parse_args()
    if os.path.exists(a.out):
        print(f"[오류] 이미 있다 — 덮어쓰지 않는다: {a.out}")
        return 1
    for p in (a.flat, a.ref, a.tex):
        if not os.path.exists(p):
            print(f"[오류] 파일이 없다: {p}")
            return 1
    out = match(cv2.imread(a.tex, cv2.IMREAD_UNCHANGED), cv2.imread(a.flat), cv2.imread(a.ref))
    cv2.imwrite(a.out, out)
    print("저장:", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
