# tools/review — 리그 · 메쉬 검증 도구

파이프라인 단계(`scripts/`)가 아니라, 산출물을 **사람이 판정하기 전에 같은 자로 재는** 도구입니다. 2026-10-12~13 검증에 쓴 것을 옮겼습니다. Blender 는 4.5 LTS (`/Applications/Blender4.5.app/Contents/MacOS/Blender`, 아래 `Blender`).

| 파일 | 하는 일 | 실행 |
|---|---|---|
| `bake_character.sh` | 캐릭터 리그에 동작 여러 편을 굽고, 늘어난 엣지 덤프와 원본 대조 영상을 만든다 | `OUTDIR=<폴더> bake_character.sh <리그 샘플> x <클립 id> …` |
| `dump2.py` | 프레임별 늘어난 엣지(rest 의 4배↑, 길이 0.05 · 0.10 초과)와 본 쌍 | `Blender --background --python dump2.py -- <animated.blend> <출력 접두사> <프레임 간격> <0\|1>` |
| `edge_stats.py` | `dump2.py` JSON → 클립별 다리 쪽 · 팔 쪽 · 전체 엣지 요약 (리그 비교표) | `python3 edge_stats.py <접두사>.json …` |
| `legspread.py` | 구운 리그에서 좌우 허벅지 사이 각 · 발목 간격(키 대비) | `Blender --background --python legspread.py -- <기준자세 animated.blend> <클립 animated.blend> …` → 표준출력 `LEG[…]` |
| `dump.py` · `analyze.py` | 겨드랑이 단면(위팔 축 수직 띠) · 정지 상태 위팔–하부몸통 엣지. `analyze.py` 는 `dump.py … 1` 이 낸 npz 를 읽는다 | `Blender --background --python dump.py -- <blend> <접두사> <간격> 1` → `python3 analyze.py <접두사>` |
| `closeup.py` | 본 둘레 확대 캡처 (정면 직교, Workbench) | `Blender --background --python closeup.py -- <blend> <출력 폴더> <프레임:본:폭:이름> …` |
| `render_diag.py` | 같은 카메라 · 조명의 진단 렌더. `--mode lit\|flat`, `--tex` 텍스처 교체, `--rough`, `--angle`, `--scale` | `Blender --background --python render_diag.py -- --glb <glb> --out <png> --mode flat` |
| `tonematch.py` | 텍스처 톤 매칭 사본 (LAB Reinhard). **자동 적용하지 않는다 — 렌더 비교 후 사람이 고른다** | 파일 머리 참조 |
| `fbxchk.py` | FBX 를 다시 읽어 본 · 메쉬 · 클립 프레임 · 이미지(내장 여부) 확인 | `Blender --background --python fbxchk.py -- <fbx> …` → `FBXCHK[…]` |
| `kf_metrics.py` · `pick_apose_key.py` | (Pod, `wham` 환경) 키프레임 후보의 위팔 벌림각 · 선명도 · 테두리 여유 | `micromamba run -n wham python kf_metrics.py <샘플>` |

데이터 루트는 `$PIPELINE_VOL/data` 입니다 (맥북 미러는 `PIPELINE_VOL=$HOME`, Pod 는 기본 `/workspace`).

**레포 안의 이 위치에서 실행하세요.** `kf_metrics.py` · `pick_apose_key.py` · `tonematch.py` 는 레포의 `scripts/`(`select_keyframes` · `silhouette`)를 이 파일 기준 상대 경로(`../../scripts`)로 찾습니다. 로그 폴더 등으로 복사해 돌리면 `ModuleNotFoundError` 가 납니다(2026-10-15 Pod 에서 실제로 겪음).

## 리그 비교표를 다시 만드는 절차

1. 새 리그에 동작을 굽는다 — `bake_character.sh` (리그 폴더에 `rest_pose.json` 필요: `scripts/make_rest_pose.py`).
2. `legspread.py` 를 기준 자세 blend + 클립 blend 들에 돌린다 → `thigh_angle_max`(허벅지 벌림각 최대), `ankle_max`.
3. `edge_stats.py` 를 `OUTDIR/_dump/*.json` 에 돌린다 → 다리 쪽 · 팔 쪽 · 전체.
4. 기준값(2026-10-13, listener): `apose_04` 리그는 다리를 벌리지 않는 7편이 다리 쪽 0~68, 벌리는 6편이 855~1,643. `apose_05` 리그는 7편 0, 6편 78~754 (팔 쪽은 13편 모두 늘었다).

## 한계

- 수치는 **변형만** 봅니다. 외형 품질(얼굴 · 무늬 세부, 색)은 렌더를 눈으로 봐야 합니다 — 수치가 우세했는데 육안이 뒤집은 사례가 둘 있습니다(walker f188 리그, listener 톤 매칭판).
- `kf_metrics.py` 의 위팔 벌림각은 WHAM pose 에서 잰 값이라 화면에서 잰 각도와 다릅니다.
- 시험은 `tests/test_review_tools.py` — `edge_stats` 와 `tonematch` 만 그날 결과 재현으로 묶여 있습니다. Blender 스크립트들은 시험이 없습니다.
