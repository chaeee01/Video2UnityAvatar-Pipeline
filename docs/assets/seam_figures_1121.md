# 5-4b 웨이트 경계 스무딩 — 수리 전후 근접 그림 출처 (2026-11-21)

공개 페이지 사례 ② 와 README 의 5-4b 문단이 쓰는 그림 4장의 출처다. 칸 순서 · 라벨은 굽기 파일과 리그를 직접 렌더해 정했다(파일명 추정 아님).

| 파일 | 크기 | sha256 | 쓰는 곳 |
|---|---|---|---|
| `site/assets/seam_crotch_listener_s.jpg` | 1200×750 | `4e7ea881d9802dd3078fcf711c2ec04dfc6655fffb8a30bd0f317aaf0e97874b` | 공개 페이지 사례 ② (16:10 칸) |
| `site/assets/seam_armpit_listener_s.jpg` | 1200×750 | `433b50ce17855c461b80c421658e2efbcf6c8781f802bc2f5f3dd4874c50607a` | 공개 페이지 사례 ② (16:10 칸) |
| `site/assets/seam_crotch_listener.jpg` | 1596×638 | `789d2646ab8727cc3b2f4c2da75fda4f185aac0617cf9990603158b3a1c9300d` | README 5-4b · 포트폴리오 |
| `site/assets/seam_armpit_listener.jpg` | 1596×638 | `c97614a4db84d79f581709b18f243a14e58f0329bf8d6c3406e76a2649e72b16` | README 5-4b · 포트폴리오 |

## 원천

| 그림 | 칸 | 굽기 (`animated.blend`) | 굽기 sha256 | 리그 (`transferred.blend`) | 리그 sha256 |
|---|---|---|---|---|---|
| 가랑이 · run_04b f34 | 수리 전 | `~/data/06_rig/listener_apose_06/motions/listener_run_04b/` | `20aa383097e531e3b66be92bc49e094e30e69368a4c757c7fa75f4f9efdcf5fa` | `listener_apose_06` | `f0c3b5caf5f3a3158ebbe2a82e8ed4d40afc68d3896970e4958fe33567aef1cd` |
| 가랑이 · run_04b f34 | 수리 후 | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1021/02_wfix/bake04b_a/` | `1b532646209c12d18d8dc51de25d2e8a4ccd8a822c7a39b3f930b76f9842b42a` | `listener_apose_06_wfix_a` — 가랑이 L_Hip:R_Hip 10겹 · 40회 | `a43e1c904d5948dc9885463b2eb62714747dada5a4d3ed171522927288cec142` |
| 겨드랑이 · run(이식판 `listener_x_stalker_run_fwd`) f62 | 수리 전 | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1019/01_listener_run_slide/transplant_stalker_run_fwd/` | `9e5f69c91525a41f8fc712a6daa2c2889d26536cacf60dc61cae8895958c0132` | `listener_apose_06` (가랑이도 수리 전) | `f0c3b5caf5f3a3158ebbe2a82e8ed4d40afc68d3896970e4958fe33567aef1cd` |
| 겨드랑이 · run f62 | 수리 후 | `~/data/06_rig/listener_apose_06_wfix/motions/listener_x_stalker_run_fwd/` | `8649f16cf26eb3aaebbeb596db626aca6d413c2af53cbbf41ffb1ce8bb549b45` | `listener_apose_06_wfix` — 10/21 채택(가랑이 + 겨드랑이 L/R_Shoulder:Spine1·2 20겹 · 160회, `_wfix_a_arm20` 과 바이트 동일) | `fb228c5571a3a301587d12864dfce7f85fdcc460443ecb7b8ab08712255a8518` |

굽기 로그(`bake.log` 의 `Read blend`)로 각 굽기가 읽은 리그를 확인했다. 겨드랑이 전후 굽기의 동작 입력(`wham_pose.npz`)은 같은 파일(`559a51ea…`), 신장비 1.00431 로 같다. 네 리그의 `rest_pose.json` 은 같은 파일(`82a1ba3d…`) — 골격은 같고 웨이트만 다르다.

## 카메라 · 렌더

`tools/site/site_seam_closeup.py` — `tools/review/closeup.py` 와 같은 카메라(정면 직교, Workbench 텍스처, 배경 0.3/0.3/0.32, 본 앞 3 단위, 800×800)에 화면 중심 오프셋을 더했다. 오프셋 0 이면 `closeup.py` 와 픽셀 동일, 같은 입력을 두 번 렌더하면 픽셀 동일(PNG 메타데이터만 다름). Blender 4.5.12 LTS.

| 그림 | 근접 | 전신 소형 컷 |
|---|---|---|
| 가랑이 f34 | 본 Pelvis · 폭 0.4 · 오프셋 (+0.02, −0.14) → 화면 중심 (0.0283, −0.1029) | Pelvis · 폭 1.1 · 중심 (0.0083, 0.0371) |
| 겨드랑이 f62 | 본 L_Shoulder · 폭 0.4 · 오프셋 (0, −0.1) → 화면 중심 (0.1122, 0.2124) | Pelvis · 폭 1.1 · 중심 (0.0207, 0.0457) |

합성 `tools/site/site_seam_compose.py` — 잘라내기 · 축소 · 라벨 · 위치 상자만(픽셀 보정 없음). 라벨 · 구분선은 `slide_listener_seq(_s).jpg` 실측에 맞췄다: Apple SD Gothic Neo Bold, 글자 (250, 235, 160), 불투명 상자 (20, 20, 20)를 칸 왼쪽 위 모서리에 붙임 — README 판 26px · 상자 90×42 · 흰 구분선 10px, 16:10 판 40px · 상자 137×58 · 흰 구분선 6px. README 판 왼쪽 전신 컷(수리 전 굽기)의 주황 상자가 근접 영역이다(기존 그림에 대응 요소 없음). 16:10 판은 근접 800×800 에서 637×800 창(가랑이 x 82~, 겨드랑이 x 164~)을 597×750 으로.

## 수치 (PROJECT_STATUS 10/21 웨이트 수리 표 원문)

- 가랑이 L_Hip:R_Hip 10겹 · 40회: 04b 가랑이 0.10 초과 471 → 0, 전체 579 → 72, 최장 0.179 → 0.119. f24~66 띠 사라짐(사용자 확인).
- 겨드랑이 L/R_Shoulder:Spine1·2 20겹 · 160회: run · run_slow 왼쪽 겨드랑이 0.10 초과 266 · 257 → 0.
- 프레임: 가랑이 471 은 f34 의 값(측정 `review_1021/02_wfix/measure/adopted_04b.json`, 최대는 f47 의 541). 겨드랑이 266 의 프레임은 f51(`regress/run_adopted.json`). 그림은 f62 — f51 의 찢긴 조각은 실루엣 안쪽 · 같은 색이라 거의 안 보이고, f62 는 허리 높이에서 실루엣 밖으로 튀어나와 보인다(10/21 실험 기록 "run f62 … 왼소매 옆 허리 높이 조각").

## 기존 근접 캡처의 칸 확정 (2026-11-21)

`review_1021/02_wfix/closeup_f34_adopted_a_ab.png` · `arm_run_f62_a_arm10_arm20.png` 의 각 칸을 `closeup.py` 로 다시 렌더해 픽셀 대조했다 — 기록에 없던 인자는 실루엣 맞춤 + 24본 전수 렌더로 찾았다(가랑이 Pelvis 1.1, 겨드랑이 L_Shoulder 0.6).
- `closeup_f34_adopted_a_ab.png` = 왼쪽부터 수리 전(`listener_apose_06` 굽기) · 가랑이 수리(`_wfix_a`) · 가랑이 + BFS 용접(`_wfix_ab`, 채택 안 됨) — 각 칸 재렌더와 픽셀 차 0.
- `arm_run_f62_a_arm10_arm20.png` = 왼쪽부터 `_wfix_a`(가랑이만 수리 — 겨드랑이는 수리 전과 같은 266) · 겨드랑이 10겹 · 20겹(채택) — 픽셀 차 0. **왼쪽 칸은 "수리 전 리그" 가 아니다.**
- 실험 기록 폴더는 `~/Desktop/e2e_check/` 에서 `~/Desktop/3D_avatar_work/experiments/e2e_check/` 로 옮겨져 있다(리그 `WFIX.md` · 로그의 경로는 옛 위치).
