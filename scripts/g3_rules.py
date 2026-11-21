"""G3 판정 로직 — 재투영 일관성 (gate_g3.py 가 쓴다). numpy 만 쓴다 (bpy · torch 없음 — tests/ 에서 그대로 시험한다).

**무엇을 재나.** WHAM 이 복원한 SMPL 몸(wham_output.pkl 의 verts, 카메라 좌표)에서 COCO 17관절을 뽑아
(WHAM 의 J_regressor_coco — J_regressor_wham 의 앞 17행과 같다) WHAM 자신의 카메라로 영상에 투영하고,
WHAM 이 입력으로 받은 2D 검출(tracking_results.pth 의 ViTPose keypoints)과의 거리를 잰다.
  카메라: 초점거리 √(W² + H²) · 주점 영상 중앙 — WHAM lib/utils/imutils.py compute_cam_intrinsics 와 같다
  (scripts/overlay_vis.py 도 같은 값).
  오차: 픽셀 거리 ÷ 사람 키(px) = WHAM bbox scale × 200. 신뢰도 < CONF_MIN 인 관절은 뺀다.
  프레임 오차: 그 프레임 몸 관절 12개(어깨 · 팔꿈치 · 손목 · 엉덩이 · 무릎 · 발목) 오차의 중앙값.

**판정은 PASS / CHECK 뿐이다 (FAIL 없음).** CHECK 여도 파이프라인은 멈추지 않는다 — 기록하고 안내한다.
  CHECK  프레임 오차 > FRAME_MAX 가 RUN_MIN 프레임 이상 연속인 구간이 있다
  PASS   그 밖

**한계.**
① WHAM 입력과 같은 2D 검출에 대한 **자기 일관성** 지표다. 2D 로는 맞는데 깊이 방향으로 틀린 자세는 잡지 못한다.
   기록된 두 실패가 그렇다(2026-11-21 실측, 손목 오차 · 그 클립 손목 오차 분포):
     walker_walk_02 f138 — WHAM 의 왼팔이 메쉬보다 바깥으로 벌어졌던 프레임(10/11): 왼손목 0.0106
       (클립 중앙 0.0092 · p95 0.016) — 눈에 띄지 않는다.
     char_shuffle f60 — 왼손 결함 프레임: 왼손목 0.0098 로 합격한 f6(0.0184)보다 오히려 작다.
② CHECK 가 표시하는 것은 **WHAM 이 약한 자세 구간**(눕기 · 엎드리기 · 기기 — RUNBOOK 791 "WHAM 의 누운 · 엎드린
   구간 높이도 흔들려")이다. 결과물의 결함 여부는 G4 바닥 판정이 판정한다. 그래서 불합격에 쓰지 않는다.
얼굴 관절 5개(코 · 눈 · 귀)는 판정에서 뺀다 — 오차는 따로 기록한다. 근거(2026-11-21 미러 88편): 관절 최대 오차가
0.05 를 넘는 프레임에서 그 관절이 얼굴인 비율이 클립 중앙 29%이고(walker_alert f108~113 오른귀 0.048~0.07, 몸 중앙
0.015, 결함 기록 없음), 머리가 낮은 기기 자세에서 크게 부푼다(common_fall_to_crawl 0.05 초과 최장 연속 7 → 얼굴 포함
46). 신뢰도로는 거를 수 없다(얼굴 · 몸 모두 0.5 미만 비율 중앙 0).
"""
import numpy as np

COCO17 = ("nose", "l_eye", "r_eye", "l_ear", "r_ear", "l_shoulder", "r_shoulder", "l_elbow", "r_elbow",
          "l_wrist", "r_wrist", "l_hip", "r_hip", "l_knee", "r_knee", "l_ankle", "r_ankle")
FACE = slice(0, 5)
BODY = slice(5, 17)

# 2D 검출 신뢰도가 이보다 낮은 관절은 오차에서 뺀다 (ViTPose 점수, 0~1).
#   2026-11-21 미러 88편: 0.5 미만 관절 비율 클립 중앙 0 — 지금 영상에서는 거의 걸리지 않는 안전장치다.
CONF_MIN = 0.5

# CHECK 기준 — 몸 관절 프레임 오차(사람 키 대비)가 FRAME_MAX 를 넘는 프레임이 RUN_MIN 프레임 이상 연속.
#   2026-11-21 미러 88편(tracking_results.pth 가 있는 전부) 역검증 — docs/G3_BACKCHECK.md:
#   77편은 0.05 초과 프레임 0. CHECK 7편은 전부 눕기 · 엎드리기 · 기기 클립(walker · stalker fall_front_v2,
#   common_crawl_to_run, stalker_get_up_c — 모두 bake.ground_align)이거나 gate_s5 불합격 이력 클립(listener_fall_front,
#   walker_get_up_c2, common_fall_to_crawl). 서서 하는 납품 클립은 최장 2프레임 연속(oiler_run_fwd_v2 의 순간 튐).
#   비교한 세 안(A: >0.05 연속 ≥5, B: >0.04 연속 ≥10, C: >0.04 연속 ≥5) 모두 서서 하는 납품 클립은 0편이었고,
#   그 클립들과의 여유 폭이 가장 큰 A 를 채택했다(A 최장 2 대 기준 5 · B 는 눕기 클립 9 대 기준 10 · C 는 3 대 5).
#   24fps 에서 5프레임 ≈ 0.2초. **잠정이다 (CHECK 표본 7편, 그중 gate_s5 불합격 3).** 재보정: 서서 하는 클립이 CHECK
#   로 올라올 때 · 새 캐릭터 · 새 생성 모델.
FRAME_MAX = 0.05
RUN_MIN = 5

STATUS = "잠정 (2026-11-21 미러 88편 역검증, CHECK 7편). 재보정: 서서 하는 클립 CHECK · 새 캐릭터 · 새 생성 모델"


def project(verts, regressor, width, height):
    """(T, V, 3) 카메라 좌표 정점 → (T, 17, 2) 픽셀. WHAM 의 카메라(초점거리 √(W²+H²), 주점 중앙)."""
    j3 = np.einsum("jv,tvc->tjc", np.asarray(regressor, np.float64), np.asarray(verts, np.float64))
    z = np.clip(j3[..., 2], 1e-4, None)
    f = (width * width + height * height) ** 0.5
    return np.stack([f * j3[..., 0] / z + width / 2.0, f * j3[..., 1] / z + height / 2.0], -1)


def errors(uv, keypoints, height_px):
    """투영 (T, 17, 2) · 검출 (T, 17, 3: x, y, 신뢰도) · 사람 키 (T,) px → 오차 (T, 17), 사용 마스크 (T, 17)."""
    kp = np.asarray(keypoints, np.float64)
    h = np.asarray(height_px, np.float64)[:, None]
    e = np.linalg.norm(kp[..., :2] - uv, axis=-1) / h
    return e, kp[..., 2] >= CONF_MIN


def frame_median(e, used, part=BODY):
    """프레임별 오차 중앙값 (쓸 관절이 없으면 nan)."""
    e, used = e[:, part], used[:, part]
    return np.array([np.median(r[m]) if m.any() else np.nan for r, m in zip(e, used)])


def spans_over(values, frame_ids, limit, run_min):
    """values > limit 가 run_min 이상 연속인 구간 → [{start, end, frames, max}] (frame_ids 기준, 양끝 포함).
    nan 은 넘지 않은 것으로 본다. 프레임 번호가 건너뛰면 연속이 끊긴 것으로 본다."""
    out, cur = [], []
    ids = [int(f) for f in frame_ids]
    for i, (v, f) in enumerate(zip(values, ids)):
        over = bool(np.isfinite(v) and v > limit)
        if over and cur and f != ids[cur[-1]] + 1:
            if len(cur) >= run_min:
                out.append(cur)
            cur = []
        if over:
            cur.append(i)
        else:
            if len(cur) >= run_min:
                out.append(cur)
            cur = []
    if len(cur) >= run_min:
        out.append(cur)
    return [{"start": ids[c[0]], "end": ids[c[-1]], "frames": len(c),
             "max": round(float(np.nanmax(values[c])), 4)} for c in out]


def longest_run(values, frame_ids, limit):
    """values > limit 의 최장 연속 길이와 시작 프레임 (기록용)."""
    s = spans_over(values, frame_ids, limit, 1)
    if not s:
        return 0, None
    best = max(s, key=lambda x: x["frames"])
    return best["frames"], best["start"]


def summarize(e, used, part):
    v = e[:, part][used[:, part]]
    if v.size == 0:
        return {"median": None, "p95": None, "max": None, "pck05": None, "n": 0}
    return {"median": round(float(np.median(v)), 4), "p95": round(float(np.percentile(v, 95)), 4),
            "max": round(float(v.max()), 4), "pck05": round(float((v < 0.05).mean()), 4), "n": int(v.size)}


def judge(e, used, frame_ids):
    """오차 → (PASS/CHECK, 사유, 기록). 몸 관절만 판정한다. 순수 함수."""
    fm = frame_median(e, used, BODY)
    spans = spans_over(fm, frame_ids, FRAME_MAX, RUN_MIN)
    reasons = [f"f{s['start']}~f{s['end']} ({s['frames']}프레임) 몸 관절 재투영 오차가 키의 {100 * FRAME_MAX:.0f}% 를 넘는다"
               f" — 최대 {100 * s['max']:.1f}%" for s in spans]
    run_len, run_at = longest_run(fm, frame_ids, FRAME_MAX)
    record = {
        "body": summarize(e, used, BODY), "face": summarize(e, used, FACE),
        "frames_over": int(np.nansum(fm > FRAME_MAX)), "longest_run": run_len, "longest_run_start": run_at,
        "frame_median_max": None if np.all(np.isnan(fm)) else round(float(np.nanmax(fm)), 4),
        "check_spans": spans,
        "per_joint_median": {COCO17[j]: (round(float(np.median(e[used[:, j], j])), 4) if used[:, j].any() else None)
                             for j in range(17)},
        "dropped_low_conf": round(float(1 - used.mean()), 4) if used.size else None,
    }
    return ("CHECK" if spans else "PASS"), reasons, record, fm
