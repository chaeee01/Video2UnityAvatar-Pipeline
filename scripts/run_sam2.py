"""
SAM2 좀비 분리: 영상 한 편에서 마스크·마스킹 클립·키프레임 후보를 뽑는다.

notebooks/sam2/SAM2_try6_260711.ipynb 를 Pod 실행용으로 정제한 것.
첫 프레임의 좀비 위치를 점 하나로 지정하면 SAM2가 전 프레임을 추적한다.

  python run_sam2.py --video /workspace/data/00_raw/zombie_sample1.mp4 \
      --out /workspace/data/02_sam2/zombie_sample1 \
      --point 640,360

출력 (--out 아래):
  frames/            SAM2 입력용 원본 프레임 (jpg, 중간 산출물)
  masks/             프레임별 마스크 PNG (흑백 8bit)
  keyframes/         알파 키프레임 후보 RGBA PNG (TRELLIS 입력용)
  <영상명>_masked.mp4  배경을 검게 지운 클립 (WHAM 입력용)
  keyframes/candidates.json  후보 선정 근거 (프레임 번호·점수)

노트북과 달라진 점:
  - Colab/드라이브 경로 하드코딩 제거 → 전부 인자, 기본값은 /workspace 기준
  - 좌표 [640, 360] 하드코딩 제거 → --point, 미지정 시 실제 해상도의 중앙
  - fps 30 하드코딩 제거 → 원본 영상의 fps 를 읽어 사용
  - 전 프레임 RGBA PNG 저장은 기본 끔 (--save-rgba). 디스크 대부분을 먹는데
    후속 단계가 쓰는 건 마스크·클립·키프레임뿐이라서.
  - 클립은 PNG 시퀀스를 다시 읽지 않고 추적 루프에서 ffmpeg 로 바로 기록
    (1-pass, h264/yuv420p). 노트북의 mp4v 출력은 브라우저에서 재생 불가
  - 시각화 셀([추가1~3], 코랩 재생용 셀)은 제외
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

import cv2
import numpy as np
from tqdm import tqdm

# 키프레임 점수·선정은 select_keyframes.py 로 옮겼다 (2026-10-08, G1a 독립화).
# S2 는 마스크만으로 1차 후보를 내고, S5 뒤의 재선정 단계가 같은 모듈로 다시 매긴다.
import silhouette
from select_keyframes import (LEG_OK, LEG_SIGNAL_P, apply_leg_term, export_keyframes,
                              keyframe_score, leg_gap_ratio, pick_keyframes,
                              write_candidates)


def parse_args():
    ap = argparse.ArgumentParser()
    # 샘플명을 기본값에 박지 않는다 (docs/CONVENTIONS.md 2절). 규약 경로는
    # /workspace/data/00_raw/<샘플>.mp4 -> /workspace/data/02_sam2/<샘플>/ 이다.
    ap.add_argument("--video", required=True,
                    help="입력 영상 (예: /workspace/data/00_raw/zombie_sample1.mp4)")
    ap.add_argument("--out", required=True,
                    help="출력 폴더 (예: /workspace/data/02_sam2/zombie_sample1)")
    ap.add_argument("--prompt", choices=["auto6", "auto10", "box", "point"], default=None,
                    help="첫 프레임 프롬프트. auto6 · auto10 = 실루엣 위에 점 6개 · 10개, "
                         "box = 실루엣 bbox, point = --point 의 좌표. 기본: --point 가 있으면 "
                         "point, 없으면 auto6. 근거는 scripts/silhouette.py 독스트링")
    ap.add_argument("--point", default=None,
                    help="첫 프레임의 대상 좌표 'x,y'. 여러 점은 ';' 로 잇는다 "
                         "(예: 540,250;380,520). --prompt point 와 함께 쓴다")
    ap.add_argument("--sam2-root", default="/workspace/repos/sam2",
                    help="SAM2 소스 루트 (pip install -e . 한 경로)")
    ap.add_argument("--checkpoint", default=None,
                    help="가중치. 기본값: <sam2-root>/checkpoints/sam2.1_hiera_large.pt")
    ap.add_argument("--model-cfg", default="configs/sam2.1/sam2.1_hiera_l.yaml")
    ap.add_argument("--obj-id", type=int, default=1)
    ap.add_argument("--topk", type=int, default=5,
                    help="저장할 키프레임 후보 개수")
    ap.add_argument("--keyframe-min-gap", type=int, default=20,
                    help="후보 사이 최소 프레임 간격 (기본 20). 0 이면 제약 없음 — "
                         "옛 동작이다. 근거는 select_keyframes.pick_keyframes() 독스트링")
    ap.add_argument("--leg-term", choices=["on", "off"], default="on",
                    help="다리 벌어짐 감점항 (기본 on). off 는 2026-10-07 이전 동작 "
                         "재현용 — 근거는 select_keyframes.leg_gap_ratio() 독스트링")
    ap.add_argument("--save-rgba", action="store_true",
                    help="전 프레임 RGBA PNG 도 저장 (노트북 동작)")
    ap.add_argument("--keep-frames", action="store_true",
                    help="중간 산출물 frames/ 를 지우지 않고 남김")
    return ap.parse_args()


def extract_frames(video_path, frames_dir):
    """영상을 SAM2 가 읽는 jpg 시퀀스로 쪼갠다. fps 도 함께 돌려준다."""
    os.makedirs(frames_dir, exist_ok=True)
    cam = cv2.VideoCapture(video_path)
    if not cam.isOpened():
        raise RuntimeError(f"영상을 열지 못함: {video_path}")
    fps = cam.get(cv2.CAP_PROP_FPS) or 30.0        # 노트북은 30 고정이었음
    n = 0
    h = w = None
    while True:
        ok, frame = cam.read()
        if not ok:
            break
        if h is None:                              # 첫 프레임에서 해상도 확보.
            h, w = frame.shape[:2]                 # 마지막 read 실패 시 frame 은 None
        cv2.imwrite(os.path.join(frames_dir, f"{n:05d}.jpg"), frame)
        n += 1
    cam.release()
    if n == 0:
        raise RuntimeError(f"프레임을 하나도 읽지 못함: {video_path}")
    print(f"[1/4] 프레임 {n}장 추출 ({w}x{h}, {fps:.2f}fps) → {frames_dir}")
    return n, fps, (w, h)


def load_predictor(args):
    """SAM2 예측기 탑재. 노트북의 sys.path 하드코딩을 --sam2-root 로 대체."""
    root = os.path.expanduser(args.sam2_root)
    for p in (root, os.path.join(root, "sam2")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import torch
    from sam2.build_sam import build_sam2_video_predictor

    ckpt = args.checkpoint or os.path.join(root, "checkpoints", "sam2.1_hiera_large.pt")
    if not os.path.exists(ckpt):
        raise RuntimeError(f"가중치가 없음: {ckpt}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[2/4] 예측기 탑재 (device={device}, cfg={args.model_cfg})")
    return build_sam2_video_predictor(args.model_cfg, ckpt, device=device), torch, device


def parse_points(text):
    """'x,y;x,y' → [(x, y), ...]"""
    pts = []
    for part in text.split(";"):
        x, y = (int(v) for v in part.split(","))
        pts.append((x, y))
    return pts


def build_prompt(args, frame0, out):
    """첫 프레임 프롬프트를 정하고 <out>/prompt.json · silhouette0.png 로 남긴다.

    실루엣은 프롬프트가 point 여도 뽑는다 — 게이트(gate_s2)의 부위 분포 판정이 그것을
    쓴다. 다만 point 일 때는 실루엣 실패로 멈추지 않는다(사람이 좌표를 직접 준 경우다).
    auto · box 에서 실루엣을 못 뽑으면 **멈춘다** — 점 하나로 조용히 돌아가지 않는다.
    """
    mode = args.prompt or ("point" if args.point else "auto6")
    if mode == "point" and not args.point:
        raise SystemExit("[중단] --prompt point 에는 --point 가 필요하다")
    fg, err = None, None
    try:
        fg = silhouette.foreground(frame0)
    except silhouette.SilhouetteError as e:
        err = str(e)
        if mode != "point":
            raise SystemExit(f"[중단] 첫 프레임에서 실루엣을 뽑지 못했다 — {e}\n"
                             f"       입력 조건(단색 배경 · 전신)을 확인하거나 --prompt point "
                             f"--point x,y[;x,y...] 로 좌표를 직접 준다.")
    prompt = {"mode": mode, "points": None, "box": None, "silhouette_error": err}
    if mode == "point":
        prompt["points"] = parse_points(args.point)
    elif mode == "box":
        prompt["box"] = list(silhouette.bbox(fg))
    else:
        prompt["points"] = silhouette.prompt_points(fg, 6 if mode == "auto6" else 10)
    sil = os.path.join(out, "silhouette0.png")
    if fg is not None:
        prompt["silhouette_bbox"] = list(silhouette.bbox(fg))
        cv2.imwrite(sil, fg.astype(np.uint8) * 255)
    elif os.path.exists(sil):
        os.remove(sil)                     # 이전 시도의 실루엣이 남아 판정에 쓰이지 않게
    with open(os.path.join(out, "prompt.json"), "w") as f:
        json.dump(prompt, f, ensure_ascii=False, indent=1)
    what = (f"상자 {prompt['box']}" if mode == "box"
            else f"점 {len(prompt['points'])}개 {prompt['points']}")
    print(f"      프롬프트 {mode}: {what}")
    return prompt


def main():
    args = parse_args()
    out = os.path.expanduser(args.out)
    frames_dir = os.path.join(out, "frames")
    masks_dir = os.path.join(out, "masks")
    keys_dir = os.path.join(out, "keyframes")
    rgba_dir = os.path.join(out, "rgba")
    for d in (masks_dir, keys_dir):
        os.makedirs(d, exist_ok=True)
    if args.save_rgba:
        os.makedirs(rgba_dir, exist_ok=True)

    n_frames, fps, (w, h) = extract_frames(os.path.expanduser(args.video), frames_dir)

    prompt = build_prompt(args, cv2.imread(os.path.join(frames_dir, "00000.jpg")), out)

    predictor, torch, device = load_predictor(args)
    state = predictor.init_state(video_path=frames_dir)
    if prompt["mode"] == "box":
        predictor.add_new_points_or_box(
            inference_state=state, frame_idx=0, obj_id=args.obj_id,
            box=np.array(prompt["box"], dtype=np.float32))
    else:
        predictor.add_new_points_or_box(
            inference_state=state, frame_idx=0, obj_id=args.obj_id,
            points=np.array(prompt["points"], dtype=np.float32),
            labels=np.ones(len(prompt["points"]), dtype=np.int32))   # 1 = 전경

    # 클립은 프레임을 ffmpeg 에 그대로 흘려보내 h264 로 굽는다. OpenCV 의 mp4v
    # 출력물은 브라우저·Jupyter 에서 재생되지 않아 Pod 검증 때 교체했다.
    name = os.path.splitext(os.path.basename(args.video))[0]
    final_mp4 = os.path.join(out, f"{name}_masked.mp4")
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 이 필요하다 (마스킹 클립 h264 인코딩)")
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}",
         "-i", "-", "-an",
         "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",   # yuv420p 는 짝수 해상도만 됨
         "-vcodec", "libx264", "-pix_fmt", "yuv420p", final_mp4],
        stdin=subprocess.PIPE)

    print(f"[3/4] 추적 + 마스크/클립 기록 ({n_frames}프레임)")
    scores = []
    autocast = (torch.autocast("cuda", dtype=torch.bfloat16)
                if device == "cuda" else torch.autocast("cpu", enabled=False))
    with torch.inference_mode(), autocast:
        for idx, obj_ids, logits in tqdm(
                predictor.propagate_in_video(state), total=n_frames):
            src = cv2.imread(os.path.join(frames_dir, f"{idx:05d}.jpg"))
            mask = np.zeros((h, w), dtype=bool)
            for i, _ in enumerate(obj_ids):
                mask |= (logits[i] > 0.0).cpu().numpy().squeeze()

            cv2.imwrite(os.path.join(masks_dir, f"{idx:05d}.png"),
                        mask.astype(np.uint8) * 255)

            masked = np.zeros_like(src)          # 배경 검정 3채널 (WHAM 입력 규약)
            masked[mask] = src[mask]
            enc.stdin.write(masked.tobytes())

            if args.save_rgba:
                rgba = np.zeros((h, w, 4), dtype=np.uint8)
                rgba[mask, 0:3] = src[mask]
                rgba[mask, 3] = 255
                cv2.imwrite(os.path.join(rgba_dir, f"{idx:05d}.png"), rgba)

            s, bbox = keyframe_score(mask)
            scores.append({"frame": int(idx), "score": round(float(s), 4), "bbox": bbox,
                           "leg_gap": round(leg_gap_ratio(mask), 4)})
    enc.stdin.close()
    if enc.wait() != 0:
        raise RuntimeError(f"ffmpeg 인코딩 실패: {final_mp4}")

    # 키프레임 후보: 점수 상위 K개를 알파 PNG 로 저장
    leg_state, leg_signal = apply_leg_term(scores, enabled=(args.leg_term == "on"))
    ranked = pick_keyframes(scores, args.topk, args.keyframe_min_gap)
    export_keyframes(ranked,
                     lambda i: cv2.imread(os.path.join(frames_dir, f"{i:05d}.jpg")),
                     masks_dir, keys_dir)
    write_candidates(keys_dir, ranked, scores, args.keyframe_min_gap, leg_state, leg_signal)
    why = {"on": "작동", "off_user": "꺼짐(사용자 지정)",
           "off_no_signal": "꺼짐(가드)"}[leg_state]
    print(f"[4/4] 키프레임 후보 {len(ranked)}장 (최소 간격 {args.keyframe_min_gap}, "
          f"다리 항 {why}) → {keys_dir}")
    if leg_state == "off_no_signal":
        # 조용히 넘기지 않는다. 판정은 WHAM 결과가 있는 재선정 단계의 몫이지만
        # (독스트링 참조) 그 단계가 생기기 전까지는 여기서 사람에게 알린다.
        print(f"      ⚠️  이 클립에는 다리가 벌어진 프레임이 없다 "
              f"(p{LEG_SIGNAL_P} 간격비 {leg_signal} < {LEG_OK}). 다리 항 없이 "
              f"구점수로 뽑았다. 동작에 다리 움직임이 있으면 다리가 붙은 메쉬는 "
              f"리깅에서 깨진다 — 후보를 눈으로 확인할 것.")
    print("      " + ", ".join(
        f"f{s['frame']}({s.get('score_adj', s['score'])}, 다리 {s['leg_gap']})"
        for s in ranked))

    if not args.keep_frames:
        shutil.rmtree(frames_dir)

    print(f"\n완료: {out}")
    print(f"  마스크 {n_frames}장 | 클립 {final_mp4}")


if __name__ == "__main__":
    main()
