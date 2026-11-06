"""WHAM 이 추정한 SMPL 몸(카메라 좌표 정점)을 원본 영상에 투영해 점으로 그린다 — 공개 페이지용.
SMPL 모델 · 관절 회귀 행렬은 라이선스상 맥에 두지 않으므로 스켈레톤 대신 정점을 그린다.
카메라 내부 파라미터는 scripts/overlay_vis.py 와 같은 근사(f = 대각선 픽셀, 주점 = 화면 중심).
  python site_mesh_overlay.py <wham_output.pkl> <영상> <출력 mp4> [--every 6] [--seconds 6] [--start 0]"""
import sys

import cv2
import joblib
import numpy as np

pkl, video, out = sys.argv[1:4]
arg = lambda k, d: type(d)(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
every, seconds, start = arg("--every", 6), arg("--seconds", 6.0), arg("--start", 0)

d = joblib.load(pkl)
tr = d[max(d, key=lambda k: len(d[k]["frame_ids"]))]
fids = np.asarray(tr["frame_ids"])
verts = np.asarray(tr["verts"])[:, ::every]          # (T, V/every, 3)
m = {int(f): i for i, f in enumerate(fids)}

cap = cv2.VideoCapture(video)
W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = cap.get(cv2.CAP_PROP_FPS) or 24
f = (W ** 2 + H ** 2) ** 0.5
cx, cy = W / 2, H / 2
vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
n = drawn = 0
last = start + int(round(seconds * fps))
while True:
    ok, frame = cap.read()
    if not ok or n >= last:
        break
    if n >= start:
        if n in m:
            v = verts[m[n]]
            z = np.clip(v[:, 2], 1e-4, None)
            u = (f * v[:, 0] / z + cx).astype(int)
            w = (f * v[:, 1] / z + cy).astype(int)
            ok_ = (u >= 0) & (u < W) & (w >= 0) & (w < H)
            over = frame.copy()
            for x, y in zip(u[ok_], w[ok_]):
                cv2.circle(over, (int(x), int(y)), 2, (40, 180, 255), -1)
            frame = cv2.addWeighted(over, 0.55, frame, 0.45, 0)
            drawn += 1
        vw.write(frame)
    n += 1
vw.release()
print("OVERLAY_DONE", out, f"{drawn} 프레임에 정점 투영 (정점 {verts.shape[1]}개 표본)")
