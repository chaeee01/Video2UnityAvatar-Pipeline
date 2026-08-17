# deprecated — 리타게팅 시도

SMPL 골격(24본) 동작을 Mixamo 골격(65본) 캐릭터로 옮기기 위해 작성했던 리타게팅 스크립트들입니다.

| 파일 | 방식 |
|---|---|
| `retarget_smpl_to_mixamo.py` | Blender 행렬 계산 — rest 방향 offset 보정 (`offset = src_rest⁻¹ @ tgt_rest`) |
| `retarget_constraint_based.py` | Blender 컨스트레인트 — world space Copy Rotation 후 NLA 베이킹 |

## 폐기 사유

세 가지 방식을 시도했고 모두 자세가 붕괴했습니다.

- **Unity Humanoid 근육(muscle) 변환**: 변환 과정에서 관절 동작이 소실되고 루트 회전만 남았습니다. Unity 에디터에서 직접 시도한 경로라 이 폴더에 스크립트는 없습니다.
- **rest 방향 offset 보정** (`retarget_smpl_to_mixamo.py`): 팔이 엉키는 자세 붕괴가 발생했고, 리그별 rest 방향 offset의 예외 처리에 실패했습니다.
- **컨스트레인트 + 베이킹** (`retarget_constraint_based.py`): 두 리그의 rest가 모두 T포즈라 world space Copy Rotation이 성립한다는 전제로 작성했으나, 마찬가지로 자세가 붕괴했습니다.

## 대체 방향

리타게팅 경로 자체를 폐기하고, **골격을 SMPL로 통일하는 직접 리깅 방식**으로 전환했습니다.
WHAM이 추정한 체형·자세로 SMPL 메쉬를 만들어 TRELLIS 메쉬와 정렬한 뒤 웨이트를 전이하면,
캐릭터가 SMPL 골격을 그대로 갖게 되어 리타게팅 문제 자체가 사라집니다.

자세한 배경과 현재 설계는 [`docs/PROJECT_STATUS.md`](../../docs/PROJECT_STATUS.md)를 참고하세요.

이 폴더의 스크립트는 기록 보존용이며 파이프라인에서 사용하지 않습니다.
