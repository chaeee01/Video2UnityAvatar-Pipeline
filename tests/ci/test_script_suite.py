"""기존 스크립트형 시험(tests/test_*.py)을 pytest 로 한 번에 돌리는 러너 — CI 용.

  pytest tests/ci -v -rs

시험 파일은 각자 `python3 tests/test_X.py` 로 돌고 종료 코드로 합격을 알린다. 이 러너는 그 파일을
하나씩 subprocess 로 실행하고(같은 인터프리터 = sys.executable) 종료 코드 0 을 확인할 뿐, 시험 내용은 건드리지 않는다.
tests/ 전체를 pytest 가 수집하게 두지 않는다 — test_s2_prompt · test_track_stitch 에 def test_ 함수가 있어 이중 실행된다.

목록은 2026-11-18 조사(미러를 가린 상태, Python 3.9)에서 정했다:
  RUN  — 끝까지 실행 9 + 부분 실행 4 (미러 없는 절은 시험이 스스로 건너뛰고 0 으로 끝난다)
         + 2026-11-21 test_orch_boundary (끝까지 실행, 가짜 Blender — 미러 · Blender 불필요)
  SKIP — 미러 없이는 아무것도 돌지 않거나(종료 0 이지만 검사 0건), 실물 절 0건을 실패로 세는 시험
tests/test_*.py 가 늘거나 줄면 목록과 어긋나 수집 단계에서 멈춘다 — 새 시험을 조용히 빠뜨리지 않는다.
"""
import subprocess
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
REPO = TESTS.parent

RUN = [
    # 끝까지 실행
    "test_blend_track_seam.py",
    "test_g4_rules.py",
    "test_gate_g2r.py",
    "test_ground_align.py",
    "test_orch_character.py",
    "test_orch_boundary.py",
    "test_orch_motion51.py",
    "test_part_islands.py",
    "test_restore_probe.py",
    "test_s2_prompt.py",
    "test_seam_smooth.py",
    # 부분 실행 (미러 절은 시험이 건너뜀)
    "test_track_stitch.py",
    "test_g1a_terms.py",
    "test_keyframe_gap.py",
    "test_review_tools.py",
]

MIRROR = "미러 필요"
BLENDER = "Blender 필요"
BLENDER_MIRROR = "Blender · 미러 필요"
NO_REAL = "실물 절 0건이라 실패 집계"
SKIP = {
    "test_g1a_reselect.py": MIRROR,
    "test_keyframe_leg.py": MIRROR,
    "test_orchestrate_dryrun.py": MIRROR,
    "test_orchestrate_g1a.py": MIRROR,
    "test_motion_bake.py": BLENDER_MIRROR,
    "test_gate_s2.py": NO_REAL,
    "test_gate_g2.py": NO_REAL,
}

TAIL = 30
TIMEOUT_S = 900

_found = sorted(p.name for p in TESTS.glob("test_*.py"))
_listed = sorted(RUN + list(SKIP))
if _found != _listed:
    raise RuntimeError("tests/ci 목록이 tests/test_*.py 와 다르다 — "
                       f"목록에 없음 {sorted(set(_found) - set(_listed))}, "
                       f"파일 없음 {sorted(set(_listed) - set(_found))}")

CASES = [pytest.param(n, id=n) for n in RUN] + \
        [pytest.param(n, id=n, marks=pytest.mark.skip(reason=r)) for n, r in SKIP.items()]


@pytest.mark.parametrize("name", CASES)
def test_script(name):
    r = subprocess.run([sys.executable, str(TESTS / name)], cwd=REPO,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=TIMEOUT_S)
    if r.returncode != 0:
        tail = "\n".join(r.stdout.splitlines()[-TAIL:])
        pytest.fail(f"{name} 종료 코드 {r.returncode} — 출력 마지막 {TAIL}줄:\n{tail}", pytrace=False)
