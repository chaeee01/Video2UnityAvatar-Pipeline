# site/assets — 공개 페이지 소재 매니페스트 (2026-11-06)

총 26개 · 3.17 MB. 영상 H.264 · 높이 540 · CRF 28 · ≤6초 · 무음, 스틸 JPEG q80 · 긴 변 ≤1200px.

| 파일 | 종류 | 크기 | 캐릭터 | 단계 | 캡션 | 전후 쌍 | 원본 |
|---|---|---|---|---|---|---|---|
| `assets/pipeline_v4.jpg` | image 698×1200 | 0.10 MB | - | 개요 | 파이프라인 v4 — 영상 한 편에서 외형(TRELLIS.2)과 동작(WHAM)을 따로 뽑아 SMPL 골격 하나로 합친다 | - | `~/Desktop/Video2UnityAvatar-Pipeline.wt/docs/assets/pipeline_v4.png` |
| `assets/lineup_meshes.jpg` | image 1200×682 | 0.10 MB | walker · listener · stalker · lurker · oiler · player · char_shuffle · dog | S3 외형 | 납품 캐릭터 8종의 TRELLIS.2 메쉬 (정면, 같은 조명) | - | `~/data/site_raw_1106/lineup.png` |
| `assets/input_ref_walker.jpg` | image 669×1200 | 0.09 MB | walker | 입력 | 입력 ① 캐릭터 참조 이미지 (영상 생성의 시작 프레임) | - | `~/data/00_raw/_refs_clean/manor_walker_01_v4_1116_clean.png` |
| `assets/input_video_walker.mp4` | video 304×540 | 0.13 MB | walker | 입력 | 입력 ② 생성 영상 — 걷기 (9:16, 24fps) | - | `~/data/00_raw/walker_walk_02__fast-ff.mp4` |
| `assets/s2_mask_walker.mp4` | video 304×540 | 0.13 MB | walker | S2 분할 | SAM2 마스크 — 배경을 지우고 몸만 남긴 클립을 다음 단계로 넘긴다 | - | `~/data/02_sam2/walker_walk_02/walker_walk_02_masked.mp4` |
| `assets/s5_wham_overlay_walker.mp4` | video 304×540 | 0.18 MB | walker | S5 동작 | WHAM 이 추정한 3D 몸(SMPL 정점)을 원본 영상에 투영 — 프레임마다 자세 · 위치를 복원 | - | `~/data/site_raw_1106/walker_wham_mesh_overlay.mp4` |
| `assets/s3_mesh_walker_turntable.mp4` | video 540×540 | 0.11 MB | walker | S3 외형 | TRELLIS.2 메쉬 턴테이블 — 키프레임 한 장에서 만든 PBR 메쉬 | - | `~/data/site_raw_1106/turn_walker/f_%04d.png` |
| `assets/s3_mesh_listener.jpg` | image 1200×1200 | 0.10 MB | listener | S3 외형 | listener 메쉬 | - | `~/data/site_raw_1106/mesh_listener.png` |
| `assets/s3_mesh_stalker.jpg` | image 1200×1200 | 0.08 MB | stalker | S3 외형 | stalker 메쉬 | - | `~/data/site_raw_1106/mesh_stalker.png` |
| `assets/s3_mesh_lurker.jpg` | image 1200×1200 | 0.09 MB | lurker | S3 외형 | lurker 메쉬 | - | `~/data/site_raw_1106/mesh_lurker.png` |
| `assets/s3_mesh_oiler.jpg` | image 1200×1200 | 0.10 MB | oiler | S3 외형 | oiler 메쉬 | - | `~/data/site_raw_1106/mesh_oiler.png` |
| `assets/s3_mesh_player.jpg` | image 1200×1200 | 0.09 MB | player | S3 외형 | player 대역 메쉬 (외형 납품 아님 — 동작 리타게팅용) | - | `~/data/site_raw_1106/mesh_player.png` |
| `assets/s3_mesh_char_shuffle.jpg` | image 1200×1200 | 0.09 MB | char_shuffle | S3 외형 | char_shuffle 메쉬 | - | `~/data/site_raw_1106/mesh_char_shuffle.png` |
| `assets/s3_mesh_dog.jpg` | image 1200×1200 | 0.09 MB | dog | S3 외형 | dog 메쉬 (골격 · 동작은 Mixamo) | - | `~/data/site_raw_1106/mesh_dog.png` |
| `assets/s4_align_walker.jpg` | image 1200×821 | 0.13 MB | walker | S4 리깅 | SMPL 몸을 TRELLIS 메쉬에 정렬한 결과 — 골격이 메쉬 안에 들어오는지 확인 | - | `~/Desktop/Video2UnityAvatar-Pipeline.wt/docs/assets/align_check_frame.png` |
| `assets/s4_transfer_walker.jpg` | image 1200×720 | 0.15 MB | walker | S4 리깅 | 웨이트 전이의 부위 제약 — 팔 · 다리가 서로 붙지 않게 | - | `~/Desktop/Video2UnityAvatar-Pipeline.wt/docs/assets/transfer_constraint_f138.png` |
| `assets/bake_walker_hit.mp4` | video 608×540 | 0.13 MB | walker | S7 결합 | 원본 영상(왼쪽)과 리그에 구운 동작(오른쪽) — 리타게팅 없이 같은 SMPL 골격 | - | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1026/08_final/videos/walker__walker_hit_01.mp4` |
| `assets/unity_placeholder.mp4` **[자리]** | video 942×540 | 0.03 MB | zombie1 (대체 후보) | Unity | [자리] 납품 캐릭터 Unity 캡처는 게임팀 요청 중 — 지금은 초기 샘플 zombie1 데모가 대체 후보 | - | `~/Desktop/Video2UnityAvatar-Pipeline.wt/docs/assets/unity_wham_demo.gif` |
| `assets/ba_weight_listener.mp4` | video 912×540 | 0.22 MB | listener | 문제 해결 · 웨이트 | 가랑이 · 겨드랑이 · 쇄골 경계 스무딩 — 원본 | 1차 수리 | 쇄골 추가 수리 | weight_smoothing · both — 가운데 before · 오른쪽 after (왼쪽은 원본 영상) | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1021/05_collar/collar_attack_original_wfix_c10.mp4` |
| `assets/ba_weight_listener_still.jpg` | image 1200×300 | 0.05 MB | listener | 문제 해결 · 웨이트 | 늘어난 막이 사라진 프레임 비교 (f163 · f96) | weight_smoothing · both — 왼쪽 before · 오른쪽 after | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1021/05_collar/collar_attack_f163_f96_wfix_vs_c10.png` |
| `assets/ba_weight_walker.mp4` | video 608×540 | 0.07 MB | walker | 문제 해결 · 웨이트 | walker 겨드랑이 스무딩 — 팔을 들 때 옆구리 막 | weight_smoothing · both — 왼쪽 before · 오른쪽 after | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1021/07_walker/walker_attack_cur_vs_arm20.mp4` |
| `assets/ba_slide_listener.mp4` | video 912×540 | 0.17 MB | listener · stalker | 문제 해결 · 미끄러짐 | 달리기 미끄러짐 — 발이 뒤로 쓸리지 않던 판 | stalker 동작 | listener 리그에 이식한 판 | foot_slide · both — 왼쪽 before · 오른쪽 after (가운데는 동작 출처) | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1019/01_listener_run_slide/compare_L04b_M_stalker_R_transplant.mp4` |
| `assets/ba_slide_listener_still.jpg` | image 1200×300 | 0.04 MB | listener | 문제 해결 · 미끄러짐 | 디딘 발 위치 비교 클로즈업 | foot_slide · both — 왼쪽 before · 오른쪽 after | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1019/01_listener_run_slide/closeup_04b_f34_vs_transplant_f60_f50.png` |
| `assets/ba_floor_walker.mp4` | video 608×540 | 0.08 MB | walker | 문제 해결 · 바닥 | 바닥 정렬 — 깊이 숙일 때 몸 전체가 바닥 아래로 내려가던 것 | floor_align · both — 왼쪽 before · 오른쪽 after | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1026/09_ga_replace/walker_idle_lurch_전후.mp4` |
| `assets/ba_floor_stalker.mp4` | video 608×540 | 0.05 MB | stalker | 문제 해결 · 바닥 | 바닥 정렬 — 엎드린 몸이 바닥에서 떠 있던 것 | floor_align · both — 왼쪽 before · 오른쪽 after | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1026/09_ga_replace/stalker_crawl_loop_전후.mp4` |
| `assets/ba_gait_stalker.mp4` | video 1218×540 | 0.59 MB | stalker | 문제 해결 · 보행 | 프롬프트 한 줄의 효과 — 걷기 | 걷기+러닝머신 문장 | 달리기 | 달리기+러닝머신 문장 (쓸기 −0.26 → −0.57, 대신 자세가 바뀜) | gait_prompt · both — 각 쌍의 왼쪽 before · 오른쪽 after | `~/Desktop/3D_avatar_work/experiments/e2e_check/review_1102/09_sweeptest/원본_walk01_walk01s_run01_run01s.mp4` |
