# Video2UnityAvatar-Pipeline

## 프로젝트 맥락

좀비 영상 입력 → 외형·리깅·동작을 갖춘 Unity 에셋 출력의 완전 자동 파이프라인. 모든 세션 시작 시 아래를 참조한다.

- 프로젝트 상태는 `docs/PROJECT_STATUS.md`의 "최근 작업" 절 참조.
- 현재 계획 위치는 `docs/ROADMAP.md` 참조.
- 절차 질문은 `docs/RUNBOOK.md` 참조.
- 실험 작업은 `feature/` 브랜치에서 진행하고, 검증 후 `main`에 머지하는 것이 규칙.

### 파이프라인 v4 단계 (출처: README.md "현재 설계 (v4)")

| 약어 | 이름 | 역할 |
|---|---|---|
| G0 | 입력 검증 | 해상도, 압축 아티팩트, 대상 존재 |
| S0 | 전처리 | fps / 해상도 / 색공간 정규화 |
| S1 | PySceneDetect | 컷 감지, 클립 분할 |
| S2 | SAM2 | 분할·트래킹 (마스크와 원본 클립 모두 보존) |
| G1a | 외형용 클립 평가 | 선명도, 시야각, 잘림 |
| S3 | TRELLIS | 단일/다중 뷰 → 메쉬 + 텍스처 |
| G2 | 메쉬 품질 | LPIPS, CLIP-I, 실루엣 IoU, UV 왜곡 |
| S4 | SMPL 골격 직접 리깅 | SMPL 메쉬 생성 → TRELLIS 메쉬와 정렬 → 웨이트 전이 |
| G2r | 리깅 검증 | SMPL 24본 계층, 정렬 오차 |
| G1m | 동작용 클립 평가 | bbox 높이, 가림, 인원수 |
| S5 | WHAM | betas, pose, transl 추정 |
| G3 | 동작 품질 | 재투영 PCK, MPJPE, 발 접지 |
| S6 | 좌표 변환 | Y-up, 미터 단위, pose 시퀀스 |
| S7 | 동작 결합 | 골격이 동일하므로 리타게팅 없음 |
| G4 | 최종 통합 평가 | 메쉬 관통, 발 접지, 원본 클립 대조 |
| R | 재시도 오케스트레이터 | 불합격 시 실패 원인별 게이트 재진입 |

WHAM(S5)의 betas를 S4로 전달해 두 경로의 골격을 SMPL로 통일한다. 골격이 같으므로 S7에 리타게팅이 없다 — v4의 핵심이자 v3와의 유일한 차이.

### 실행 환경

- 레포별 의존성 충돌(torch 1.11~2.5, CUDA 11.3~12.4)로 단일 환경이 불가능하다. micromamba로 환경을 분리한다 — `wham` / `sam2` / `trellis`. 우회가 아니라 확정된 원칙.
- GPU 작업은 RunPod(RTX 4090, EU-RO-1) + Network Volume `/workspace`.
- 볼륨에 직접 설치한다. Dockerfile은 환경 확정 후 굳힌다.
- 로컬 작업은 Blender 4.5 LTS. 5.2는 FBX 임포터에 조명 객체 파싱 버그가 있다.

### 경로 규약

볼륨 공통 — micromamba는 `/workspace/micromamba/bin/micromamba`(전 환경 공통), 레포는 `/workspace/repos/`(이 레포는 `/workspace/repos/Video2UnityAvatar-Pipeline`), 로그는 `/workspace/logs/`, 캐시는 `/workspace/.cache/`(pip, huggingface, torch, torch_extensions, u2net).

| 번호 | 경로 | 근거 |
|---|---|---|
| 00 | `data/00_raw` | run_sam2.py |
| 01 | 미정 | 계획 (ROADMAP W2 목), 미구현 |
| 02 | `data/02_sam2` | run_sam2.py, run_trellis.py |
| 03 | `data/03_trellis` | run_trellis.py, setup_trellis.sh |
| 04 | 미정 | 계획 (ROADMAP W2 목), 미구현 |
| 05 | `data/05_wham` | run_wham.sh, generate_smpl_mesh.py, convert_wham_npz.py |
| 06 | `data/06_smpl_mesh` | generate_smpl_mesh.py |
| 07 | 미정 (`07_unity` 예정) | 계획 (ROADMAP W2 목), 미구현 |

S번호와 `data/` 번호는 1:1이 아니다 (예: `06_smpl_mesh`는 S4 산출물). 번호를 추정하지 말 것.

`sam2` 환경은 setup 스크립트가 없다 — 수동 설치라 재현 절차 미확보.

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
| 주간 마무리 | PROJECT_STATUS 주간 요약 + ROADMAP 체크 | 다음 주 카드 정리 |

- PROJECT_STATUS는 feature 브랜치에서 고치지 않고 main 머지 때 갱신한다.
- 문서만 바꾸는 작업은 `docs/` 브랜치에서 하고, 검토 후 바로 머지한다.

### 안전 규칙

- 비가역 작업은 실행 전 사용자 승인을 받는다: Pod terminate, `/workspace` 이하 삭제, micromamba 환경 삭제, `git push --force`, 브랜치 삭제, 파일 삭제.
- `.env`는 커밋하지 않고, 토큰이 출력에 노출되지 않게 한다.
- 검증되지 않은 스크립트는 `main`에 머지하지 않는다.
- 단계별로 보고하고 승인을 받은 뒤 진행하는 것이 기본이다.

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
