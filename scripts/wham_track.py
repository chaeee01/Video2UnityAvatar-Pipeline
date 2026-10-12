"""WHAM pkl 에서 쓸 트랙 고르기 — 게이트(gate_s5)와 하류 단계들이 같은 규칙을 쓰게 한다.

WHAM 은 사람을 놓쳤다 다시 잡으면 트랙을 새로 만든다. 2026-10-12 까지는 어디서나 "첫 번째
트랙" 을 썼는데, listener_walk_fwd(바지만 잡힌 마스크)에서 트랙이 34 · 54 · 65프레임 셋으로
끊겼고 첫 번째는 그중 가장 짧았다. **가장 긴 트랙**을 고른다. 길이가 같으면 먼저 나온 것.

joblib · numpy 만 쓴다 (판정은 순수 함수라 tests/ 에서 dict 로 시험한다).
"""


def track_lengths(data):
    """{트랙 키: 프레임 수} — pkl 을 joblib 로 읽은 dict 를 받는다."""
    return {k: len(t["frame_ids"]) for k, t in data.items()}


def pick_track(data):
    """가장 긴 트랙의 키. 트랙이 없으면 예외."""
    if not data:
        raise RuntimeError("WHAM 이 사람을 하나도 추적하지 못했다 (트랙 0개)")
    lens = track_lengths(data)
    return max(lens, key=lambda k: lens[k])          # max 는 같은 값이면 먼저 나온 것


def frame_gaps(frame_ids):
    """트랙 안에서 프레임 번호가 건너뛴 횟수."""
    ids = [int(f) for f in frame_ids]
    return sum(1 for a, b in zip(ids, ids[1:]) if b != a + 1)
