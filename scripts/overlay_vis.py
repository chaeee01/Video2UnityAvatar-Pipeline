import argparse, pickle, joblib, numpy as np, cv2
from pathlib import Path

PARENTS = [-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19,20,21]

ap = argparse.ArgumentParser()
ap.add_argument("--pkl", required=True)
ap.add_argument("--video", required=True)
# --smpl-model: align_smpl_to_trellis.py 의 --smpl(SMPL OBJ 메쉬)과 이름이 겹치지 않도록
# 구분한다. 여기서 받는 건 SMPL 공식 모델 pkl 이다.
ap.add_argument("--smpl-model", default="/workspace/repos/WHAM/dataset/body_models/smpl/SMPL_NEUTRAL.pkl",
                help="SMPL 공식 모델 pkl (J_regressor 용)")
a = ap.parse_args()

# SMPL 공식 J_regressor 로 정점에서 관절 추출
with open(a.smpl_model, "rb") as f:
    smpl = pickle.load(f, encoding="latin1")
J = smpl["J_regressor"]
if hasattr(J, "toarray"):
    J = J.toarray()
J = np.asarray(J, dtype=np.float64)          # (24, 6890)

track = next(iter(joblib.load(a.pkl).values()))
verts = np.asarray(track["verts"])            # (T, 6890, 3) 카메라 좌표계
fids  = np.asarray(track["frame_ids"])
joints = np.einsum("jv,tvc->tjc", J, verts)   # (T, 24, 3)

cap = cv2.VideoCapture(a.video)
W  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
H  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
fps = cap.get(cv2.CAP_PROP_FPS) or 30

# WHAM 기본 카메라 내부 파라미터 근사
f = (W**2 + H**2) ** 0.5
cx, cy = W/2, H/2

out = str(Path(a.pkl).parent / "overlay.mp4")
vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))

m = {int(fid): i for i, fid in enumerate(fids)}
n = 0
while True:
    ok, frame = cap.read()
    if not ok:
        break
    if n in m:
        j3 = joints[m[n]]
        z = np.clip(j3[:, 2], 1e-4, None)
        u = (f * j3[:, 0] / z + cx).astype(int)
        v = (f * j3[:, 1] / z + cy).astype(int)
        for i, p in enumerate(PARENTS):
            if p >= 0:
                cv2.line(frame, (u[i], v[i]), (u[p], v[p]), (0, 165, 255), 3)
        for i in range(len(u)):
            cv2.circle(frame, (u[i], v[i]), 5, (255, 80, 0), -1)
    vw.write(frame)
    n += 1
cap.release(); vw.release()
print("저장:", out, f"| {n}프레임 중 {len(fids)}프레임에 스켈레톤")
