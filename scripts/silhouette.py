"""첫 프레임의 전경 실루엣 — S2 의 다중 점 프롬프트와 부위 분포 판정이 함께 쓴다.

입력 조건이 "단색 회색 배경 · 전신" 이라, 배경색에서 멀리 떨어진 픽셀을 모으면 SAM2 없이도
인물의 윤곽을 대강 얻는다. 정밀한 마스크가 아니라 **어디에 몸이 있는가**만 알면 되는 두 곳에
쓴다 (2026-10-12 설계):

  1. 프롬프트 점을 몸 위에 고르게 찍는다 — 점 하나로는 옷이 여러 겹인 캐릭터에서 한 겹만
     잡힌다. listener_walk_fwd 가 점 하나로 바지만(커버리지 11.7%), 손으로 찍은 6점으로
     전신(43.7%)이 잡혔다.
  2. SAM2 마스크가 몸의 위·아래를 모두 덮었는지 본다 — 위의 "바지만" 마스크는 커버리지
     하한 7% 를 넘어 게이트를 통과했다.

SAM2 · torch 를 쓰지 않는다. tests/ 에서 그대로 시험한다.
"""
import cv2
import numpy as np

EDGE = 40            # 좌우 테두리 띠 너비(px, 1080 폭 기준 — 폭에 비례해 줄인다)
DIST = 28.0          # 배경색에서 이만큼(LAB 거리) 떨어지면 전경. **확실한 곳만** 잡는다 —
                     # 14 로 두면 배경의 밝기 얼룩(stalker 머리 옆)과 바닥 그림자가 전경이 되어
                     # 프롬프트 점이 배경에 찍힌다. 대신 배경과 색이 비슷한 옷(walker 의 회색
                     # 셔츠)은 빠진다. 점을 찍고 위·아래를 가르는 데는 그것으로 충분하다.
                     # 2026-10-12 walker · listener · stalker 첫 프레임에서 맞춘 값이다.
AREA_MIN, AREA_MAX = 0.02, 0.70   # 실루엣이 프레임에서 차지하는 비율의 허용 범위
BG_SPREAD_MAX = 10.0              # 테두리 띠 안의 색 흩어짐(p90). 넘으면 배경이 단색이 아니다

# 점을 찍는 높이 — 실루엣 bbox 높이에 대한 비율. 머리 · 가슴 · 배 · 골반 · 무릎 · 정강이.
ROWS_6 = (0.10, 0.25, 0.40, 0.55, 0.70, 0.85)
# 2차 시도에서 좌우 점을 더하는 높이 — 어깨와 골반. 그 줄의 가장 넓은 구간을 4등분한 1·3번 점.
ROWS_SIDE = (0.25, 0.55)


class SilhouetteError(RuntimeError):
    """실루엣을 뽑지 못했다 — 입력 조건(단색 배경 · 전신) 위반 신호. 조용히 넘기지 않는다."""


def foreground(bgr):
    """BGR 프레임 → 전경 bool 마스크 (가장 큰 덩어리 하나)."""
    h, w = bgr.shape[:2]
    e = max(8, int(EDGE * w / 1080))
    lab = cv2.cvtColor(cv2.GaussianBlur(bgr, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    # Veo 영상은 좌우 끝 4~5px 이 검은 띠이고 그 옆 2~3px 이 밝게 번진다 (2026-10-12 실측).
    # 그 안쪽에서 띠를 뜬다.
    i0 = max(8, w // 100)
    # 배경은 완전한 단색이 아니다 — 위에서 아래로, 그리고 좌우로 밝기가 조금 기운다
    # (listener_walk_fwd 아래쪽에서 좌 147 · 우 119). 줄마다 좌우 띠의 색을 따로 재고
    # 그 사이를 직선으로 잇는다.
    k = max(3, (h // 10) | 1)

    def row_color(strip):
        row = np.median(strip, axis=1)
        # 팔을 벌려 테두리에 닿은 줄은 중앙값이 몸 색이 된다. 위아래 줄로 고르게 편다.
        pad = np.pad(row, ((k // 2, k // 2), (0, 0)), mode="edge")
        return np.stack([np.median(pad[i:i + k], axis=0) for i in range(h)])

    left, right = lab[:, i0:i0 + e], lab[:, -i0 - e:-i0]
    cl, cr = row_color(left), row_color(right)
    spread = float(np.percentile(np.concatenate([
        np.linalg.norm(left - cl[:, None, :], axis=2),
        np.linalg.norm(right - cr[:, None, :], axis=2)], axis=1), 90))
    if spread > BG_SPREAD_MAX:
        raise SilhouetteError(f"배경이 단색이 아니다 (테두리 색 흩어짐 {spread:.1f} > {BG_SPREAD_MAX})")
    t = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :, None]
    bg = cl[:, None, :] * (1 - t) + cr[:, None, :] * t
    m = (np.linalg.norm(lab - bg, axis=2) > DIST).astype(np.uint8)
    m[:, :i0] = 0
    m[:, -i0:] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    # 머리 · 몸통 · 다리가 색이 다른 옷으로 끊겨 있어도 한 덩어리로 잇는다
    kc = max(5, (w // 40) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((kc, kc), np.uint8))
    n, lab_cc, st, _ = cv2.connectedComponentsWithStats(m)
    if n < 2:
        raise SilhouetteError("전경이 없다 (배경과 구별되는 픽셀이 없음)")
    fg = lab_cc == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    area = float(fg.mean())
    if not (AREA_MIN <= area <= AREA_MAX):
        raise SilhouetteError(f"실루엣 면적 {100 * area:.1f}% 가 허용 범위 "
                              f"{100 * AREA_MIN:.0f}~{100 * AREA_MAX:.0f}% 밖이다")
    return fg


def bbox(fg):
    """(x0, y0, x1, y1) — 끝 포함."""
    ys, xs = np.where(fg.any(axis=1))[0], np.where(fg.any(axis=0))[0]
    return int(xs[0]), int(ys[0]), int(xs[-1]), int(ys[-1])


def _widest_run(line):
    """bool 한 줄에서 가장 긴 True 구간의 (시작, 끝). 없으면 None."""
    x = np.flatnonzero(np.diff(np.concatenate([[0], line.astype(np.int8), [0]])))
    if len(x) == 0:
        return None
    runs = x.reshape(-1, 2)
    a, b = runs[int(np.argmax(runs[:, 1] - runs[:, 0]))]
    return int(a), int(b - 1)


def prompt_points(fg, n=6):
    """실루엣 위의 프롬프트 점 [(x, y), ...]. n 은 6 또는 10.

    줄마다 **가장 넓은 전경 구간의 가운데**에 찍는다 — 실루엣의 무게중심에 찍으면 다리를
    벌린 줄에서 점이 다리 사이 빈 곳에 떨어진다.
    """
    if n not in (6, 10):
        raise ValueError(f"n 은 6 또는 10 이다: {n}")
    _, y0, _, y1 = bbox(fg)
    pts = []
    for r in ROWS_6:
        y = int(round(y0 + r * (y1 - y0)))
        run = _widest_run(fg[y])
        if run:
            pts.append(((run[0] + run[1]) // 2, y))
    if n == 10:
        for r in ROWS_SIDE:
            y = int(round(y0 + r * (y1 - y0)))
            run = _widest_run(fg[y])
            if run:
                q = (run[1] - run[0]) // 4
                pts += [(run[0] + q, y), (run[1] - q, y)]
    if len(pts) < 3:
        raise SilhouetteError(f"프롬프트 점을 {len(pts)}개밖에 찍지 못했다")
    return pts


def part_distribution(fg, mask):
    """마스크가 실루엣의 위·아래 절반을 얼마나 덮는가 + 높이 비.

    upper · lower  실루엣 bbox 를 위아래로 반 갈라, 그 안의 실루엣 픽셀 중 마스크가 덮은 비율
    height_ratio   마스크 높이 ÷ 실루엣 높이
    """
    _, y0, _, y1 = bbox(fg)
    mid = (y0 + y1) // 2
    both = fg & mask

    def recall(sl):
        return float(both[sl].sum() / max(1, fg[sl].sum()))

    my = np.where(mask.any(axis=1))[0]
    return {"upper": round(recall(slice(y0, mid)), 3),
            "lower": round(recall(slice(mid, y1 + 1)), 3),
            "height_ratio": round(float((my[-1] - my[0]) / max(1, y1 - y0)), 3) if len(my) else 0.0}
