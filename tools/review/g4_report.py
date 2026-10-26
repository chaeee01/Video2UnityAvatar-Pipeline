#!/usr/bin/env python3
"""gate_g4.py 가 남긴 g4_<클립>.json 들을 표 하나로 모은다.

  python3 g4_report.py <폴더> [...]          # 마크다운 표 + 판정별 개수
"""
import glob
import json
import os
import sys


def main():
    rows = []
    for d in sys.argv[1:]:
        for p in sorted(glob.glob(os.path.join(d, "**", "g4_*.json"), recursive=True)):
            rows.append(json.load(open(p)))
    if not rows:
        print("g4_*.json 없음")
        return 1
    print("| 클립 | 종합 | 늘어남 (0.10 초과 / 최장) | 발 쓸기 (역할 · 나쁜 발) | 바닥 (시작 / 끝 / 최저) | 사유 |\n|---|---|---|---|---|---|")
    cnt = {}
    for r in rows:
        e, s = r["edges"], r["sweep"]
        g = r.get("ground") or {"verdict": "-", "reasons": []}       # version 1 결과에는 없다
        cnt[r["verdict"]] = cnt.get(r["verdict"], 0) + 1
        why = "; ".join(e["reasons"] + s["reasons"] + g["reasons"])
        gcol = f"{g['verdict']} ({g['first']:+.3f} / {g['last']:+.3f} / {g['sink']:+.3f})" if "first" in g else g["verdict"]
        print(f"| {os.path.basename(os.path.dirname(r['blend']))} → `{r['clip']}` | **{r['verdict']}** | {e['verdict']} ({e['max10']} / {e['longest']}) "
              f"| {s['verdict']} ({r.get('role') or '-'} · {s['worst']}) | {gcol} | {why} |")
    print("\n판정별:", ", ".join(f"{k} {v}" for k, v in sorted(cnt.items())), f"(총 {len(rows)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
