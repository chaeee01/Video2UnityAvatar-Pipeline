"""--dry-run 은 run 기록을 바꾸지 않는다 — 완료 마커 · 시도 기록 · 메타 모두.

2026-10-13 Pod 에서 `--resume --dry-run` 뒤 done/5-1.done(elapsed 0.0)이 생겨, 이어진 실제
실행이 "마커는 있는데 산출물이 없다" 로 멈췄다. 가짜 볼륨(test_orchestrate_g1a 의 대역)에서
같은 순서를 되밟는다: dry-run → 기록 불변 확인 → 실제 실행이 그 단계를 돈다.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_orchestrate_g1a import CS, PKL, make_vol, orch, start_run


def snapshot(run):
    return {p.relative_to(run.root).as_posix(): p.read_bytes()
            for p in sorted(run.root.rglob("*")) if p.is_file()}


def main():
    if not ((CS / "masks").is_dir() and PKL.exists()):
        print("⚠️  미러에 char_shuffle 마스크·pkl 이 없어 건너뛴다")
        return 0
    ok = True

    def check(label, cond, got=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"   {'✅' if cond else '❌'} {label}{'  → ' + str(got) if got != '' else ''}")

    print("── dry-run 은 run 폴더를 바꾸지 않는다")
    with tempfile.TemporaryDirectory() as tmp:
        vol, _ = make_vol(tmp)
        run, _ = start_run(vol)                       # G0 · S2 · S5 완료
        before = snapshot(run)
        rc, out = orch(vol, "--resume", "--dry-run")
        after = snapshot(run)
        check("종료 코드 0 또는 2(인계)", rc in (0, 2), rc)
        check("dry-run 이 G1a 를 다음 단계로 보여 준다", "[G1a]" in out)
        new = sorted(set(after) - set(before))
        check("새 파일 없음 (완료 마커 · 게이트 · 로그)", not new, new)
        changed = sorted(k for k in before if after.get(k) != before[k])
        check("기존 파일 불변 (attempts.json · run.json)", not changed, changed)
        check("G1a · S3 · 5-1 마커가 생기지 않았다",
              not any(run.is_done(k) for k in ("G1a", "S3", "5-1")),
              [k for k in ("G1a", "S3", "5-1") if run.is_done(k)])

        print("── dry-run 뒤의 실제 실행이 그 단계를 돈다")
        rc, out = orch(vol, "--resume", "--until", "G1a")
        check("종료 코드 0, G1a 완료 마커, '마커는 있는데 산출물이 없다' 아님",
              rc == 0 and run.is_done("G1a") and "산출물이 없다" not in out, out[-300:] if rc else "")

    print("\n" + ("전부 통과" if ok else "실패 있음"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
