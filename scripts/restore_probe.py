#!/usr/bin/env python3
"""복원한 환경이 제 발로 서는지 본다 — import · 버전 · 적재 경로. restore_test_env.sh 가 부른다.

  cd <레포 루트> && micromamba run -n <환경> python restore_probe.py <환경 경로> <레포 경로> <모듈…>

보는 것은 셋이다.
  1. sys.prefix 가 그 환경인가, torch 가 CUDA 를 보는가
  2. 지정한 모듈이 import 되는가 (버전과 파일 위치를 찍는다)
  3. 적재된 모듈 파일 중 **원본(_orig)을 가리키는 것**이나 **환경·레포 밖의 것**이 있는가

3번이 핵심이다. 2026-09-29 에 sam2 아카이브가 다른 경로에서 검증을 통과했는데 실은 복원본이
원본 레포를 참조한 거짓 통과였다. 그래서 원본을 `<이름>_orig` 로 치워 둔 채 이 점검을 돌린다.

2026-10-09 첫 실행에서 이 점검이 세 번 틀렸고, 전부 고쳤다:
  - 레포 모듈(WHAM 의 lib.models)을 못 찾았다 — 스크립트로 실행하면 cwd 가 sys.path 에
    없다. cwd 를 넣는다.
  - 이 파일 자신을 "환경 밖" 으로 셌다.
  - torch 가 실행 중에 만드는 모듈을 "환경 밖" 으로 셌다 — `__file__` 이 `_ops.py` 처럼
    실재하지 않는 상대 경로이거나 임시 폴더(`/tmp/…/_remote_module_non_scriptable.py`)다.
    원본 환경에서도 똑같이 나오므로 복원과 무관하다. 디스크에 없는 경로와 임시 폴더는 뺀다.
"""
import importlib
import os
import sys
import tempfile


def classify(files, env, repo, me):
    """모듈 파일 목록을 (원본 참조, 환경·레포 밖) 으로 가른다. 근거는 위 독스트링."""
    tmp = os.path.realpath(tempfile.gettempdir())
    orig, outside = [], []
    for f in files:
        if f.startswith(env + "_orig" + os.sep) or f.startswith(repo + "_orig" + os.sep):
            orig.append(f)
            continue
        if f.startswith(env + os.sep) or f.startswith(repo + os.sep) or f == me:
            continue
        if not os.path.isabs(f) or not os.path.exists(f):
            continue                      # torch 가 만든 가짜 경로 (_ops.py 등)
        if os.path.realpath(f).startswith(tmp + os.sep):
            continue                      # 실행 중 생성한 임시 모듈
        outside.append(f)
    return orig, outside


def main():
    env, repo, mods = sys.argv[1].rstrip("/"), sys.argv[2].rstrip("/"), sys.argv[3:]
    sys.path.insert(0, os.getcwd())       # 레포 루트
    ok = True
    import torch
    print(f"  python {sys.version.split()[0]}  prefix {sys.prefix}")
    print(f"  torch {torch.__version__}  cuda {torch.cuda.is_available()}")
    ok &= torch.cuda.is_available() and sys.prefix == env
    for m in mods:
        try:
            x = importlib.import_module(m)
            print(f"  {m:18s} {getattr(x, '__version__', '-'):14s} {getattr(x, '__file__', '(builtin)')}")
        except Exception as e:
            ok = False
            print(f"  {m:18s} 실패: {type(e).__name__}: {e}")
    files = [f for f in (getattr(v, "__file__", None) for v in list(sys.modules.values())) if f]
    orig, outside = classify(files, env, repo, os.path.abspath(__file__))
    print(f"  적재된 모듈 파일 {len(files)}개 | 원본(_orig) 참조 {len(orig)} | 환경·레포 밖 {len(outside)}")
    for f in (orig + outside)[:8]:
        print("    !", f)
    ok &= not orig and not outside
    print("  PROBE", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
