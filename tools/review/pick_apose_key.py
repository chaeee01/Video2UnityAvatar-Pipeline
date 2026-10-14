"""외형 전용 영상의 키프레임을 규칙으로 고른다 (Pod, wham 환경). 사람 확인 없이 도는 야간 큐용.

  python pick_apose_key.py <샘플>      → 표준출력 마지막 줄에 키프레임 PNG 경로, 없으면 종료 코드 3

조건: 양팔 벌림각 [25°, 50°] (WHAM, 몸통 아래 방향 기준) · 마스크가 화면 테두리에서 25px 이상 ·
시선각 30° 이하. 그중 **정지 구간**(앞뒤 프레임과의 차이가 작은 것)에서 가장 선명한 프레임.
2026-10-12 의 1차 외형 영상에서 손으로 고르던 기준을 그대로 옮긴 것이다.
"""
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

masks = sorted(glob.glob(f"{D}/02_sam2/{n}/masks/*.png")); cap = cv2.VideoCapture(f"{D}/00_raw/{n}.mp4")
rows, prev = [], None
for i, f in enumerate(fids):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f); ok, im = cap.read(); g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    m = cv2.imread(masks[f], 0) > 127; ys, xs = np.where(m); h, w = m.shape
    rows.append(dict(f=int(f), L=arm(pose[i], "L"), R=arm(pose[i], "R"), gaze=sk.gaze_offaxis_deg(pose[i]),
                     edge=int(min(xs.min(), w - 1 - xs.max(), ys.min(), h - 1 - ys.max())),
                     sharp=float(cv2.Laplacian(g, cv2.CV_64F)[m].var()),
                     mot=0.0 if prev is None else float(np.abs(g.astype(int) - prev.astype(int))[m].mean())))
    prev = g
for i, r in enumerate(rows):                       # 앞뒤 5프레임의 평균 움직임 — 정지 구간인가
    r["still"] = float(np.mean([q["mot"] for q in rows[max(0, i - 5):i + 6]]))
A = np.array([[r["L"], r["R"]] for r in rows])
print(f"{n}: 위팔 벌림각 L {A[:,0].min():.0f}~{A[:,0].max():.0f}° R {A[:,1].min():.0f}~{A[:,1].max():.0f}°")
pick, used = None, None
for lo, hi in ((25, 50), (20, 60)):
    ok = [r for r in rows if lo <= min(r["L"], r["R"]) and max(r["L"], r["R"]) <= hi and r["edge"] >= 25 and r["gaze"] <= 30]
    print(f"  조건 [{lo}, {hi}]° · 여유 ≥25px · 시선 ≤30°: {len(ok)}프레임")
    if ok:
        ok.sort(key=lambda r: (round(r["still"]), -r["sharp"])); pick, used = ok[0], (lo, hi); break
rec = {"sample": n, "pick": pick, "range": used, "frames": len(rows), "candidates_top": sorted(rows, key=lambda r: r["still"])[:5]}
os.makedirs(f"{D}/02_sam2/{n}/_custom", exist_ok=True); json.dump(rec, open(f"{D}/02_sam2/{n}/_custom/pick_apose.json", "w"), ensure_ascii=False, indent=1)
if not pick:
    print("  조건을 만족하는 프레임이 없다 — 키프레임을 고르지 않는다"); sys.exit(3)
f = pick["f"]; cap.set(cv2.CAP_PROP_POS_FRAMES, f); ok_, src = cap.read(); m = cv2.imread(masks[f], 0) > 127
rgba = np.zeros(m.shape + (4,), np.uint8); rgba[m, 0:3] = src[m]; rgba[m, 3] = 255
p = f"{D}/02_sam2/{n}/_custom/key0_f{f:05d}.png"; cv2.imwrite(p, rgba)
print(f"  선정 f{f}: L {pick['L']:.1f} R {pick['R']:.1f} 시선 {pick['gaze']:.1f} 여유 {pick['edge']}px 선명 {pick['sharp']:.0f} 정지도 {pick['still']:.1f}")
print(p)
