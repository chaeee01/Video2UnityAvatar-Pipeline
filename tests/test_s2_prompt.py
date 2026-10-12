"""S2 다중 점 프롬프트 · 부위 분포 판정 · S5 트랙 연속성 (2026-10-12).

  A. 실루엣 (silhouette.py) — 합성 그림. 점이 몸 위에 찍히는가, 다리 사이 빈 곳을 피하는가,
     배경이 단색이 아니면 멈추는가.
  B. 부위 분포 — "바지만" 마스크를 gate_s2.judge 가 막는가. 기록된 실측값으로도 본다.
  C. 트랙 — 가장 긴 트랙을 고르는가, 끊긴 pkl 을 gate_s5.judge 가 막는가.
  D. 오케스트레이터 — 재시도가 프롬프트 종류를 auto6 → auto10 → box 로 바꾸는가.

SAM2 · WHAM 은 돌리지 않는다. 실제 영상으로 하는 수용 시험(listener 전신 · walker 마스크
동일성)은 Pod 에서 따로 한다 — PROJECT_STATUS 기록 참조.
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import gate_s2
import gate_s5
import orchestrate
import silhouette
import wham_track

OK = []


def check(name, cond, detail=""):
    OK.append(bool(cond))
    print(f"{'✅' if cond else '❌'} {name}" + (f" — {detail}" if detail else ""))


def scene(legs_apart=True, bg_noise=False):
    """회색 배경(위아래 · 좌우로 밝기가 기운다) + 사람 모양. (그림, 몸 마스크, 바지 마스크)"""
    h, w = 960, 540
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    g = 120 + 20 * yy / h + 12 * xx / w
    img = np.stack([g, g, g], axis=2)
    if bg_noise:
        rng = np.random.default_rng(0)
        img += rng.integers(-60, 60, size=(h // 8 + 1, w // 8 + 1, 3)).repeat(8, 0).repeat(8, 1)[:h, :w]
    body = np.zeros((h, w), bool)
    pants = np.zeros((h, w), bool)
    cv2_img = np.clip(img, 0, 255).astype(np.uint8)
    cv2.circle(cv2_img, (270, 120), 45, (150, 170, 215), -1)            # 머리
    cv2.rectangle(cv2_img, (200, 170), (340, 480), (40, 40, 110), -1)   # 겉옷 (붉은색)
    if legs_apart:
        cv2.rectangle(cv2_img, (200, 480), (255, 880), (60, 50, 50), -1)    # 왼다리
        cv2.rectangle(cv2_img, (285, 480), (340, 880), (60, 50, 50), -1)    # 오른다리
    else:
        cv2.rectangle(cv2_img, (215, 480), (325, 880), (60, 50, 50), -1)
    ref = np.clip(img, 0, 255).astype(np.uint8)
    body = np.abs(cv2_img.astype(int) - ref.astype(int)).sum(2) > 0
    pants[480:881] = body[480:881]
    return cv2_img, body, pants


def test_silhouette():
    img, body, pants = scene()
    fg = silhouette.foreground(img)
    inter = (fg & body).sum() / body.sum()
    check("A1 실루엣이 몸을 덮는다", inter > 0.9 and (fg & ~body).mean() < 0.02, f"회수 {inter:.2f}")
    for n in (6, 10):
        pts = silhouette.prompt_points(fg, n)
        on = [bool(body[y, x]) for x, y in pts]
        check(f"A2 점 {n}개가 모두 몸 위에 있다", len(pts) == n and all(on), str(pts))
    # 다리 사이 빈 곳(x 256~284)에 찍히지 않아야 한다 — 무게중심이면 x=270 에 떨어진다
    low = [p for p in silhouette.prompt_points(fg, 6) if p[1] > 500]
    check("A3 다리 줄의 점이 다리 사이 빈 곳을 피한다", low and all(not (256 <= x <= 284) for x, _ in low), str(low))
    try:
        silhouette.foreground(scene(bg_noise=True)[0])
        check("A4 배경이 단색이 아니면 멈춘다", False, "예외가 나지 않았다")
    except silhouette.SilhouetteError as e:
        check("A4 배경이 단색이 아니면 멈춘다", True, str(e))
    blank = scene()[0].copy()
    blank[:] = 128
    try:
        silhouette.foreground(blank)
        check("A5 전경이 없으면 멈춘다", False)
    except silhouette.SilhouetteError as e:
        check("A5 전경이 없으면 멈춘다", True, str(e))


def test_parts():
    img, body, pants = scene()
    fg = silhouette.foreground(img)
    full = silhouette.part_distribution(fg, body)
    part = silhouette.part_distribution(fg, pants)
    check("B1 전신 마스크는 위·아래를 다 덮는다", full["upper"] > 0.9 and full["lower"] > 0.9 and full["height_ratio"] > 0.95, str(full))
    check("B2 바지만 마스크는 위가 비고 높이가 낮다", part["upper"] < 0.05 and part["height_ratio"] < 0.6, str(part))
    base = dict(coverage_mean=11.743, empty_frames=0, parts_mean=1.323)
    # 2026-10-12 실측 — listener_walk_fwd. 커버리지 · 조각 수만으로는 통과했던 마스크다.
    v0, _, w0 = gate_s2.judge(dict(base))
    check("B3 (회귀) 실루엣 없이는 바지만 마스크가 통과하고 주의가 남는다", v0 == "PASS" and any("부위 분포" in x for x in w0))
    v1, r1, _ = gate_s2.judge(dict(base, parts=dict(upper=0.018, lower=0.496, height_ratio=0.531)))
    check("B4 listener 바지만(실측) → FAIL", v1 == "FAIL" and len(r1) == 2, "; ".join(r1))
    for name, p in [("listener 전신 6점", dict(upper=0.991, lower=0.901, height_ratio=1.004)),
                    ("walker_idle", dict(upper=0.964, lower=0.941, height_ratio=0.997)),
                    ("walker_roar_02", dict(upper=0.963, lower=0.929, height_ratio=0.997))]:
        v, r, _ = gate_s2.judge(dict(coverage_mean=26.0, empty_frames=0, parts_mean=1.0, parts=p))
        check(f"B5 {name}(실측) → PASS", v == "PASS", "; ".join(r))
    v2, r2, _ = gate_s2.judge(dict(coverage_mean=20.0, empty_frames=0, parts_mean=1.0,
                                   parts=dict(upper=0.95, lower=0.10, height_ratio=0.55)))
    check("B6 상체만 → FAIL", v2 == "FAIL")


def track(a, b):
    return {"frame_ids": np.arange(a, b), "pose": np.zeros((b - a, 72))}


def test_tracks():
    broken = {0: track(3, 37), 3: track(48, 102), 4: track(106, 171)}      # listener 실측: 34 · 54 · 65
    check("C1 가장 긴 트랙을 고른다 (첫 번째가 아니라)", wham_track.pick_track(broken) == 4)
    check("C2 길이가 같으면 먼저 나온 것", wham_track.pick_track({7: track(0, 10), 2: track(0, 10)}) == 7)
    lens = wham_track.track_lengths(broken)
    v, r, w = gate_s5.judge(lens, 4, 0, 192)
    check("C3 끊긴 pkl(실측) → FAIL, 트랙 여러 개는 주의", v == "FAIL" and "33.9%" in r[0] and w, r[0])
    v, r, w = gate_s5.judge({0: 192}, 0, 0, 192)
    check("C4 192/192 한 트랙 → PASS, 주의 없음", v == "PASS" and not w)
    v, _, _ = gate_s5.judge({0: 184}, 0, 0, 192)
    check("C5 184/192 (95.8%) → PASS", v == "PASS")
    v, _, _ = gate_s5.judge({0: 180}, 0, 0, 192)
    check("C6 180/192 (93.8%) → FAIL", v == "FAIL")
    gaps = wham_track.frame_gaps([0, 1, 2, 5, 6, 9])
    v, r, _ = gate_s5.judge({0: 190}, 0, gaps, 192)
    check("C7 트랙 안에서 프레임이 건너뛰면 FAIL", gaps == 2 and v == "FAIL", "; ".join(r))
    try:
        wham_track.pick_track({})
        check("C8 트랙 0개는 예외", False)
    except RuntimeError:
        check("C8 트랙 0개는 예외", True)


def test_orchestrate():
    c = {}
    seq = [orchestrate.s2_prompt(n, c)[0] for n in (1, 2, 3)]
    check("D1 재시도 순서 auto6 → auto10 → box", seq == ["auto6", "auto10", "box"], str(seq))
    c = {"user_point": "540,250;380,520"}
    seq = [orchestrate.s2_prompt(n, c)[0] for n in (1, 2, 3)]
    check("D2 사용자 좌표는 1차에만 쓴다", seq == ["point", "auto10", "box"], str(seq))
    c = {"name": "x", "video": "/v.mp4", "s2_prompt": "point", "point": "1,2;3,4"}
    cmd = orchestrate.stage_command("S2", c)
    check("D3 point 프롬프트는 --point 를 넘긴다", cmd[-4:] == ["--prompt", "point", "--point", "1,2;3,4"], str(cmd[-4:]))
    c = {"name": "x", "video": "/v.mp4", "s2_prompt": "auto10", "point": None}
    cmd = orchestrate.stage_command("S2", c)
    check("D4 auto 프롬프트는 --point 를 넘기지 않는다", cmd[-2:] == ["--prompt", "auto10"] and "--point" not in cmd, str(cmd[-2:]))
    import tempfile
    from pathlib import Path
    from types import SimpleNamespace
    with tempfile.TemporaryDirectory() as tmp:
        logs = Path(tmp)
        run = SimpleNamespace(logs=logs)
        check("D6 처음 도는 단계는 try1 부터", orchestrate.prior_tries(run, "5-4") == 0)
        for f in ("5-4_try1.log", "5-4_try1_gate.log", "S2_try1.log", "S2_try2.log", "S2_try3.log", "5-5_try1.log"):
            (logs / f).write_text("")
        check("D7 이어받기는 번호를 잇는다 (5-4 → try2, S2 → try4, 게이트 로그는 세지 않는다)",
              (orchestrate.prior_tries(run, "5-4"), orchestrate.prior_tries(run, "S2")) == (1, 3),
              str((orchestrate.prior_tries(run, "5-4"), orchestrate.prior_tries(run, "S2"))))
    s5 = next(s for s in orchestrate.STAGES if s["key"] == "S5")
    check("D5 S5 에 게이트가 붙었다", s5["gate"] == "gate_s5")


if __name__ == "__main__":
    test_silhouette()
    test_parts()
    test_tracks()
    test_orchestrate()
    print(f"\n{'✅ 전체 통과' if all(OK) else '❌ 실패 있음'} ({sum(OK)}/{len(OK)})")
    sys.exit(0 if all(OK) else 1)
