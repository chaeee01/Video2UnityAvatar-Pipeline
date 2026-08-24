# Video2UnityAvatar-Pipeline

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
