# Video2UnityAvatar-Pipeline

[Software Maestro] 좀비 영상 한 편을 입력하면 유니티 아바타 에셋(캐릭터 + 애니메이션)으로 자동 변환하는 파이프라인.

## 파이프라인

```
입력 영상
  → SAM2      (segmentation)      인물 마스킹·트래킹
  ├→ TRELLIS  (mesh generation)   키프레임 1장 → 3D 메쉬 + 텍스처
  └→ WHAM     (motion estimation) 클립 → SMPL 동작 (pose/betas/trans)
  → Blender 처리                  SMPL 직접 리깅 (메쉬 정렬 + 웨이트 전이) → FBX
  → Unity 반입                    Humanoid 아바타 + 애니메이션
```

각 단계 사이에는 품질 게이트(G0~G4)가 있어, 불합격 시 해당 단계로 재진입합니다.

## 설계 변천

| 버전 | 구성 | 변경 사유 |
|---|---|---|
| v1 | SAM2 + SuGaR + Unique3D + WHAM (4모델) | 초기 설계. SuGaR로 배경까지 3D 복원 |
| v2 | SAM2 + TRELLIS + WHAM (3모델) | 최종 목표가 아바타라 배경 3D가 불필요하고, SuGaR는 정적 장면 전제라 움직이는 인물에 부적합해 제외. Unique3D는 라이선스·유지보수 문제로 TRELLIS로 교체 |
| **v3 (현재)** | v2 + SMPL 골격 직접 리깅 | Mixamo 리타게팅이 자세 붕괴로 실패해 폐기. 골격을 SMPL로 통일해 리타게팅 단계 자체를 제거 |

상세 이력과 각 결정의 검증 근거는 [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md)에 있습니다.
폐기한 리타게팅 시도는 [`scripts/deprecated/README.md`](scripts/deprecated/README.md)를 참고하세요.

## 레포 구조

| 경로 | 내용 |
|---|---|
| `docs/` | 프로젝트 문서. 설계·검증 결과·다음 단계는 [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) |
| `notebooks/sam2/` | SAM2 전처리 Colab 시행착오 노트북 (try1~try6) |
| `scripts/` | 검증된 실행 스크립트 (WHAM 실행, pkl→FBX 변환, 텍스처 추출 등) |
| `scripts/deprecated/` | 폐기된 시도 — SMPL→Mixamo 리타게팅 계열 |
| `pipeline/qa/` | 품질 게이트 및 재시도 오케스트레이터 |
| `docker/` | 환경 확정 후 굳힐 Dockerfile |

## 실행 환경

레포별 의존성이 충돌(torch 1.11~2.5, CUDA 11.3~12.4)하여 단일 환경을 쓰지 않고, 모델별로 환경을 분리합니다.
GPU 작업은 RunPod(RTX 4090, EU-RO-1) + Network Volume(`/workspace`)에서 micromamba로 구성합니다.

## 상태

- 검증 완료: WHAM 동작 복원, TRELLIS 외형 복원, 유니티 에셋 반입
- 진행 중: SMPL 골격 직접 리깅 (메쉬 생성 → 정렬 → 웨이트 전이)
- 예정: TRELLIS 로컬 설치, 품질 게이트 연결, 오케스트레이터 가동, Dockerfile 고정
