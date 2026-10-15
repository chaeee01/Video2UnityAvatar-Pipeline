"""G1a 후보 + 전 프레임의 벌림각 · 선명도 · 테두리 여유 · 정지도 (보고용, 아무것도 고르지 않는다)."""
import glob, json, os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import select_keyframes as sk
n = sys.argv[1]; D = os.path.join(os.environ.get("PIPELINE_VOL", "/workspace"), "data")
fids, pose = sk.load_wham_track(f"{D}/04_wham/{n}_masked/wham_output.pkl"); R = sk._rot
def arm(p, side):
    G = np.eye(3)
    for j in (0, 3, 6, 9): G = G @ R(p[j])
    col, sh = (13, 16) if side == "L" else (14, 17)
    d = G @ R(p[col]) @ R(p[sh]) @ np.array([1.0 if side == "L" else -1.0, 0, 0])
    return float(np.degrees(np.arccos(np.clip(d @ (G @ np.array([0, -1.0, 0])), -1, 1))))
masks = sorted(glob.glob(f"{D}/02_sam2/{n}/masks/*.png")); cap = cv2.VideoCapture(f"{D}/00_raw/{n}.mp4"); rows = {}; prev = None
for i, f in enumerate(fids):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f); ok, im = cap.read(); g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    m = cv2.imread(masks[f], 0) > 127; ys, xs = np.where(m); h, w = m.shape
    rows[int(f)] = dict(L=arm(pose[i], "L"), R=arm(pose[i], "R"), elbowL=float(np.degrees(np.linalg.norm(pose[i][18]))), elbowR=float(np.degrees(np.linalg.norm(pose[i][19]))),
                        gaze=sk.gaze_offaxis_deg(pose[i]), edge_lr=int(min(xs.min(), w - 1 - xs.max())), edge_tb=int(min(ys.min(), h - 1 - ys.max())),
                        sharp=float(cv2.Laplacian(g, cv2.CV_64F)[m].var()), mot=0.0 if prev is None else float(np.abs(g.astype(int) - prev.astype(int))[m].mean()))
    prev = g
A = lambda k: np.array([r[k] for r in rows.values()])
print(f"{n}: 프레임 {len(rows)} | 위팔 벌림각 L {A('L').min():.1f}~{A('L').max():.1f}° R {A('R').min():.1f}~{A('R').max():.1f}° | 팔꿈치 굽힘 L {A('elbowL').mean():.0f}° R {A('elbowR').mean():.0f}° | 시선 {A('gaze').min():.1f}~{A('gaze').max():.1f}° | 선명도 {A('sharp').min():.0f}~{A('sharp').max():.0f} (중앙값 {np.median(A('sharp')):.0f}) | 좌우 여유 {A('edge_lr').min()}~{A('edge_lr').max()}px | 프레임간 움직임 평균 {A('mot')[1:].mean():.2f}")
c = json.load(open(f"{D}/02_sam2/{n}/keyframes/candidates.json"))
print("  G1a 후보:")
for i, t in enumerate(c["topk"], 1):
    r = rows[t["frame"]]; print(f"   #{i} f{t['frame']}: 점수 {t.get('score_adj', t['score'])} | 벌림각 L {r['L']:.1f}° R {r['R']:.1f}° | 시선 {r['gaze']:.1f}° | 선명도 {r['sharp']:.0f} | 좌우 여유 {r['edge_lr']}px 상하 {r['edge_tb']}px | 움직임 {r['mot']:.1f} | 다리 {t.get('leg_gap')}")
json.dump(rows, open(f"{D}/02_sam2/{n}/_kf_metrics.json", "w"))
