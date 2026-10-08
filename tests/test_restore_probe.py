"""복원 점검(restore_probe.py)의 경로 분류 시험.

2026-10-09 복원 시험에서 이 점검이 세 번 틀렸다 (wham FAIL · trellis2 FAIL 로 찍혔으나
둘 다 복원은 멀쩡했다). 그때 실제로 나온 경로를 그대로 시험지로 쓴다.
torch 없이 돈다 — 분류 함수만 본다.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from restore_probe import classify

ENV, REPO = "/workspace/micromamba/envs/trellis2", "/workspace/repos/TRELLIS.2"
ME = "/workspace/repos/Video2UnityAvatar-Pipeline/scripts/restore_probe.py"


def main():
    ok = True

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")

    inside = [f"{ENV}/lib/python3.10/site-packages/torch/__init__.py",
              f"{REPO}/trellis2/__init__.py"]
    check("환경·레포 안의 파일은 통과", classify(inside, ENV, REPO, ME) == ([], []))
    check("점검 스크립트 자신은 세지 않는다 (10/9 wham 오탐)", classify([ME], ENV, REPO, ME) == ([], []))
    # 10/9 trellis2 오탐 3건: torch 가 실행 중에 만드는 모듈
    with tempfile.TemporaryDirectory() as tmp:
        gen = os.path.join(tmp, "_remote_module_non_scriptable.py")
        open(gen, "w").close()
        got = classify(["_ops.py", "_classes.py", gen], ENV, REPO, ME)
        check("torch 생성 모듈(_ops.py · _classes.py · 임시 폴더)은 세지 않는다", got == ([], []), got)
    # 진짜 문제는 잡아야 한다
    o = [f"{ENV}_orig/lib/python3.10/site-packages/numpy/__init__.py", f"{REPO}_orig/trellis2/x.py"]
    got = classify(o, ENV, REPO, ME)
    check("원본(_orig) 참조는 잡는다 — sam2 거짓 통과의 경우", got == (o, []), got)
    real = os.path.abspath(__file__)           # 디스크에 실재하고 환경·레포·임시 폴더 밖
    got = classify([real], ENV, REPO, ME)
    check("환경·레포 밖의 실재하는 파일은 잡는다", got == ([], [real]), got)
    # 이름이 비슷한 다른 환경을 원본으로 오인하지 않는다
    other = "/workspace/micromamba/envs/trellis2_original_backup/x.py"
    check("'_orig' 로 시작하는 다른 이름은 원본 참조가 아니다 (경로 구분자까지 본다)",
          classify([other], ENV, REPO, ME)[0] == [])

    print("\n✅ 전체 통과" if ok else "\n❌ 실패")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
