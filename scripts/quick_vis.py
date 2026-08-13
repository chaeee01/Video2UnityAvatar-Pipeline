import argparse, joblib, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter
from pathlib import Path

PARENTS = [-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19,20,21]
IDX = [3500,1000,4500,3000,1100,4600,3020,3300,6700,3040,3400,6800,
       300,1300,4800,400,1350,4850,1600,5100,2100,5600,2200,5700]

ap = argparse.ArgumentParser()
ap.add_argument("--pkl", required=True)
ap.add_argument("--fps", type=int, default=30)
a = ap.parse_args()

track = next(iter(joblib.load(a.pkl).values()))
j = np.asarray(track["verts"])[:, IDX, :].copy()
j[..., 1] *= -1
T = len(j)
print(f"프레임 {T}")

lo, hi = j.reshape(-1,3).min(0), j.reshape(-1,3).max(0)
c, s = (lo+hi)/2, float((hi-lo).max())*0.6

fig = plt.figure(figsize=(6,8))
ax = fig.add_subplot(111, projection="3d")
out = str(Path(a.pkl).parent / "skeleton_preview.mp4")

with FFMpegWriter(fps=a.fps, bitrate=2000).saving(fig, out, dpi=100) as w:
    for t in range(T):
        ax.clear()
        for i, p in enumerate(PARENTS):
            if p >= 0:
                ax.plot(*zip(j[t][i], j[t][p]), color="tab:orange", lw=2)
        ax.scatter(j[t][:,0], j[t][:,1], j[t][:,2], s=12)
        ax.set_xlim(c[0]-s, c[0]+s); ax.set_ylim(c[1]-s, c[1]+s); ax.set_zlim(c[2]-s, c[2]+s)
        ax.set_box_aspect([1,1,1]); ax.view_init(elev=10, azim=-70)
        ax.set_title(f"frame {t+1}/{T}"); ax.set_axis_off()
        w.grab_frame()
print("저장:", out)
