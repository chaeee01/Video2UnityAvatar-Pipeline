#!/usr/bin/env python3
"""
첫 프레임에 좌표 격자를 얹어 저장한다 — 사람이 --point 를 읽기 위한 것.

  python frame_grid.py --video <영상> --out <출력.png> [--step 100] [--frame 0]

오케스트레이터가 S2 게이트 상한에 걸려 멈출 때 자동으로 만든다(설계 6절의 실전
보완). 사람은 이 그림에서 좌표를 읽어 --point 로 넘긴다.

눈금은 실제 픽셀 좌표다 — 리사이즈하지 않으므로 읽은 값을 그대로 쓰면 된다.
"""
import argparse

import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--step", type=int, default=100, help="격자 간격(px)")
    ap.add_argument("--frame", type=int, default=0, help="몇 번째 프레임")
    a = ap.parse_args()

    cap = cv2.VideoCapture(a.video)
    if a.frame:
        cap.set(cv2.CAP_PROP_POS_FRAMES, a.frame)
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"프레임을 읽지 못함: {a.video}")

    h, w = img.shape[:2]
    # 격자는 반투명으로 덧그린다 — 원본 색을 가리면 좌표를 고르기 어렵다.
    ov = img.copy()
    for x in range(0, w, a.step):
        cv2.line(ov, (x, 0), (x, h), (0, 220, 255), 1)
    for y in range(0, h, a.step):
        cv2.line(ov, (0, y), (w, y), (0, 220, 255), 1)
    img = cv2.addWeighted(ov, 0.45, img, 0.55, 0)

    # 눈금 숫자. 배경에 검은 띠를 깔아 흰 배경에서도 읽히게 한다.
    f, fs, th = cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
    for x in range(0, w, a.step * 2):
        cv2.rectangle(img, (x, 0), (x + 52, 18), (0, 0, 0), -1)
        cv2.putText(img, str(x), (x + 3, 13), f, fs, (0, 255, 255), th)
    for y in range(0, h, a.step * 2):
        cv2.rectangle(img, (0, y), (52, y + 18), (0, 0, 0), -1)
        cv2.putText(img, str(y), (3, y + 13), f, fs, (0, 255, 255), th)
    # 중앙 십자 — 기본 좌표가 어디였는지 바로 보이게
    cv2.drawMarker(img, (w // 2, h // 2), (0, 0, 255), cv2.MARKER_CROSS, 40, 2)

    cv2.imwrite(a.out, img)
    print(f"저장: {a.out}  ({w}x{h}, 격자 {a.step}px, 중앙 {w//2},{h//2})")


if __name__ == "__main__":
    main()
