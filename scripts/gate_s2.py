"""G0/S2 게이트: SAM2 마스크가 대상을 통째로 잡았는지 판정한다.

SAM2 는 첫 프레임의 점 하나로 대상을 지정하는데, 열린 겉옷 안으로 보이는 속옷을
찍으면 그 조각만 잡는다. 2026-09-10 의 4샘플 7회 실행에서 2샘플이 이 방식으로
실패했고(50%), 실패는 육안으로만 잡혔다. 이 게이트가 그 판정을 자동화한다.

  python gate_s2.py --masks ~/data/02_sam2/<샘플>/masks --frames 240 --out <폴더>
  python gate_s2.py --video ~/data/02_sam2/<샘플>/<샘플>_masked.mp4 --out <폴더>

--masks 는 SAM2 가 낸 마스크 PNG 폴더, --video 는 마스킹 클립이다. 클립에서도
마스크를 복원할 수 있어(배경이 검다) 마스크 폴더를 회수하지 못한 경우에 쓴다.
복원 오차는 2026-09-11 실측에서 -0.45 ~ +0.02 %p 였다 — 검은 옷에서 약간
낮게 잡힌다.

출력: <out>/gate_s2.json (오케스트레이터가 읽는다) + 표준출력 요약.
"""
import argparse
import glob
import json
import os
import sys

import cv2
import numpy as np

# ── 임계값과 근거 ────────────────────────────────────────────────────────────
# 2026-09-10 실측 (1280x720, 240프레임, 4샘플 7회 실행):
#
#   실행                 커버리지  빈프레임  조각수   실제
#   walker              9.21%      0       1.00    성공
#   stalker 2차         9.31%      0       1.00    성공
#   dog                12.44%      0       1.00    성공
#   zombie1(9/4)        ~3%*       0       1.00    성공   * 1세대 기록, 참고용
#   listener 1차(속옷)  3.00%      0       1.00    실패
#   listener 2차(겉옷)  6.04%      0       3.11    실패
#   listener 3차(얼굴)  0.81%      0       1.00    실패
#   stalker 1차(셔츠)   0.52%     54       2.48    실패
#
# 커버리지만으로는 못 가른다 — 성공 최저 9.21% 와 실패 최고 6.04% 사이에 갭이
# 있지만, 프레임을 꽉 채우는 근접 촬영이나 멀리 선 인물에서 이 갭은 무너진다.
# 그래서 세 지표를 AND 가 아니라 OR 로 묶어 하나라도 걸리면 불합격시킨다.
#
# COVERAGE_MIN = 7.0
#   성공 최저(9.21)와 실패 최고(6.04)의 사이. 산술 중점 7.6 보다 낮게 잡은 것은
#   실패를 놓치는 비용(잘못된 메쉬가 하류로 흘러 Pod 시간을 태움)보다 성공을
#   막는 비용(재실행 33초)이 싸기 때문이다. 경계에 걸리면 WARN 으로 표시해
#   사람이 보게 한다.
# COVERAGE_WARN = 9.0
#   성공 사례의 최저값 언저리. 여기~MIN 구간은 통과시키되 눈으로 확인하라는 뜻.
# EMPTY_MAX = 0
#   성공 4건은 빈 프레임이 0 이고 실패 1건만 54 였다. 추적이 끊긴 것이므로
#   한 프레임이라도 비면 불합격이다.
# PARTS_MAX = 1.5
#   성공 4건은 전부 정확히 1.00 (단일 연결 요소). 실패 2건은 2.48, 3.11.
#   1.5 는 "가끔 한 프레임에서 팔이 떨어져 보이는" 정도까지만 허용한다.
#   조각 수는 커버리지가 정상 범위여도 부분 선택을 잡아내는 유일한 지표다
#   (listener 2차: 커버리지 6.04% 로 애매했지만 조각 3.11 로 확정).
COVERAGE_MIN = 7.0
COVERAGE_WARN = 9.0
EMPTY_MAX = 0
PARTS_MAX = 1.5
EMPTY_COVERAGE = 0.5      # 이 값 미만이면 그 프레임은 "비었다"
MIN_BLOB_AREA = 50        # 이보다 작은 조각은 압축 잡음으로 보고 세지 않는다


def parse_args():
    ap = argparse.ArgumentParser(description="G0/S2 게이트 — SAM2 마스크 품질 판정")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--masks", help="마스크 PNG 폴더 (예: ~/data/02_sam2/<샘플>/masks)")
    src.add_argument("--video", help="마스킹 클립 mp4. 마스크 폴더가 없을 때 복원해 쓴다")
    ap.add_argument("--out", required=True, help="판정 결과를 쓸 폴더")
    ap.add_argument("--name", default=None, help="샘플 이름. 기본값: --out 폴더 이름")
    ap.add_argument("--frames", type=int, default=None,
                    help="기대 프레임 수. 주면 마스크 개수와 대조한다")
    ap.add_argument("--stride", type=int, default=1,
                    help="표본 간격. 1 이면 전 프레임 (기본). 클립 복원 시 속도용")
    return ap.parse_args()


def measure_from_masks(mask_dir, stride):
    files = sorted(glob.glob(os.path.join(mask_dir, "*.png")))
    if not files:
        raise RuntimeError(f"마스크 PNG 가 없음: {mask_dir}")
    out = []
    for i, f in enumerate(files):
        if i % stride:
            continue
        g = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        if g is None:
            raise RuntimeError(f"마스크를 읽지 못함: {f}")
        out.append((g > 127).astype(np.uint8))
    return out, len(files)


def measure_from_video(path, stride):
    cam = cv2.VideoCapture(path)
    if not cam.isOpened():
        raise RuntimeError(f"클립을 열지 못함: {path}")
    out, n = [], 0
    while True:
        ok, frame = cam.read()
        if not ok:
            break
        if n % stride == 0:
            # 배경이 검게 지워진 클립이므로 "검지 않은 곳" 이 마스크다.
            # h264 압축 잡음이 0 근처에서 흔들려 8 을 문턱으로 둔다.
            out.append((frame.max(axis=2) > 8).astype(np.uint8))
        n += 1
    cam.release()
    if not out:
        raise RuntimeError(f"프레임을 하나도 읽지 못함: {path}")
    return out, n


def measure(masks):
    """마스크 목록에서 판정 지표를 뽑는다. 판정과 분리해 둔다 — 오탐 시험에서
    기록된 수치만으로 판정 로직을 따로 시험할 수 있어야 하기 때문이다."""
    cov, parts, empty = [], [], 0
    for m in masks:
        c = float(m.mean() * 100)
        cov.append(c)
        if c < EMPTY_COVERAGE:
            empty += 1
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        parts.append(len([x for x in cnts if cv2.contourArea(x) > MIN_BLOB_AREA]))
    cov = np.array(cov, dtype=float)
    parts = np.array(parts, dtype=float)
    return {
        "frames_measured": len(masks),
        "coverage_mean": round(float(cov.mean()), 3),
        "coverage_min": round(float(cov.min()), 3),
        "coverage_max": round(float(cov.max()), 3),
        "coverage_std": round(float(cov.std()), 3),
        "empty_frames": int(empty),
        "parts_mean": round(float(parts.mean()), 3),
        "parts_max": int(parts.max()),
        "frames_multipart": int((parts > 1).sum()),
    }


def judge(metrics, expected_frames=None, frames_found=None):
    """지표 → PASS/FAIL. 측정과 분리된 순수 함수다."""
    reasons, warnings = [], []
    if metrics["coverage_mean"] < COVERAGE_MIN:
        reasons.append(
            f"커버리지 평균 {metrics['coverage_mean']}% < {COVERAGE_MIN}% — "
            f"대상의 일부만 잡혔을 가능성이 높다")
    elif metrics["coverage_mean"] < COVERAGE_WARN:
        warnings.append(
            f"커버리지 평균 {metrics['coverage_mean']}% 가 관측된 성공 최저치"
            f"({COVERAGE_WARN}%) 아래다 — 눈으로 확인할 것")
    if metrics["empty_frames"] > EMPTY_MAX:
        reasons.append(
            f"빈 프레임 {metrics['empty_frames']}개 — 추적이 끊겼다")
    if metrics["parts_mean"] > PARTS_MAX:
        reasons.append(
            f"조각 수 평균 {metrics['parts_mean']} > {PARTS_MAX} — "
            f"마스크가 여러 조각으로 갈라져 있다 (부분 선택 신호)")
    if expected_frames is not None and frames_found is not None and expected_frames != frames_found:
        reasons.append(f"마스크 {frames_found}장 ≠ 기대 프레임 {expected_frames}장")
    return ("FAIL" if reasons else "PASS"), reasons, warnings


def main():
    a = parse_args()
    os.makedirs(a.out, exist_ok=True)
    name = a.name or os.path.basename(os.path.normpath(a.out))
    if a.masks:
        masks, total = measure_from_masks(os.path.expanduser(a.masks), a.stride)
        source = {"type": "masks", "path": a.masks}
    else:
        masks, total = measure_from_video(os.path.expanduser(a.video), a.stride)
        source = {"type": "video", "path": a.video,
                  "note": "클립에서 복원한 마스크 (검은 옷에서 최대 0.5%p 낮게 잡힌다)"}
    metrics = measure(masks)
    verdict, reasons, warnings = judge(metrics, a.frames, total)
    result = {
        "gate": "S2",
        "version": 1,
        "name": name,
        "verdict": verdict,
        "reasons": reasons,
        "warnings": warnings,
        "metrics": metrics,
        "frames_total": total,
        "thresholds": {
            "coverage_min": COVERAGE_MIN, "coverage_warn": COVERAGE_WARN,
            "empty_max": EMPTY_MAX, "parts_max": PARTS_MAX,
        },
        "source": source,
    }
    path = os.path.join(a.out, "gate_s2.json")
    with open(path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    mark = "✅" if verdict == "PASS" else "❌"
    print(f"{mark} [{verdict}] {name}  커버리지 {metrics['coverage_mean']}% "
          f"빈 {metrics['empty_frames']} 조각 {metrics['parts_mean']}")
    for r in reasons:
        print(f"    사유: {r}")
    for w in warnings:
        print(f"    주의: {w}")
    print(f"    → {path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
