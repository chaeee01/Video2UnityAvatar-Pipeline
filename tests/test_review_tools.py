"""검증 도구(tools/review) 시험 — 2026-10-13 의 결과를 그대로 다시 낸다.

  A. edge_stats.summarize — listener_apose_04 리그 13편의 다리 쪽 엣지 수가 검수시트 표
     (벌리지 않는 7편 0~68, 벌리는 6편 855~1,643)와 같다. 입력은 그날 dump2.py 가 낸
     'long' (tests/fixtures/review_long_listener_apose_04.json).
  B. tonematch.match — listener · walker apose_04 텍스처로 다시 만든 톤 매칭판이 그날 손으로
     만든 사본과 전 픽셀 같다. 미러(~/data)에 텍스처 · 정면 렌더 · 레퍼런스가 있어야 돈다.
  C. 도구들이 세션 임시 폴더나 특정 사용자 경로를 가리키지 않는다.
"""
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools" / "review"
sys.path.insert(0, str(TOOLS))
H = Path(os.path.expanduser("~/data"))

# 검수시트(2026-10-13) "listener — 다리를 크게 벌리지 않는 클립" 표의 다리 쪽 늘어난 엣지
LEG_EXPECT = {"idle_03": 0, "walk_02": 0, "roar_02": 0, "idle": 0, "idle_02": 0, "walk_fwd_mp": 10,
              "walk_03": 68, "roar_03": 1554, "roar": 1643, "run_03": 858, "attack": 855,
              "run_fwd": 1494, "run_02": 984}
# 같은 날 구 리그(apose_04) 대 신 리그(apose_05) 비교표의 구 리그 열
TOTAL_EXPECT = {"idle": 861, "roar": 2890, "attack": 2475, "run_02": 1806}
ARM_EXPECT = {"idle": 861, "attack": 1050, "run_fwd": 649}


def main():
    ok = True

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")

    print("── A. edge_stats: 10/13 표 재현")
    import edge_stats
    long = json.load(open(REPO / "tests" / "fixtures" / "review_long_listener_apose_04.json"))["long"]
    S = {c: edge_stats.summarize(d) for c, d in long.items()}
    got = {c: S[c]["leg"] for c in LEG_EXPECT}
    check("다리 쪽 엣지 13편", got == LEG_EXPECT, {c: (got[c], LEG_EXPECT[c]) for c in got if got[c] != LEG_EXPECT[c]})
    check("벌리지 않는 7편 0~68 · 벌리는 6편 855~1,643",
          sorted(got.values())[:7] == [0, 0, 0, 0, 0, 10, 68] and min(sorted(got.values())[7:]) == 855
          and max(got.values()) == 1643, sorted(got.values()))
    check("전체 0.05 초과 (4편)", all(S[c]["total"] == v for c, v in TOTAL_EXPECT.items()),
          {c: S[c]["total"] for c in TOTAL_EXPECT})
    check("팔 관련 (3편)", all(S[c]["arm"] == v for c, v in ARM_EXPECT.items()), {c: S[c]["arm"] for c in ARM_EXPECT})
    check("run_02: 다리 최악 프레임과 전체 최악 프레임이 다르다 (프레임별 최대를 쓰는 이유)",
          S["run_02"]["leg_f"] != S["run_02"]["total_f"], (S["run_02"]["leg_f"], S["run_02"]["total_f"]))
    check("쌍 정보가 없는 프레임만 있어도 죽지 않는다",
          edge_stats.summarize({"1": [0, 0, 0.0]}) == dict(total=0, total_f="1", leg=0, leg_f=None, arm=0,
                                                         over10=0, longest=0.0, top=[]))

    print("── B. tonematch: 10/13 손 결과와 전 픽셀 동일")
    import cv2
    import tonematch
    ran = 0
    for ch in ("listener", "walker"):
        d = H / "03_trellis2" / f"{ch}_apose_04"
        tex = d / "textures" / f"{ch}_apose_04_tex_0.png"
        want = d / "textures" / f"{ch}_apose_04_tex_0_tonematch_20261013.png"
        flat = d / "diag" / f"{ch}_apose_04_flat_20261013.png"
        ref = H / "00_raw" / "_refs_clean" / f"manor_{ch}_01_v4_1116_clean.png"
        miss = [p.name for p in (tex, want, flat, ref) if not p.exists()]
        if miss:
            print(f"   ⚠️  {ch}: 미러에 없어 건너뛴다 — {miss}")
            continue
        out = tonematch.match(cv2.imread(str(tex), cv2.IMREAD_UNCHANGED), cv2.imread(str(flat)), cv2.imread(str(ref)))
        w = cv2.imread(str(want), cv2.IMREAD_UNCHANGED)
        check(f"{ch}: {out.shape} 전 픽셀 동일", out.shape == w.shape and (out == w).all(),
              "" if out.shape == w.shape and (out == w).all() else "다름")
        ran += 1
    if not ran:
        print("   ⚠️  B 는 한 건도 돌지 못했다 (미러 없음) — 통과로 세지 않는다")

    print("── C. 경로")
    bad = {}
    for f in sorted(TOOLS.iterdir()):
        if f.suffix not in (".py", ".sh"):
            continue
        hits = [w for w in ("scratchpad", "/private/tmp", "/Users/", "Pipeline.wt", "e2e_check") if w in f.read_text()]
        if hits:
            bad[f.name] = hits
    check("세션 임시 폴더 · 사용자 경로 없음", not bad, bad)
    names = {f.name for f in TOOLS.iterdir()}
    check("bakechar4.sh 는 들어 있지 않다, dump.py 는 analyze.py 와 함께 있다",
          "bakechar4.sh" not in names and {"dump.py", "analyze.py"} <= names, sorted(names))

    print("\n" + ("✅ 전체 통과" if ok else "❌ 실패 있음") + (f" (B {ran}/2 건 실행)" ))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
