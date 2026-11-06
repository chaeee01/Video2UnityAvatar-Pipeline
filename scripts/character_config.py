"""캐릭터 설정(06_rig/<캐릭터>/character.json) 읽기 — 오케스트레이터 · 5-4b · 동작 트랙 공용.

character.json 은 "채택 리그 포인터 + 판정" 이다(v1). v2 는 두 절을 덧붙인다 (2026-11-06):

  rig_build   채택 리그를 어떻게 만들었는가.
                source_sample  5-1~5-4 를 돈 외형 샘플 (06_rig/<source_sample>/rigged.blend)
                transfer       5-4 transfer_weights.py 추가 인자 (기본값이면 빈 객체)
                seam_smooth    5-4b — 적힌 순서대로 smooth_seams.py 를 한 번씩 돈다.
                               [{"label", "pairs": ["A:B", ...], "rings", "iters", "lam"}, ...]
  bake        동작 트랙 굽기 옵션 (캐릭터 공통).
                fallback_height  T포즈 메쉬가 없는 클립의 평균 신장 (bake_character.sh 의 FALLBACK_H). 없으면 null

클립별 역할 · 수용 기록 · 굽기 옵션(bake.ground_align)은 같은 폴더의 clip_roles.json 이다 — 관심사가 달라 분리한다.
리그를 바꿀 때 이전 판을 character_prev_*.json 으로 복사해 두는 관례는 그대로다 — 만든 방법도 함께 보존된다.

v1 파일은 rig_build · bake 가 없는 것으로 읽는다(5-4b 없음). 값이 틀린 꼴이면 조용히 넘어가지 않고 멈춘다.
"""
import json
from pathlib import Path


class ConfigError(Exception):
    pass


def _check_pass(i, p):
    where = f"seam_smooth[{i}]"
    for k, t in (("label", str), ("pairs", list), ("rings", int), ("iters", int), ("lam", (int, float))):
        if k not in p:
            raise ConfigError(f"{where}: {k} 가 없다")
        if not isinstance(p[k], t) or isinstance(p[k], bool):
            raise ConfigError(f"{where}.{k}: 형식이 틀렸다 ({p[k]!r})")
    if not p["pairs"]:
        raise ConfigError(f"{where}.pairs: 비어 있다")
    for pr in p["pairs"]:
        parts = pr.split(":") if isinstance(pr, str) else []
        if len(parts) != 2 or not all(x.strip() for x in parts):
            raise ConfigError(f"{where}.pairs: 'A:B' 꼴이어야 한다 ({pr!r})")
    if p["rings"] < 1 or p["iters"] < 1:
        raise ConfigError(f"{where}: rings · iters 는 1 이상 ({p['rings']}, {p['iters']})")


def validate(cfg, path="character.json"):
    """형식만 본다. 고쳐서 돌려주지 않는다."""
    if not isinstance(cfg, dict) or "character" not in cfg:
        raise ConfigError(f"{path}: character 가 없다")
    rb = cfg.get("rig_build")
    if rb is not None:
        if not isinstance(rb, dict) or not isinstance(rb.get("source_sample"), str):
            raise ConfigError(f"{path}: rig_build.source_sample 이 없다")
        if not isinstance(rb.get("transfer", {}), dict):
            raise ConfigError(f"{path}: rig_build.transfer 는 객체여야 한다")
        ss = rb.get("seam_smooth", [])
        if not isinstance(ss, list):
            raise ConfigError(f"{path}: rig_build.seam_smooth 는 목록이어야 한다")
        labels = [p.get("label") for p in ss if isinstance(p, dict)]
        if len(set(labels)) != len(labels):
            raise ConfigError(f"{path}: seam_smooth label 이 겹친다 ({labels})")
        for i, p in enumerate(ss):
            if not isinstance(p, dict):
                raise ConfigError(f"{path}: seam_smooth[{i}] 는 객체여야 한다")
            _check_pass(i, p)
    bk = cfg.get("bake")
    if bk is not None:
        fh = bk.get("fallback_height") if isinstance(bk, dict) else "x"
        if fh is not None and (not isinstance(fh, (int, float)) or isinstance(fh, bool) or fh <= 0):
            raise ConfigError(f"{path}: bake.fallback_height 는 양수 또는 null ({fh!r})")
    return cfg


def load(data_root, character):
    p = Path(data_root) / "06_rig" / character / "character.json"
    if not p.exists():
        raise ConfigError(f"캐릭터 설정이 없다: {p}")
    return validate(json.loads(p.read_text()), p), p


def find_by_source_sample(data_root, sample):
    """rig_build.source_sample 이 sample 인 캐릭터 설정. 없으면 (None, None), 둘 이상이면 멈춘다."""
    hits = []
    for p in sorted((Path(data_root) / "06_rig").glob("*/character.json")):
        try:
            cfg = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if (cfg.get("rig_build") or {}).get("source_sample") == sample:
            hits.append((validate(cfg, p), p))
    if len(hits) > 1:
        raise ConfigError(f"source_sample {sample} 를 가리키는 캐릭터가 둘 이상이다: {[str(h[1]) for h in hits]}")
    return hits[0] if hits else (None, None)


def seam_passes(cfg):
    return list(((cfg or {}).get("rig_build") or {}).get("seam_smooth") or [])


def load_roles(data_root, character):
    p = Path(data_root) / "06_rig" / character / "clip_roles.json"
    if not p.exists():
        raise ConfigError(f"역할표가 없다: {p}")
    return json.loads(p.read_text()), p


def resolve_clip(roles, name):
    """납품 이름(키) 또는 source(굽기 폴더 이름)로 클립 항목을 찾는다 — g4_rules.resolve 와 같은 규칙."""
    clips = (roles or {}).get("clips", {})
    if name in clips:
        return name, clips[name]
    for k, v in clips.items():
        if v.get("source") == name:
            return k, v
    return None, None
