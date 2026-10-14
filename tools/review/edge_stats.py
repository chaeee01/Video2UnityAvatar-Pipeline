#!/usr/bin/env python3
"""dump2.py 가 낸 JSON 에서 클립별 늘어난 엣지 요약을 뽑는다 — 리그끼리 같은 자로 비교하기 위한 표.

  python3 edge_stats.py <dump 접두사>.json [...]            # 표
  python3 edge_stats.py --json <...>                        # JSON

세는 것은 dump2.py 의 'long' (rest 길이의 4배를 넘고 길이 0.05 를 넘는 엣지, 키 = 1 단위):
  leg    양쪽 본이 모두 다리 · 골반(Hip · Knee · Ankle · Foot · Pelvis)인 엣지 수의 **프레임별 최대**
  arm    한쪽이라도 팔(Shoulder · Elbow · Wrist · Hand · Collar)인 엣지 수의 프레임별 최대
  total  0.05 초과 엣지 수의 프레임별 최대 (그 프레임 = total_f)
  over10 0.10 초과 엣지 수의 프레임별 최대,  longest 최장 엣지

'프레임별 최대' 인 이유: 다리 쪽이 가장 늘어나는 프레임과 전체가 가장 늘어나는 프레임이 다르다
(2026-10-13 listener: run_02 는 전체 최악 프레임에서 962, 다리 최악 프레임에서 984).
"""
import argparse
import json
import sys

LEG = ("Hip", "Knee", "Ankle", "Foot", "Pelvis")
ARM = ("Shoulder", "Elbow", "Wrist", "Hand", "Collar")


def summarize(long):
    """long: {프레임: [0.05 초과 수, 0.10 초과 수, 최장, {본쌍: 수}?]} → 요약 dict."""
    leg = arm = total = 0
    leg_f = None
    for f, v in long.items():
        pairs = v[3] if len(v) > 3 else {}
        n_leg = sum(n for k, n in pairs.items() if all(b.endswith(LEG) for b in k.split("|")))
        n_arm = sum(n for k, n in pairs.items() if any(b.endswith(ARM) for b in k.split("|")))
        if n_leg > leg:
            leg, leg_f = n_leg, f
        arm = max(arm, n_arm)
        total = max(total, v[0])
    total_f = max(long, key=lambda f: long[f][0])
    worst = long[total_f]
    top = sorted((worst[3] if len(worst) > 3 else {}).items(), key=lambda x: -x[1])[:5]
    return dict(total=total, total_f=total_f, leg=leg, leg_f=leg_f, arm=arm,
                over10=max(v[1] for v in long.values()),
                longest=round(max(v[2] for v in long.values()), 3), top=top)


def main():
    ap = argparse.ArgumentParser(description="dump2.py JSON → 클립별 늘어난 엣지 요약")
    ap.add_argument("dumps", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = {p: summarize(json.load(open(p))["long"]) for p in a.dumps}
    if a.json:
        json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
        return 0
    print("| 덤프 | 다리 | 팔 | 전체 >0.05 (프레임) | >0.10 | 최장 | 최악 프레임 상위 본 쌍 |\n|---|---|---|---|---|---|---|")
    for p, s in out.items():
        print(f"| {p} | {s['leg']} | {s['arm']} | {s['total']} (f{s['total_f']}) | {s['over10']} | {s['longest']} | "
              + ", ".join(f"{k} {n}" for k, n in s["top"][:3]) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
