# 빠른 시작 — 영상 1편 → 리깅된 FBX (외형 트랙)

> **검증된 범위**
> - **검증됨** — 준비된 볼륨(SMPL 3개 · 모델 캐시 · 레포)을 붙인 새 서버에서 명령 하나로 영상 1편 → FBX (2026-11-21,
>   [PROJECT_STATUS](PROJECT_STATUS.md) 11/21 "관통 검증" 표 — 외형 walker_walk_02 364초 · 481초, 종료 코드 0).
> - **미검증** — 빈 볼륨에서 시작하는 준비(SMPL 배치, 모델 첫 다운로드). 아래 3단계는 필요한 것의 목록이고 **돌려 본 기록이 없다.**
> - **필요한 것** — GHCR 읽기 권한(1단계), SMPL 라이선스("무료 판은 비상업 연구용이다. 상업 배포에는 Meshcapade 라이선스가
>   필요하다" — [VISION.md](VISION.md)), RunPod 계정(GPU RTX 4090, 리전 EU-RO-1).

**1. 이미지 접근 권한** — 실행 이미지 `ghcr.io/chaeee01/v2ua-all` 은 비공개다.
- 받는 사람: 자기 GitHub 아이디를 소유자(chaeee01)에게 전한다 → 권한을 받으면 `read:packages` 권한만 가진 PAT 를 만들어
  RunPod 템플릿의 Container Registry Credentials 에 넣는다([RUNBOOK 1-A](RUNBOOK.md#1-a-이미지-pod-기본) 1).
- 소유자: 패키지 설정 → Manage access → 그 아이디로 초대, 역할 Read
  ([GitHub Docs — Configuring a package's access control and visibility](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)).

**2. 볼륨 · 템플릿 · 배포** — Network Volume 은 리전 EU-RO-1. 템플릿: 이미지 `ghcr.io/chaeee01/v2ua-all:v3-20261121-d160513`,
Start Command 비움, 환경 변수 `PUBLIC_KEY` = 맥의 `~/.ssh/id_ed25519.pub` 내용, Expose TCP `22`, Volume Mount Path `/vol`.
Storage → 볼륨 → 이 템플릿으로 Deploy. → [RUNBOOK 1-A](RUNBOOK.md#1-a-이미지-pod-기본) 1~2

**3. 볼륨에 있어야 하는 것 (미검증 — 돌려 본 기록 없음)** — 이미지에 넣지 않은 것들이다([RUNBOOK 1-A](RUNBOOK.md#1-a-이미지-pod-기본) 3).
- `/vol/repos/Video2UnityAvatar-Pipeline` — 이 레포(공개)
- `/vol/repos/WHAM/dataset/body_models/` — SMPL 3개: `smpl` · `smplx2smpl.pkl` · `smpl_mean_params.npz`(라이선스상 재배포 불가.
  받는 절차는 이 레포에 정리돼 있지 않다 — `scripts/setup_wham.sh` 는 WHAM 레포의 `fetch_demo_data.sh` 를 안내한다)
- `/vol/.cache` — 모델 캐시(trellis2, 약 27GB)
- `/vol/data/00_raw/` — 입력 영상

**4. 접속 · 영상 올리기** — 콘솔의 "SSH over exposed TCP" 주소 · 포트. 영상 조건: 90~600프레임 · 24~30fps · 세로 720 이상
([RUNBOOK 0절](RUNBOOK.md#0-입력-조건-g0g1-수동-적용) · 0-A).

```bash
ssh -p <포트> root@<IP> -i ~/.ssh/id_ed25519
rsync -rt -e "ssh -p <포트> -i ~/.ssh/id_ed25519" <영상>.mp4 root@<IP>:/vol/data/00_raw/      # 맥에서
```

**5. 명령 하나 (Pod 에서)** — SMPL · 캐시를 이미지 경로에 잇고([RUNBOOK 1-A](RUNBOOK.md#1-a-이미지-pod-기본) 3) 돌린다
([1.5절](RUNBOOK.md#15-원커맨드-실행--orchestratepy)). 실측 약 6~8분.

```bash
B=/workspace/repos/WHAM/dataset/body_models
for f in smpl smplx2smpl.pkl smpl_mean_params.npz; do ln -s /vol/repos/WHAM/dataset/body_models/$f $B/$f; done
ln -s /vol/.cache /workspace/.cache
cd /vol/repos/Video2UnityAvatar-Pipeline
PYTHONUNBUFFERED=1 PIPELINE_VOL=/vol PIPELINE_ENV_ROOT=/workspace nohup \
  python3 scripts/orchestrate.py --video /vol/data/00_raw/<영상>.mp4 --name <이름> > /vol/logs/<이름>.log 2>&1 &
tail -f /vol/logs/<이름>.log
```

종료 코드 **0 성공 / 1 실패(로그를 본다) / 2 사람이 정할 차례** — 할 일은
[RUNBOOK 5.8](RUNBOOK.md#58-check--fail-이-떴을-때--게이트별-대응-2026-11-22-정리), 이어받기는 같은 명령에 `--resume`(`--video` 대신).

**6. 회수 · Terminate (맥에서)** — 결과는 `/vol/data` 에 남는다. 맥 `~/data` 로 내린 뒤 Pod 을 **Terminate**(Stop 은 스토리지 2배 과금).
→ [RUNBOOK 7절](RUNBOOK.md#7-회수--정리)

```bash
for d in 02_sam2/<이름> 03_trellis2/<이름> 04_wham/<이름>_masked 05_smpl_mesh/<이름> 06_rig/<이름> 07_unity/<이름>; do
  mkdir -p ~/data/$d && rsync -rt -e "ssh -p <포트> -i ~/.ssh/id_ed25519" root@<IP>:/vol/data/$d/ ~/data/$d/
done
```

**7. Unity 반입** — `~/data/07_unity/<이름>/<이름>_wham.fbx`(메쉬 + SMPL 골격 + 웨이트 + 동작). 텍스처는 FBX 에 들어가지 않아
`~/data/03_trellis2/<이름>/textures/` 를 따로 연결하고, 크기는 정규화 단위라 Unity 에서 스케일을 수동 보정한다. → [RUNBOOK 6절](RUNBOOK.md#6-unity-반입-s7)

**그다음 — 같은 캐릭터에 다른 동작 굽기(동작 트랙, 미검증).** 외형 트랙의 리그를 채택하고(`scripts/make_rest_pose.py` →
`06_rig/<캐릭터>/character.json`) 역할표 `06_rig/<캐릭터>/clip_roles.json` 에 클립 항목(`source` · `role` · `bake.ground_align`)을
적으면 `--motion --character <캐릭터>` 로 돈다. 새 캐릭터로 이 순서를 돌린 기록은 없다 — [RUNBOOK 1.5](RUNBOOK.md#15-원커맨드-실행--orchestratepy) "동작 트랙"
· 5-5 "모션 트랙".
