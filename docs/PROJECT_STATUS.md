# 좀비 영상 → 유니티 아바타 파이프라인 — 진행 상황 정리

작성일: 2026-08-11 (최종 갱신: 2026-08-20)
레포: [Video2UnityAvatar-Pipeline](https://github.com/chaeee01/Video2UnityAvatar-Pipeline) — 초기 이름 `3DGS-Character-Generation-Pipeline`에서 개명. SuGaR(3DGS) 기반 복원을 설계에서 제외하면서 이름이 실제 구성과 어긋나 정리함.
목표: 좀비 영상 한 편을 입력하면 SAM2로 객체를 분리하고, TRELLIS로 외형을, WHAM으로 동작을 복원한 뒤 유니티 에셋(아바타 + 애니메이션)으로 반입하는 파이프라인 구축.

---

## 1. 최종 파이프라인 설계

기획(v1) 이후 세 차례 개정을 거쳐 확정된 v4 구조. 버전별 구조도는 [`assets/`](assets/)에 있다 ([v1](assets/pipeline_v1.png) · [v2](assets/pipeline_v2.png) · [v3](assets/pipeline_v3.png) · [v4](assets/pipeline_v4.png)).

```
입력 영상
  → G0 입력 검증
  → S0 전처리 (fps/해상도 정규화)
  → S1 PySceneDetect (컷 분할)
  → S2 SAM2 (마스킹·트래킹)
      ├→ G1a 외형용 프레임 평가 → S3 TRELLIS → G2 메쉬 평가 → S4 SMPL 골격 직접 리깅
      └→ G1m 동작용 클립 평가 → S5 WHAM → G3 동작 평가 → S6 좌표변환
                                          └─ betas 전달 ─→ S4
  → S7 동작 결합(리타게팅 없음) → G4 최종 통합 평가 → (불합격 시 게이트별 재진입)
```

### 버전별 설계 변경 이력

| 버전 | 핵심 구성 | 전환 사유 |
|---|---|---|
| v1 (기획, 미실행) | SAM2 + SuGaR + WHAM, 가우시안 LOD 렌더링 | 조사 단계에서 SuGaR의 동적 인물 부적합 확인(정적 장면 전제), 최종 목표가 아바타라 배경 3D 불필요 → 착수 전 배제 |
| v2 | Mixamo 자동 리깅 + Unity Humanoid 리타게팅 | 실행 결과 근육 변환에서 관절 동작 소실, 루트 회전만 잔존 → 폐기 (3절) |
| v3 | 품질 게이트(G0~G4)·재시도 오케스트레이터 추가 | 평가·재시도 체계 확립. 리깅 방식은 v2 유지 |
| v4 (현재) | SMPL 골격 직접 리깅, betas 전달로 골격 통일 | 리타게팅 단계의 구조적 제거 (4절) |

각 버전에 공통으로 적용된 결정:
- Unique3D/SF3D → TRELLIS 교체 — MIT 라이선스(상업 이용 가능), 단일/다중 뷰 지원, 유지보수 활발. Hunyuan3D는 한국 지역 사용 제한으로 배제.
- 외형용(G1a)과 동작용(G1m) 평가 분리(v3~) — 두 모델이 요구하는 입력 조건이 다르기 때문(외형: 선명한 1프레임 / 동작: 가림 없는 시퀀스).

---

## 2. 인프라 (완료)

| 항목 | 내용 |
|---|---|
| GPU | RunPod 초당 과금. RTX 4090 ($0.69/hr, EU-RO-1) 사용 중 |
| 스토리지 | Network Volume 100GB, EU-RO-1 고정. Pod 간 데이터 공유 통로 |
| 환경 구성 | 도커 이미지 대신 볼륨(`/workspace`)에 micromamba로 직접 설치. Pod을 지워도 환경이 유지되어 디버깅 사이클이 짧음. 명령이 확정되면 Dockerfile로 굳힐 예정 |
| 접속 | SSH(Direct TCP) + VSCode Remote-SSH. Pod 재배포 시 IP/포트 변경됨 |
| 검증 완료 | 볼륨 영속성 테스트 통과 (Pod terminate 후 재배포해도 데이터 유지) |

운영 규칙: Pod은 작업 후 반드시 Terminate(Stop은 스토리지 2배 과금). 모든 Pod은 EU-RO-1에서 배포. 결과 파일은 terminate 전에 맥북으로 회수.

레포별 의존성이 충돌(torch 1.11~2.5, CUDA 11.3~12.4)하여 단일 환경 불가 → 환경 분리 원칙 확정. 현재 볼륨에 wham 환경(python 3.9 + torch 2.0.0+cu118) 구축 완료.

---

## 3. 단계별 검증 결과

### 동작 복원 (WHAM) — 검증 완료
- SMPL/SMPLify 계정 인증 완료. 체크포인트·바디모델 다운로드 완료 (`/workspace/repos/WHAM`).
- `zombie_sample1.mp4`(69프레임, 2.3초)로 실행 → `wham_output.pkl` 생성.
  - pose (69,72), trans (69,3), betas (69,10), verts (69,6890,3)
  - 트랙 1개(단독 추적 성공), 포즈 표준편차 0.44(동작 확실히 포착)
- 검증: SMPL 공식 J_regressor로 관절 추출 → 원본 영상에 2D 재투영 → 좀비 위에 정확히 정합. 재투영 오차가 작음을 육안 확인.
- DPVO 미설치, `--estimate_local_only` 모드(카메라 고정 전제). 카메라 이동 영상이 필요해지면 추가.

### 외형 복원 (TRELLIS) — 검증 완료
- HF Space(무료)에서 좀비 키프레임 1장 → GLB 생성. 뒷면 품질 양호, 얼굴 디테일은 아쉬우나 좀비 컨셉상 허용 범위.
- GLB → Blender → FBX 변환 → Mixamo 자동 리깅 성공(관절 마커 수동 배치).
- Unity Humanoid 매핑 통과(필수 본 15개 전부 매핑).
- 텍스처: FBX 변환 시 누락되는 문제를 GLB 바이너리에서 직접 추출(PNG 2048×2048)하여 해결. Unity Material(URP Base Map)에 연결 완료.

### 유니티 에셋 반입 — 검증 완료
- Mixamo 캐릭터(With Skin) + Mixamo 애니메이션(Without Skin) 구조로 반입.
- 텍스처 입힌 좀비가 Mixamo 좀비 애니메이션으로 정상 동작 확인.
- "외형 + 리깅 + 텍스처 + 동작"이 유니티에서 결합되는 전체 절차 검증 완료.

### WHAM 동작의 유니티 반입 — 미해결 (유일한 미완 구간)
- pkl → FBX 변환 자체는 성공: Blender bpy 스크립트로 SMPL Unity FBX 템플릿에 동작을 구움. Blender에서 팔다리 동작 정상 재생 확인.
- 실패 지점: SMPL 골격(24본) 동작을 Mixamo 골격(65본) 캐릭터로 옮기는 리타게팅. 세 가지 방식을 시도해 모두 실패.

  | 방식 | 구현 | 결과 |
  |---|---|---|
  | Unity Humanoid 리타게팅 | Unity 에디터에서 직접 시도 (스크립트 없음) | 근육(muscle) 변환 과정에서 관절 동작 소실, 루트 회전만 잔존 |
  | Blender 행렬 계산 | `retarget_smpl_to_mixamo.py` — rest 방향 offset 보정 (`offset = src_rest⁻¹ @ tgt_rest`) | 자세 붕괴(팔 엉킴). 리그별 rest 방향 예외 처리 실패 |
  | Blender 컨스트레인트 | `retarget_constraint_based.py` — world space Copy Rotation 후 NLA 베이킹 | 두 리그의 rest가 모두 T포즈라 world space 회전 복사가 성립한다는 전제였으나 마찬가지로 자세 붕괴 |

  스크립트는 `scripts/deprecated/`에 사유와 함께 보존 ([README](../scripts/deprecated/README.md)).
- 결정: 리타게팅 경로 폐기. Mixamo 리깅은 최종 파이프라인에 들어가지 않으므로 이 다리를 고치는 데 추가 투자하지 않음 (→ 4절 v4 전환).

---

## 4. v4로의 전환: SMPL 골격 직접 리깅

v2/v3의 리타게팅 실패가 역설적으로 방향을 확정함 — 골격을 SMPL로 통일하면 리타게팅 문제 자체가 소멸.
v3까지는 외형 경로(Mixamo 65본)와 동작 경로(SMPL 24본)의 골격이 달라 S7에서 반드시 리타게팅을 거쳐야 했다.
v4는 동작 경로의 betas(체형)를 외형 경로의 리깅 단계(S4)로 전달해 양쪽 골격을 SMPL로 통일하고, S7을 리타게팅이 아닌 단순 동작 결합으로 바꾼다.

```
WHAM betas(체형) + 키프레임 pose(자세) → 그 좀비와 같은 자세·체형의 SMPL 메쉬 생성
  → TRELLIS 메쉬와 정렬 (같은 자세이므로 정렬 난이도 대폭 하락 — 핵심 아이디어)
  → 웨이트 전이 (Blender Data Transfer, Nearest Face Interpolated)
  → SMPL 골격을 가진 좀비 → WHAM 동작 무변환 재생 → Unity Humanoid 반입
```

구조도: [pipeline_v4.png](assets/pipeline_v4.png) — G3에서 S4로 향하는 `betas 전달` 경로가 v3 대비 유일한 신규 연결이며, 이 한 줄이 리타게팅 단계를 제거한다.

기대 효과: Mixamo(수동, API 없음) 제거로 완전 자동화 가능. UniRig(스키닝 모델 미공개) 의존 불필요.

예상 난관: TRELLIS 형상과 SMPL pose 재현 간 미세 불일치, 팔-몸통 근접부 웨이트 번짐(→ G1a에서 팔 벌린 키프레임 선정이 중요), SMPL 몸체 밖 요소(너덜거리는 옷)의 웨이트 처리.

---

## 5. 입력 영상 조건 (확정)

클립 전체(WHAM): 90프레임(3초) 이상·600프레임 이하, 30fps, 720p+, 인물 1명, 컷 전환 없음, bbox 높이 256px+, 가림 30% 미만, 발끝까지 프레임 안, 카메라 고정.

키프레임(TRELLIS): 클립 내 1장 이상 — 전신, 모션블러 없음, 팔이 몸통에서 떨어진 자세, 정면~3/4 측면.

충돌 해소: "팔을 벌린 채 걷는 좀비"가 양쪽 조건을 동시에 만족. 방위각 45° 이상 차이 나는 양질 프레임 2장 이상이면 다중 뷰 경로.

※ 현재 테스트 영상(69프레임)은 기준 미달. 실제 제작 시 5~10초 클립 필요.

---

## 6. 자산 목록

### 스크립트 (작성 완료)

작성된 스크립트는 모두 **레포 `scripts/`에 통합됨** (폐기분은 `scripts/deprecated/`). 볼륨·맥북에 흩어져 있던 사본을 회수해 단일 출처로 정리했다.

| 파일 | 용도 | 상태 |
|---|---|---|
| setup_wham.sh / run_wham.sh | WHAM 볼륨 설치·실행 | 검증됨 |
| overlay_vis.py | SMPL 2D 재투영 검증 | 검증됨 |
| quick_vis.py | SMPL 스켈레톤 프리뷰 (matplotlib 애니메이션) | 검증됨 |
| wham_to_smplfbx.py | WHAM pkl → 변환용 형식 | 검증됨 |
| smpl_pkl_to_fbx.py | pkl → FBX (bpy) | 변환 성공, 리타게팅 미해결 |
| retarget_smpl_to_mixamo.py / retarget_constraint_based.py | SMPL→Mixamo 리타게팅 (행렬 offset / 컨스트레인트) | 폐기 (`scripts/deprecated/`) |
| generate_smpl_mesh.py | SMPL 메쉬 생성 (키프레임 자세 + T포즈 + 관절 추출) | 검증됨 |
| align_smpl_to_trellis.py | TRELLIS-SMPL 자동 정렬 (bbox 기반 스케일·이동, IoU 검증) | 검증됨 |
| create_smpl_armature.py | SMPL 아마추어 생성·바인딩 (관절 좌표계 자동 보정) | 검증됨 |
| glb_tex.py | GLB 텍스처 추출 | 검증됨 |
| check_tex.py | Blender 텍스처 진단 | 검증됨 |
| setup_trellis.sh / run_trellis.py | TRELLIS 로컬 설치·실행 | 미실행 (Space로 대체 중), 레포 미반입 |
| gate1~3, orchestrator, config.yaml | 품질 게이트·자동화 골격 | 코드만 존재, 미연결. 자리는 `pipeline/qa/`에 확보 |

### 데이터 (Network Volume + 맥북)
- `/workspace/data/05_wham/zombie_sample1/` — wham_output.pkl, overlay.mp4 등
- 맥북: wham_output.pkl, zombie_anim2.fbx(동작 정상), GLB 원본, zombie_tex_0/1.png(구 버전 출력명, 현재는 `{glb명}_tex_N.png` 규칙), Mixamo FBX 2종
- Unity 프로젝트: 텍스처 연결된 좀비 + Mixamo 애니메이션 작동 상태

### 도구·계정
- Blender 5.2(FBX 임포터 조명 버그 있음) + 4.5 LTS(우회용) 공존 설치
- SMPL/SMPLify 계정(인증 완료), HF 계정, Mixamo(Adobe) 계정, RunPod($49+ 잔여)

---

## 7. 리스크·이슈

- **SMPL 라이선스**: 무료 버전은 비상업 연구용. 유니티 에셋 상용 배포 시 Meshcapade 상업 라이선스 필요. 프로젝트 성격 확정 전 반드시 검토.
- **SMPL prior의 좀비 자세 왜곡**: 짧은 테스트에서는 동작이 보존됐으나, 극단적 자세(기어가기, 관절 꺾임)에서 정상 자세로 회귀할 가능성. 실전 영상으로 추가 검증 필요.
- **Blender 5.2 FBX 임포터 버그**(조명 객체 파싱 실패) — 4.5로 우회 중.
- 리깅 자동화의 대안(UniRig)은 스키닝 모델 미공개 상태. SMPL 직접 리깅이 실패할 경우의 백업 부재.

---

## 8. 최근 작업

- **2026-08-13 — 레포 정리 완료**: 브랜치 통합(SAM2 노트북 6개를 main으로 merge 후 원격 브랜치 4개 삭제), 구조 재편(`docs/` `notebooks/sam2/` `scripts/` `pipeline/qa/` `docker/`), 흩어져 있던 스크립트 8종 회수, 레포 개명 및 README 갱신.
- **2026-08-18**: TRELLIS-SMPL 정렬 검증 통과. 자세 일치 육안 확인 — 상체 기울기·스트라이드·팔 위치 대응, 어긋남은 의복 두께 수준. 파라미터: Rot X -90°, Scale 0.588 (TRELLIS 1.001/SMPL 1.702), Location Y -2.58.

![정렬 검증](assets/align_check_frame.png)

- **2026-08-20**: 정렬 자동화 검증 — 자동 계산이 수동 측정 재현 (scale 0.5884, offset Y -2.629, bbox IoU 0.717). IoU가 정렬 게이트 판정 지표 후보로 확보됨.

| 항목 | 수동 측정 (08-18) | 자동 계산 (08-20) | 판정 |
|---|---|---|---|
| 스케일 | 0.588 | 0.5884 | 일치 |
| 이동 Y | -2.58 | -2.629 | 일치 (육안 측정 오차 수준) |
| 이동 X/Z | — | 0.013 / 0.021 | 육안으로 못 잡던 미세 오프셋 보정 |
| 겹침 | 육안 확인 | IoU 0.717 | 기준(0.5) 상회 |

이미지는 08-18 수동 정렬 캡처와 시각적으로 동일하여 생략. 정렬 상태는 `~/Desktop/aligned.blend` 참조.

### 설계 판단 두 가지

**웨이트 바인딩**: SMPL 공식 LBS 웨이트는 볼륨의 SMPL_NEUTRAL.pkl에만 있어 로컬 작업에서는 Blender Automatic Weights로 바인딩. SMPL 몸체는 토폴로지가 균일해 자동 웨이트 품질이 실용 수준. 스크립트에 `--weights` 옵션을 두어 추후 공식 웨이트(npy)로 교체 가능하게 설계.

**관절 좌표계 자동 보정**: joints json(OBJ 원본 좌표)과 정렬된 메쉬의 좌표계 차이를 수동으로 추정하지 않고, 후보 회전 4개를 시험해 관절-메쉬 최근접 거리 최솟값을 자동 선택. 리타게팅 단계에서 축 추정 실패를 세 차례 겪은 데 대한 재발 방지 설계.

| 후보 회전 | 평균 관절-메쉬 거리 | 판정 |
|---|---|---|
| identity | 0.0279 | ✅ 선택 |
| X+90 | 3.2521 | 탈락 |
| X-90 | 3.2275 | 탈락 |
| X180 | 5.0325 | 탈락 |

선택 후보와 차순위가 100배 차이로 판정 명확. 거리 0.028은 관절 중심과 피부 표면 간 해부학적 간격 수준으로, 관절이 메쉬 내부 정위치에 배치됨을 의미.

**포즈 시험 통과**: L_Shoulder·R_Shoulder·R_Knee 회전 시 해당 부위 메쉬가 관절 경계에서 분리되어 자연스럽게 변형됨을 육안 확인.

![포즈 시험 - R_Knee](assets/pose_test_knee.png)

- **2026-08-21**: 캐릭터 에셋 4종 완성 (외형+리깅+텍스처, 애니메이션 없음). 좀비 파이프라인의 외형 경로가 신규 입력 4종에 그대로 재현됨. Mixamo 텍스처 소실 → GLB 추출 재연결 패턴도 동일.

![캐릭터 에셋 4종](assets/char_assets_4.png)

- **2026-08-24**: 4단계 통과 — WHAM 69프레임이 리깅 좀비에서 원본 영상과 동일 패턴으로 재생. 웨이트 전이는 2단계 방식(0.08 정밀 + 전파) 확정. 발견: 찢어진 옷자락은 본체와 분리된 고립 섬(5.4만 정점)이라 자동 전이의 구조적 예외 — 별도 과제로 분리, G1a/G2 게이트에 부유 지오메트리 플래그 요건 추가.

![Blender 재생 검증 (Unity 반입 전 단계)](assets/wham_playback_blender.gif)

- **2026-08-24**: M1 달성 — Unity 반입 완료. Generic Rig로 임포트(rest가 T포즈가 아니므로 Humanoid 근육 변환 회피), Animator 재생으로 원본 영상 동작 재현 확인. 수동 파이프라인 전 구간(영상→SAM2→TRELLIS/WHAM→SMPL 리깅→Unity) 관통.
- **2026-08-25**: SAM2 RunPod 이전 완료 — Colab 의존 제거, 전 단계가 볼륨+레포 체계로 통일. 발견: 테스트 영상 실측 24fps, 키프레임 자동 후보에 수동 선택 프레임(f7) 포함 — G1a 설계 참고.
- **2026-08-27**: 좀비 영상 4종 소싱 완료 — Gemini 생성으로 확보 (저작권·초상권 무결). 스펙: 4종 동일 규격 240프레임/24fps/720p/10초, 전 항목 합격. 내용 검증: 1인·컷 없음·팔 벌린 키프레임·카메라 고정·AI 아티팩트 없음 육안 확인. 미결 2건: ①AI 생성 영상의 WHAM 적합성 미검증 — W2 좀비 2호 리허설이 첫 시험, 실패 시 직접 촬영 폴백 ②720p는 하한 — TRELLIS 품질 확인 후 필요시 1080p 재생성.
- **2026-08-28 — W1 주간 마무리 (M1 달성)**: 수동 파이프라인이 영상→에셋 전 구간을 관통했다. M1 체크리스트 다섯 항목(WHAM 동작 Unity 재생 · 통합 데모 GIF · main 머지 · runbook · SAM2 레포 반입)이 8/27에 모두 충족되어 목표 8/31보다 4일 앞섰다. 핵심은 v4의 SMPL 골격 직접 리깅이 실증된 것으로, 정렬 IoU 0.717 · 관절-메쉬 거리 0.028 · 웨이트 무배정 0%로 리타게팅 없이 WHAM 동작이 재생됐다. SAM2가 Colab에서 볼륨으로 옮겨오면서 전 단계가 레포+볼륨 체계로 통일됐고, 입력 영상 4종도 확보했다. W2(9/1~9/5) 목표는 자동화의 전제 조건인 **TRELLIS 로컬 설치**(Space 의존 제거)와 스크립트 CLI·경로 규약 표준화, 그리고 runbook 리허설을 겸한 좀비 2호 수동 제작이다. 2호 제작이 AI 생성 영상의 WHAM 적합성을 가리는 첫 시험이기도 하다.

---

## 9. 다음 단계 (우선순위)

1. **SMPL 리깅 1단계**: betas + pose → SMPL 메쉬 생성 스크립트 (smplx 패키지, 맥북)
2. 2단계: TRELLIS 메쉬와 정렬 (ICP/바운딩박스)
3. 3단계: 웨이트 전이 (bpy Data Transfer) → WHAM 동작 직접 재생 검증
4. 병행: SAM2 RunPod 이전(Colab → 볼륨 설치), 기준 미달인 테스트 영상을 조건 충족 클립으로 교체
5. 이후: TRELLIS 로컬 설치, 게이트 연결, 오케스트레이터 가동, Dockerfile 고정
