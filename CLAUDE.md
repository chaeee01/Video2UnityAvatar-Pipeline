# Video2UnityAvatar-Pipeline

## 프로젝트 맥락

좀비 영상 입력 → 외형·리깅·동작을 갖춘 Unity 에셋 출력의 완전 자동 파이프라인. 모든 세션 시작 시 아래를 참조한다.

- 프로젝트 상태는 `docs/PROJECT_STATUS.md`의 "최근 작업" 절 참조.
- 현재 계획 위치는 `docs/ROADMAP.md` 참조.
- 절차 질문은 `docs/RUNBOOK.md` 참조.
- 경로·CLI 규약은 `docs/CONVENTIONS.md` 참조.
- 실험 작업은 `feature/` 브랜치에서 진행하고, 검증 후 `main`에 머지하는 것이 규칙.

### 파이프라인 v4 단계 (출처: README.md "현재 설계 (v4)" — 그림 `docs/assets/pipeline_v4_current.png`)

| 약어 | 이름 | 역할 |
|---|---|---|
| G0 | G0 · 입력 검증 | 프레임 수 · fps · 해상도 실측 |
| S2 | SAM2 분할 · 트래킹 | 마스크와 원본 클립 모두 보존 · 키프레임 1차 후보 |
| G1 (gate_s2) | G1 · 분할 판정 | 마스크 커버리지 · 빈 프레임 · 조각 수. 불합격 시 프롬프트 바꿔 다시 시도 (시도 최대 3회) |
| S5 | WHAM 동작 복원 | 마스크 영상 입력. 고정 카메라 (local only, DPVO 미설치). betas, pose, transl 추정 |
| G1 (gate_s5) | G1 · 추적 판정 | 트랙 연속성 — 끊김 없이 전 프레임 추적 |
| G3 | G3 · 재투영 일관성 | 몸 관절 12개 재투영 오차 (키 대비). PASS · CHECK 기록 · 안내 (불합격 없음, 2026-11-21~). 발 접지는 G4 |
| G1a | G1 · 키프레임 선정 | 마스크: 다리 벌어짐 + WHAM pose: 시선각. 다리 움직임 없는 클립은 붙은 다리 허용 |
| S3 | TRELLIS.2 외형 생성 | 단일 뷰(키프레임 1장) 입력 · 메쉬 + 텍스처 생성 |
| G2 | G2 · 메쉬 품질 | 유효 metallic · 데시메이션 비율. 불합격 시 seed 바꿔 다시 생성 (시도 최대 2회) |
| S4 | SMPL 골격 직접 리깅 | WHAM 키프레임 정점으로 SMPL 메쉬 (5-1) → TRELLIS 메쉬와 정렬 (스케일, 회전) → 웨이트 전이 3단 → 경계 스무딩 |
| G2r | G2 · 리깅 검증 | 정렬 스케일 · bbox IoU · 관절 거리, 말단 본 · 좌우 교차 · 부위 잇는 엣지 · 폴백 분포 |
| S7 | 동작 결합 · 베이킹 | 골격이 동일하므로 리타게팅 없음. SMPL pose 를 리깅 메쉬에 직접 적용 (Y-up, TRELLIS 정규화 단위). 베이킹(클립 전 프레임) · 바닥 정렬 (5-5). 걷기류(걷기 · 달리기) 납품 클립은 서 있는 도입부를 자르고 루프 위상을 맞춘 고정 npz 로 굽는다(11/02 사용자 지시, 14편 — 모션 폴더 `gait_window.json` · `track_select.json`. 만드는 스크립트 `gait_window.py` 는 레포에 없어 새 클립에는 자동 적용되지 않는다 — RUNBOOK 1.5절) |
| G4 | G4 · 클립 품질 | 동작 클립마다 — 늘어남 · 발 쓸기 · 바닥 수치 판정. 동작 트랙(`--motion`)에서만 돈다. CHECK · FAIL 이면 클립 FBX 를 내보내지 않음 → 사람 확인 · 수용 기록 → G4 만 다시 판정 (종료 코드 2) |
| R | 오케스트레이터 (orchestrate.py) | 명령 하나로 전 구간 · 사람 개입 0~1회. 단계별 자동 시도 S2 최대 3회 · S3 최대 2회 (그 밖 1회) → 넘으면 사람 개입 (종료 코드 2) |

게이트 묶음은 공개 페이지 표와 같다 — G0 / G1(gate_s2 · gate_s5 · G1a) / G2(G2 · G2r) / G3 / G4. S5 에서 외형 경로로 가는 전달은 둘이다 — **pose 전달 (시선각 · 다리 움직임)** → G1a, **SMPL 몸 전달 (체형 betas · 키프레임 자세 반영)** → S4. 11/14 이전 표의 S0 · S1 · G1m · S6 은 구현되지 않았거나(S0 · S1) 흡수됐다(G1m → gate_s2 · gate_s5, S6 → S7 · 5-2) — PROJECT_STATUS 2026-11-21 "설계도를 지금 구현된 모습으로" 항목.

WHAM(S5)의 SMPL 몸(체형 포함)을 S4 리깅에 그대로 사용해 두 경로의 골격을 SMPL로 통일한다. 골격이 같으므로 S7에 리타게팅이 없다 — v4의 핵심이자 v3와의 유일한 차이.

실행 순서는 **`S2 → S5 → G1a → S3`** 다 (2026-10-08 변경, 표도 이 순서). 키프레임을 고르는 데 WHAM pose 가 필요해 동작 경로가 외형 경로보다 먼저 돈다. 근거는 `docs/ORCHESTRATOR_DESIGN.md` 10절.

### 실행 환경

- 레포별 의존성 충돌(torch 1.11-2.5, CUDA 11.3-12.4)로 단일 환경이 불가능하다. micromamba로 환경을 분리한다 — `wham` / `sam2` / `trellis`. 우회가 아니라 확정된 원칙.
- GPU 작업은 RunPod(RTX 4090, EU-RO-1) + Network Volume `/workspace`.
- 볼륨에 직접 설치한다. Dockerfile은 환경 확정 후 굳힌다.
- 로컬 작업은 Blender 4.5 LTS. 5.2는 FBX 임포터에 조명 객체 파싱 버그가 있다.

### 경로 규약

볼륨 공통 — micromamba는 `/workspace/micromamba/bin/micromamba`(전 환경 공통), 레포는 `/workspace/repos/`(이 레포는 `/workspace/repos/Video2UnityAvatar-Pipeline`), 로그는 `/workspace/logs/`, 캐시는 `/workspace/.cache/`(pip, huggingface, torch, torch_extensions, u2net).

`data/` 번호는 `00_raw` · `01_pre` · `02_sam2` · `03_trellis` · `04_wham` · `05_smpl_mesh` · `06_rig` · `07_unity` 순이다. 폴더 번호는 산출물 생성 순서이고 **S번호와는 독립된 식별자**라 1:1이 아니다 — 번호를 보고 단계를 추정하지 말 것. 번호별 내용·구번호 대응표·맥북 미러(`~/data/`) 규약은 `docs/CONVENTIONS.md` 참조.

환경 setup 스크립트는 `scripts/setup_{wham,sam2,trellis,trellis2}.sh` 4종이다. `sam2` 는 원래 수동 설치라 스크립트가 없었으나 2026-09-29 에 Pod 환경을 역추적해 복원했다 (EH-226). 환경 아카이브·복원 절차는 `docs/RUNBOOK.md` 8절 참조.

### RunPod 원격 작업

- Pod 생성·GPU 선택·Terminate는 사용자가 콘솔에서 한다. Claude Code는 SSH 접속 이후만 담당하며 RunPod API를 호출하지 않는다.
- 접속은 ssh 별칭 `runpod`. IP·포트는 재배포마다 바뀌므로 사용자가 주면 `~/.ssh/config`를 갱신하고, 없으면 추측하지 말고 요청한다.
- 5분 이상 걸리는 원격 작업은 `nohup` + `/workspace/logs/` 로그로 백그라운드 실행하고 `tail`로 확인한다. 전경에서 붙잡지 않는다.
- Pod은 Stop이 아니라 Terminate — Stop은 스토리지가 2배로 과금된다. Terminate 전에 결과 파일을 로컬로 회수했는지 사용자에게 확인한다.

### 깃헙·지라 관리

| 시점 | 깃헙 | 지라 |
|---|---|---|
| 작업 시작 | `feature/` 브랜치 생성 | 카드 → 진행 중 |
| 중간 결과 | feature에 커밋·푸시 | 코멘트 (수치·로그 경로) |
| 검증 통과 | main 머지 + 같은 머지에 PROJECT_STATUS "최근 작업" 항목 | 카드 → 완료 |
| 검증 실패 | feature 유지 | 코멘트에 원인 |
| 커밋 전 | 문서 외 변경은 관련 시험 실행 (`tests/`). push 하면 CI(`tests.yml`)가 RUN 목록의 시험(2026-11-19 기준 13개 파일)을 자동 실행하지만, 건너뜀 7개(미러 · Blender 필요, 실물 절 0건)는 맥에서 직접 돌린다. 새 시험 파일은 `tests/ci/test_script_suite.py` 의 RUN 또는 SKIP 에 넣는다(빠지면 수집 단계에서 멈춘다) | — |
| 주간 마무리 | PROJECT_STATUS 주간 요약 + ROADMAP 체크 | 다음 주 카드 정리 |

- PROJECT_STATUS는 feature 브랜치에서 고치지 않고 main 머지 때 갱신한다.
- 문서만 바꾸는 작업은 `docs/` 브랜치에서 하고, 검토 후 바로 머지한다.

### 안전 규칙

- 비가역 작업은 실행 전 사용자 승인을 받는다: Pod terminate, `/workspace` 이하 삭제, micromamba 환경 삭제, `git push --force`, 브랜치 삭제, 파일 삭제.
- `.env`는 커밋하지 않고, 토큰이 출력에 노출되지 않게 한다.
- 검증되지 않은 스크립트는 `main`에 머지하지 않는다.
- 단계별로 보고하고 승인을 받은 뒤 진행하는 것이 기본이다.
- 보고 인용 시 원문 확인 필수 — 기억으로 재구성한 보고 내용(숫자·프레임 번호·질문의 존재)을 검증 없이 전제하지 않는다. 세션 트랜스크립트·`git log`·파일 내용이 근거다. 확인되지 않으면 "확인되지 않음"으로 보고하고, 그 인용에 기대어 문서·코드를 고치지 않는다. 사용자와 Claude 양쪽에 같이 적용된다.

## Jira 연동

Jira 작업 시 프로젝트 루트의 `.env`에서 자격증명을 읽어 REST API를 호출한다.
`.env`는 `.gitignore`로 차단돼 있으며 절대 커밋하지 않는다.

`.env` 항목:

| 키 | 용도 |
|---|---|
| `JIRA_SITE` | API 기준 URL (`https://studio301.atlassian.net`) |
| `JIRA_EMAIL` | Basic 인증 사용자 |
| `JIRA_TOKEN` | Atlassian API 토큰 |
| `JIRA_PROJECT` | 프로젝트 키 (`EH`) |
| `JIRA_BOARD_URL` | 백로그 보드 링크 (참고용, API 미사용) |

호출 방식 — Basic 인증(`이메일:토큰`), API v3:

```bash
set -a && . ./.env && set +a
curl -s -u "$JIRA_EMAIL:$JIRA_TOKEN" -H "Accept: application/json" \
  "$JIRA_SITE/rest/api/3/myself"
```

주요 엔드포인트:

| 작업 | 엔드포인트 |
|---|---|
| 내 계정 확인 | `GET /rest/api/3/myself` |
| 카드 검색 | `GET /rest/api/3/search/jql?jql=project=EH` |
| 카드 생성 | `POST /rest/api/3/issue` |
| 상태 전이 조회 | `GET /rest/api/3/issue/{key}/transitions` |
| 상태 전이 실행 | `POST /rest/api/3/issue/{key}/transitions` |
| 코멘트 추가 | `POST /rest/api/3/issue/{key}/comment` |

주의사항:

- 설명·코멘트 본문은 평문이 아니라 **ADF(Atlassian Document Format)** JSON으로 보내야 한다.
- 상태 이름은 한글이다 (`할 일`, `진행 중`, `완료`). 전이 ID는 카드마다 다를 수 있으므로 하드코딩하지 말고 매번 transitions를 조회한다.
- 카드 제목 끝의 ` : N`은 스토리 포인트 관례다.
- 토큰이 출력에 노출되지 않도록 `curl` 결과만 파싱한다.
- 카드 생성 시 assignee를 항상 명시할 것 (미지정 시 프로젝트 기본 담당자가 들어감).
- 생성 전에 제목 유사 카드 중복 조회 필수.
