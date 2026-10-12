"""G2r 게이트: SMPL 정렬·리깅 결과를 판정한다.

align_smpl_to_trellis.py 의 aligned_params.json 과 transfer_weights.py 의 로그를
읽어 리깅 사슬이 제대로 붙었는지 본다. 세 지표 모두 기존 RUNBOOK 5-2·5-3·5-4 의
확인 포인트를 그대로 옮긴 것이다 — 사람이 눈으로 보던 수치를 게이트로 만든다.

  python gate_g2r.py --params ~/data/06_rig/<샘플>/aligned_params.json --out <폴더>
  python gate_g2r.py --params ... --joint-dist 0.0293 --fallback-pct 3.67 --out <폴더>
  python gate_g2r.py --params ... --transferred <transferred_params.json> --out <폴더>

--transferred 를 주면 폴백 분포(fallback_detail)를 읽어 **폴백 총량과 무관하게**
분포를 판정한다. 위험 분류면 총량이 경고선 아래여도 경고한다. 같은 파일의 rig_check
(본→메쉬 거리 · 지배 정점 · 좌우 교차 배정)로 ①②③ 도 판정한다.

관절거리와 폴백률은 별도 파일로 남지 않아 인자로 받는다 (create_smpl_armature.py·
transfer_weights.py 가 로그로만 찍는다 — 구조화 출력이 필요하다는 것이 이 게이트를
쓰면서 드러난 숙제다).

출력: <out>/gate_g2r.json (gate_s2 와 같은 스키마).
"""
import argparse
import json
import os
import sys

# ── 임계값과 근거 ────────────────────────────────────────────────────────────
# 스케일 판정 — 2026-10-13 에 다시 짰다.
#   종전에는 "정렬 스케일이 0.55~0.65 안" 하나였다 (SMPL 표준 신장과 TRELLIS 정규화 크기의
#   비라는 구조 상수 — zombie1 계열 5회가 0.588~0.5914). 그런데 정렬 스케일은
#   **메쉬 높이 ÷ SMPL 자세 높이**이고(align_smpl_to_trellis.py), 그 범위는 두 가지를 말없이
#   가정한다: 메쉬가 키로 정규화됐다(가장 긴 변 = 키), SMPL 이 똑바로 서 있다. 키프레임의
#   자세가 그 가정을 깨면 리그가 멀쩡해도 불합격이 난다.
#
#                          스케일  SMPL 자세높이  SMPL 최장변  T포즈 키  정규화 일관성  자세높이÷T포즈
#     기존 10건*           0.557~0.620  1.61~1.80   = 높이     1.76~1.80   0.995~1.001    0.913~1.000
#     walker f49 (팔 위로)   0.504       1.984       = 높이     1.797       1.000          1.104
#     dog f134 (팔 수평)     0.527       1.759       1.829(폭)  1.846       0.964          0.953
#     * zombie1 3종 · char_shuffle f60 · f6 · walker f138 · f18 · f26 · walker_apose · stalker_apose
#
#   f49 는 든 팔이 SMPL 자세 높이를 키웠고, dog 는 가장 긴 변이 폭이라 메쉬 높이가 1 보다 작게
#   정규화됐다. 둘 다 옛 규칙에서 불합격이었다 (외형 전용 영상은 팔을 벌린 자세를 일부러
#   쓰므로 이 경우는 되풀이된다). 그래서 자세와 무관한 두 판정으로 나눴다.
#
# TPOSE_H_MIN/MAX = 1.5 / 2.0
#   SMPL T포즈 키(평균 betas). WHAM 의 체형 추정이 틀어지면 벗어난다. 실측 1.763~1.846.
# NORM_MIN/MAX = 0.90 / 1.05   "정규화 일관성"
#   (메쉬 높이 ÷ 메쉬 최장변) ÷ (SMPL 자세 높이 ÷ SMPL 최장변). TRELLIS 는 가장 긴 변을 1 로
#   맞추므로, 메쉬와 SMPL 의 모양이 같으면 이 값은 1 이다. 부유 지오메트리가 메쉬를 부풀리거나
#   메쉬가 잘리면 벗어난다. **잠정이다 — 팔을 수평으로 벌린 표본이 dog 1건(0.964)뿐이다.**
#   그 0.964 는 메쉬의 손이 SMPL 의 손보다 길어서 나온 값이다.
# POSE_H_MIN/MAX = 0.93 / 1.03   경고만 한다
#   SMPL 자세 높이 ÷ T포즈 키. 키프레임에서 몸이 얼마나 접히거나 뻗었는가. f49(팔을 머리 위로)
#   1.104, f60(숙임) 0.913 — 둘 다 나쁜 키프레임이었다. **표본 2건 기준 잠정.**
#   G1a 의 시선 항은 뒤로 젖힌 고개를 못 잡는다(WHAM 이 작게 추정한다 — f49 에서 25.8° 로
#   통과했고 얼굴이 소실됐다). 이 경고는 그 사각을 **간접으로** 보완하는 그물이다: 고개를
#   젖히는 자세는 대개 몸을 뻗거나 팔을 드는 자세와 같이 온다. 직접 재는 것은 아니다.
# IOU_MIN = 0.5
#   실측 0.717 / 0.743 / 0.760 / 0.797. 0.5 는 RUNBOOK 이 쓰던 값 그대로다.
#   2세대는 열린 자락 탓 1세대보다 낮게 나오는 것이 정상이다.
# JOINT_DIST_MAX = 0.2
#   실측 0.028 / 0.0292 / 0.0293 로 임계값과 7배 차이가 난다. 이 값은 좌표계
#   판정이 틀렸을 때를 잡기 위한 것이다 — 틀린 후보는 2.6~4.1 로 두 자릿수
#   차이가 나므로 0.2 면 충분하다.
# FALLBACK_WARN_PCT = 8.0
#   직선거리 폴백은 천으로 떨어진 부위에 웨이트가 건너뛸 수 있어 낮을수록 좋다.
#
# ── 확장 후보 3지표 (2026-10-01 실측, W5 게이트 작업일에 임계 확정) ──────────
#   char_shuffle 이 **현 게이트를 전부 통과하고도 품질 불합격**이었다 (폴백 3.708%,
#   무배정 0%, IoU 0.9762 로 PASS). 아래 셋은 그 결함을 전부 잡아낸다.
#
#   ① 본→메쉬 최근접 거리의 좌우 비대칭
#      L_Hand 0.0852 vs R_Hand 0.0123 (7배). 왼손 본이 메쉬 밖에 있었다.
#      9/22 에 등록한 "관절-TRELLIS 표면 거리" 후보의 실측이 이것이다.
#      토르소 본은 몸 안쪽이라 거리가 먼 게 정상이므로 **좌우 대칭 쌍으로** 본다.
#   ② 좌우 교차 배정률
#      L_Ankle 정점의 38.3% 가 오른쪽 몸에 있었다 (R_Ankle 은 0.2%). 다리가 융합된
#      메쉬에서 Data Transfer 가 다리 사이를 건너뛴 결과다.
#   ③ 지배 정점이 0 인 본
#      L_Hand·L_Wrist 가 0 이었다. 그 본이 회전해도 따라올 지오메트리가 없다.
#
#   셋 다 계산이 싸고 판별력이 분명하다. 임계는 표본을 더 모아 정한다.
#
# ── ①②③ 게이트 코드화 (2026-10-09 구현) ────────────────────────────────────
#   원자료는 transfer_weights.py 의 rig_check 가 재서 transferred_params.json 에 남긴다.
#   5샘플 실측 (tests/fixtures/g2r_rig_check.json 에 전수 보관):
#
#                        ① 말단 본 최대 거리     ② 최대 교차        ③ 지배 0 본        육안
#     char_shuffle f60   0.0852 L_Hand · 0.0642 L_Wrist   28.3% R_Knee · 13.1% L_Ankle   L_Wrist · L_Hand   불합격
#     char_shuffle f6    0.0096                 1.4%               없음 (최소 0.262%)   합격
#     zombie1 1024       0.0239                 4.2%               없음 (최소 0.386%)   합격
#     zombie1 512        0.0172                 6.7%               없음 (최소 0.269%)   합격
#     zombie1 1세대      0.0632 R_Hand          26.1% R_Knee       R_Hand             합격(아래 참조)
#
#   **지표 정의가 10/1 첫 측정과 두 군데 다르다.**
#   ① 은 **말단 8본(손목·손·발목·발)의 절댓값**만 본다. 10/1 에는 "좌우 비대칭 배수"
#      로 적었는데 배수는 못 쓴다 — 합격한 f6 도 배수는 6~8배이고 절댓값이 전부 0.01
#      이하일 뿐이다. 말단으로 한정하는 이유는 몸통·엉덩이·무릎 본이 원래 몸 안쪽에
#      있어서다. 합격 샘플에서도 Hip 0.05~0.07, Spine2 0.07~0.09 가 나온다.
#   ② 는 **좌우 본 쌍의 이등분면** 기준이다. 10/1 의 "L_Ankle 38.3%" 는 몸 정중선을
#      수직면(x=0)으로 잡은 값인데, 그 정의는 기울어 선 자세에서 틀린다 — zombie1 은
#      상체가 기울어 R_Collar 가 70% 로 나왔다(결함이 아니다). 이등분면으로는 f60 이
#      L_Ankle 13.1% · R_Knee 28.3% 다.
#
#   임계 (잠정 — 표본 5건, 불합격 실물은 f60 하나. 표본이 쌓이면 재보정한다):
#     DISTAL_DIST_MAX = 0.03   합격 최대 0.0239 / f60 0.0642·0.0852. 여유 넉넉.
#     CROSS_MAX_PCT   = 10.0   **합격 최대 6.7% / 불합격 13.1% 사이 — 여유가 얇다.**
#                              재보정 1순위. 지배 정점이 CROSS_MIN_VERTS(100) 미만인
#                              본은 비율이 조각 하나에 휘둘려 보지 않는다.
#     DOM_MIN_PCT     = 0.01   지배 정점이 전체의 이 비율(%) 미만이면 "따라올 정점이
#                              없다" 로 본다. 합격 최소 0.262% / f60 은 0.
#
#   **판정 수위.** 불합격은 **같은 본에서 ①과 ③이 함께** 걸릴 때만이다 — 본이 메쉬
#   밖에 있고 따라올 정점도 없으면, 그 본이 움직일 때 주변 조각이 다른 본을 따라간다.
#   f60 의 L_Wrist 가 그 경우다. 하나만 걸리면 경고다. ② 는 단독으로는 항상 경고다
#   (여유가 얇아 불합격을 낼 근거가 약하다).
#
#   **불합격 대상에서 손(Hand)은 뺀다 — FAIL_BONES.** zombie1 1세대가 R_Hand 에서 ①③ 이
#   함께 걸리는데, 렌더로 확인하니 손 메쉬는 온전하고 SMPL 의 손 본만 메쉬 옆 허공에
#   있다(메쉬의 손은 아래로 늘어졌고 SMPL 의 손은 팔 방향으로 뻗었다). 손 정점은 손목을
#   따라간다. 그런데 **WHAM 은 손 관절을 거의 움직이지 않는다** — 5편에서 손 관절 회전
#   범위가 1.3~6.0° 이고 손목은 12.7~35.3° 다. 손목이 정점을 쥐고 있으면 손 본이 비어
#   있어도 동작에 차이가 없다. f60 은 **손목까지** 비어 있어서(L_Wrist·L_Hand) 손목
#   회전이 통째로 사라졌다. 그래서 불합격은 WHAM 이 실제로 움직이는 관절(손목·발목·발)
#   에서만 내고, 손에서 걸리면 경고로 둔다.
#   **이 면제의 전제는 모션 소스가 WHAM 이라는 것이다.** WHAM 은 손 관절을 거의 구동하지
#   않는다(실측 1.3~6.0°). 손 관절을 움직이는 모션 소스 — AMASS 같은 외부 SMPL 모션 —
#   를 들여오면 손 본이 비어 있는 것이 그대로 결함이 되므로 **이 면제를 재검토한다.**
#
#   **① 은 2단이다 — 0.03 넘으면 경고, 0.05 넘으면 그것만으로 불합격 (2026-10-12).**
#     DISTAL_DIST_MAX  = 0.03   경고. 말단 8본(손목·손·발목·발)
#     DISTAL_DIST_FAIL = 0.05   불합격. 손목·발목·발만 (손은 위 면제대로 경고)
#   출처: 합격 최대 0.0239 (zombie1 1024) / 불합격 f60 0.0642 (왼손목). 그 사이에 파일럿
#   f138 의 왼손 0.0254 가 있는데, 이것은 부위 제약으로 고쳐져 합격했다.
#   (경위 — 이 조건은 부위 제약을 구현하다 f60 이 PASS 로 빠지는 것을 보고 먼저 넣은 뒤
#   승인받았다. 승인된 규칙은 "①∧③ 같은 본" 뿐이었다.)
#   10/12 에 웨이트 전이에 부위 제약(transfer_weights.part_constraint)이 들어가면서 필요해졌다.
#   제약은 팔 메쉬 안의 오배정 조각을 팔 본으로 되돌리는데, 그러면 f60 의 왼손목이 정점
#   3,445개를 되찾아 ③ 이 풀리고 **①∧③ 불합격이 사라진다.** 그런데 f60 은 여전히 쓸 수 없는
#   메쉬다 — 손목 본이 메쉬에서 0.064 떨어져 있어 회전축이 어긋나 있고 다리는 붙어 있다.
#   웨이트가 제 본으로 돌아와도 **본이 제자리에 없으면** 고쳐진 것이 아니다. 그래서 거리만으로
#   불합격을 낸다. 제약이 게이트를 무르게 만드는 것을 막는 장치다.
#
#   **판정은 부위 제약을 거친 뒤의 값으로 한다.** rig_check 는 제약 다음에 잰다. 따라서 ⑤ 에
#   남는 것은 "제약으로도 못 고친 것" — 메쉬가 실제로 붙은 경우(파일럿 f18 737)다.
#
#   ④ 는 아래대로 독립 경고다. 수위를 올리는 데 쓰지 않고, 불합격 사유에 "사라진
#   정점이 어디로 갔는지" 의 근거로 인용한다.
#
# ── ⑤ 떨어져 있어야 할 부위를 잇는 엣지 (2026-10-12 구현, 경고) ─────────────
#   10/11 파일럿 walker_walk_02 가 **①②③ 을 전부 무경고로 통과하고 육안 불합격**이었다.
#   팔을 벌리면 손과 허벅지 사이가 판자처럼 늘어났다. 손 정점이 허벅지 본을 받았거나
#   (f138 — WHAM 팔 자세와 메쉬 팔이 어긋남) 허벅지 정점이 손 본을 받은(f18 — 손이
#   허벅지 가까이 있어 번짐) 것이다. 어느 쪽이든 **메쉬 엣지 양끝을 서로 이웃하지 않는
#   부위의 본이 지배**한다. rig_check 의 limb_edges 가 그 엣지를 센다.
#
#                          팔–다리   팔–하부몸통   좌다리–우다리   육안
#     char_shuffle f60        249         84         1,825       불합격
#     walker_walk_02 f138     532         29             0       불합격
#     walker_walk_02 f18    1,260        368             0       불합격
#     char_shuffle f6           0          0             0       합격
#     zombie1 1024              0          0           130       합격
#     zombie1 512               0          0           151       합격
#     zombie1 1세대             0          0            14       합격
#
#   **2026-10-12 재보정 — 팔에 위팔(Shoulder)을 넣었다.** 위 표는 팔을 팔꿈치 아래로만 볼 때의
#   값이다. walker f138 의 위팔–Spine1 엣지 961개가 그 정의 밖이라 ⑤ 가 0 으로 기록됐고,
#   roar_02 에서 팔을 들자 그 엣지가 막처럼 늘어났다. 위팔을 넣은 뒤의 값(전이 제약 적용 후):
#
#                          팔–다리 + 팔–하부몸통   육안
#     walker_walk_02 f18          1,768           불합격
#     walker_walk_02 f138         1,181           팔을 크게 들지 않는 동작만 합격 (roar 불합격)
#     char_shuffle f60              533           불합격
#     walker_apose f188             343           기각 (외형)
#     stalker_apose f188            198           잠정 v1
#     zombie1 1024                   45           합격
#     zombie1 512                    16           합격
#     zombie1 1세대                   3           합격
#     char_shuffle f6 · f26 · dog     0           합격 · 실험
#
#   경고선을 20 → 100 으로 올렸다. 합격 최대 45(어깨 둘레에 Spine2 가 조금 닿는 정도)와 결함
#   최소 198 의 사이다. 20 으로 두면 합격 샘플 zombie1 1024 가 걸린다. 아래 문단의 "합격 4건이
#   전부 0" 은 옛 정의에서의 서술이다.
#
#     LIMB_EDGES_MAX = 20 (옛 정의)    팔–다리 + 팔–하부몸통 엣지 수. **합격 4건이 전부 0** 이고
#                            불합격 최소가 333(f60) 이라 사이가 넓다. 0 이 아니라 20 인
#                            것은 경계 한두 군데의 우연한 접촉을 흘려보내기 위해서다.
#   좌다리–우다리는 기록만 한다 — 걷는 자세의 zombie1 이 130~151 이라 f60(1,825)과 사이는
#   넓지만 표본이 얇고, 다리 융합은 이미 ② 가 본다.
#
#   **경고로 시작한다.** 표본 7건에서 완벽히 갈리지만 불합격 3건이 두 영상에서 나왔다.
#   ① 과 달리 **손 본이 메쉬에 잘 붙어 있어도 걸린다** — f18 은 ① 이 가장 좋았는데
#   (0.004) 결과가 가장 나빴다. ① 을 조여서는 이 결함을 못 잡는다.
#   실측 1.49%(512) / 3.67%(1024) 이고 둘 다 포즈 시험을 통과했다. 상한의 근거가
#   약해 불합격이 아니라 경고로 둔다 — 8%는 1024 실측의 두 배를 조금 넘는 값이다.
#
# ── ④ 폴백 분포 판정 — 상시 평가 (2026-10-07 구현) ──────────────────────────
#   폴백 총량은 품질을 가르지 못한다. 표본 둘이 정반대로 나왔다 —
#
#                         폴백      사지 본 비율   소스거리 p90   육안
#     char_shuffle f60    3.708%    47.53%         0.0606         불합격 (10/1)
#     char_shuffle f6     8.921%     1.84%         0.0229         합격   (10/6)
#     (f6 은 1536_cascade)
#
#   총량으로는 f6 이 2.4배 나쁜데 결과는 반대다. 가르는 것은 **어느 본으로,
#   얼마나 멀리서** 붙었느냐다. f6 의 폴백은 58.9% 가 Head, 27.2% 가 Collar 로
#   간다 — 머리카락 UV 섬과 어깨 장비가 강체 본에 붙은 것이라 움직여도 티가
#   나지 않는다. f60 은 L_Elbow 한 본으로 26.8% 가 갔다 — 정렬이 어긋나 SMPL
#   에서 멀어진 왼손 메쉬가 통째로 팔꿈치 웨이트를 빌렸다.
#
#   그래서 분포를 **총량과 무관하게 항상** 본다.
#     FB_SRC_P90_MAX  = 0.04    웨이트를 빌려 온 거리의 p90 (정렬 공간, 신장 약 1.0).
#                               합격 최대 0.0336 / 불합격 f60 0.0606 (7샘플). 1차 전이
#                               반경 0.08 의 절반. 넘으면 "위험", 아니면 "무해" 다.
#
#   **사지 본 비율 축은 2026-10-12 에 뺐다.** "사지 본(어깨·팔꿈치·…·발)으로 간 폴백
#   비율" 을 10/7 에 두 번째 축으로 넣었는데 닷새 사이 오탐이 세 번 났다.
#     ① zombie1 1024 (합격) 21.0% — 당시 임계 20% 를 넘어 "위험". 10/9 에 35% 로 올림
#     ② zombie1 512  (합격) 26.5% — 같은 날 같은 사유
#     ③ 파일럿 walker_walk_02 (10/11) 100% — 폴백 9,793정점이 전부 무릎의 찢어진
#        청바지 조각이었다. 조각이 **제 다리 본에 가까이**(p90 0.0286) 붙은 것이라 무해한데
#        "사지 본으로 갔다" 는 이유만으로 걸렸다
#   이 축은 "어느 본으로 갔나" 만 보고 **그 조각이 원래 그 사지의 것인가** 를 보지 않는다.
#   팔다리에 장식이 달린 캐릭터는 늘 걸린다. 거리(p90)는 그 구분을 한다 — 먼 데서 빌려
#   왔으면 남의 웨이트다. f60 은 거리만으로도 걸린다(0.0606). limb_pct 는 기록만 남긴다.
#   떨어져 있어야 할 부위가 이어진 것은 ⑤ 가 직접 잰다.
#     FB_MIN_VERTS    = 1000    잡음 가드. 폴백 정점이 이보다 적으면 분류하지 않는다.
#                               p90 과 본별 비율은 표본이 작으면 조각 한두 개에
#                               휘둘린다. 1000 은 70만 정점 메쉬의 약 0.14% 로,
#                               지금까지의 실측 최솟값(zombie1 512 의 1.49%)보다
#                               한 자릿수 아래다 — 실제 샘플은 걸리지 않고, 폴백이
#                               사실상 없는 메쉬만 건너뛴다.
#
#   **발동 조건을 총량에 걸지 않는다.** 처음에는 "폴백이 8% 경고선을 넘을 때만
#   2차 판정" 으로 짰는데, 그러면 이 메모의 전제("총량은 품질을 가르지 못한다")와
#   모순된다 — f60 은 3.708% 라 판정이 돌지 않아 위험 분류인데도 무경고 PASS 였다.
#   그래서 상시 평가로 바꿨다. 결과는 넷이다.
#
#       총량 ≤ 8%, 분포 무해   경고 없음
#       총량 ≤ 8%, 분포 위험   경고 ("총량은 낮지만 분포가 위험")      ← f60
#       총량 > 8%, 분포 무해   경고 ("총량은 높지만 분포 무해")        ← f6+1536
#       총량 > 8%, 분포 위험   경고 (가장 강한 문구)
#
#   **"위험" 은 경고이지 불합격이 아니다.** 표본이 2건이고 위험 표본은 f60 하나라
#   FAIL 로 올릴 근거가 없다. 표본이 쌓이면 격상을 검토한다.
#
#   높이 밴드(머리/상체/…)는 판정에 쓰지 않는다. 팔이 몸통과 같은 높이에 있어
#   f60 의 "상체 64.6%" 와 f6 의 "상체 29.6%" 가 뜻하는 바가 전혀 다르다.
TPOSE_H_MIN, TPOSE_H_MAX = 1.5, 2.0
NORM_MIN, NORM_MAX = 0.90, 1.05
POSE_H_MIN, POSE_H_MAX = 0.93, 1.03
IOU_MIN = 0.5
JOINT_DIST_MAX = 0.2
FALLBACK_WARN_PCT = 8.0
UNASSIGNED_MAX = 0
FB_SRC_P90_MAX = 0.04
FB_MIN_VERTS = 1000
DISTAL = ("Wrist", "Hand", "Ankle", "Foot")
DISTAL_DIST_MAX = 0.03
DISTAL_DIST_FAIL = 0.05                      # 손목·발목·발이 이보다 멀면 그것만으로 불합격
CROSS_MAX_PCT = 10.0
CROSS_MIN_VERTS = 100
DOM_MIN_PCT = 0.01
FAIL_BONES = ("Wrist", "Ankle", "Foot")      # ①∧③ 이 불합격이 되는 본. Hand 는 경고 (위 메모)
LIMB_EDGES_MAX = 100                         # ⑤ 팔–다리 + 팔–하부몸통 엣지 (2026-10-12 재보정, 위 메모)

THRESHOLD_STATUS = "스케일은 5회 검증, 나머지는 잠정(표본 4건). 폴백 분포·리깅 지표 임계는 표본 7건(불합격 실물 3건, 영상 2편). 재보정: 신규 10건 누적 시 / PASS 후 하류 실패 발생 시"


def classify_fallback(detail):
    """폴백 분포를 "benign"(무해) / "risky"(위험) 로 가른다.

    돌려주는 값은 (분류, 사유 목록) 이다. 자료가 없으면 분류가 None, 폴백 정점이
    FB_MIN_VERTS 에 못 미치면 "too_few"(잡음 가드) 다. 근거와 임계의 출처는 위 ④ 메모.
    """
    if not detail or detail.get("verts") is None:
        return None, []
    if detail["verts"] < FB_MIN_VERTS:
        return "too_few", []
    p90 = (detail.get("src_dist") or {}).get("p90")
    if p90 is None:
        return None, []
    why = [f"소스거리 p90 {p90} > {FB_SRC_P90_MAX}"] if p90 > FB_SRC_P90_MAX else []
    return ("risky" if why else "benign"), why


def check_rig(rc, detail=None):
    """①②③ 을 판정한다. (불합격 사유, 경고, 기록) 을 돌려준다. 근거는 위 메모."""
    if not rc:
        return [], [], None
    n = rc.get("vertices") or 0
    dist, dom, cross = rc.get("bone_dist", {}), rc.get("dominant", {}), rc.get("cross", {})
    far = {b: d for b, d in dist.items() if b.endswith(DISTAL) and d > DISTAL_DIST_MAX}
    empty = [b for b, c in dom.items() if n and 100.0 * c / n < DOM_MIN_PCT]
    crossed = {b: round(100.0 * c / dom[b], 1) for b, c in cross.items()
               if dom.get(b, 0) >= CROSS_MIN_VERTS and 100.0 * c / dom[b] > CROSS_MAX_PCT}
    both = [b for b in far if b in empty]
    fatal = [b for b in both if b.endswith(FAIL_BONES)]
    reasons, warnings = [], []
    if fatal:
        msg = (f"{' · '.join(fatal)}: 본이 메쉬 밖에 있고(거리 "
               f"{' · '.join(str(far[b]) for b in fatal)} > {DISTAL_DIST_MAX}) 따라올 정점이 없다"
               f"(지배 정점 0) — 이 본이 움직여도 메쉬가 따라오지 않는다")
        # 사라진 정점이 어디로 갔는지 — ④ 폴백 분포를 근거로 붙인다 (수위에는 쓰지 않는다)
        by = (detail or {}).get("by_bone") or {}
        side = {b[:2] for b in fatal}
        limb = [(b, c) for b, c in by.items()
                if b[:2] in side and b.endswith(("Shoulder", "Elbow", "Hip", "Knee"))]
        if limb:
            b, c = max(limb, key=lambda kv: kv[1])
            msg += f". 폴백 {c:,}정점이 {b} 로 갔다"
        reasons.append(msg)
    # 본이 메쉬에서 한참 밖 — 지배 정점이 있든 없든 불합격 (위 메모)
    way_off = [b for b in far if b.endswith(FAIL_BONES) and far[b] > DISTAL_DIST_FAIL and b not in fatal]
    if way_off:
        reasons.append(
            f"{' · '.join(way_off)}: 본이 메쉬에서 너무 멀다(거리 "
            f"{' · '.join(str(far[b]) for b in way_off)} > {DISTAL_DIST_FAIL}) — 정렬이 어긋났다. "
            f"웨이트가 붙어 있어도 회전축이 제자리에 없다")
        fatal = fatal + way_off
    rest_both = [b for b in both if b not in fatal]
    if rest_both:
        warnings.append(
            f"{' · '.join(rest_both)}: 본이 메쉬 밖이고(거리 "
            f"{' · '.join(str(far[b]) for b in rest_both)}) 지배 정점이 없다 — 손 본은 WHAM 이 "
            f"거의 움직이지 않아 불합격으로 보지 않는다. 손목이 정점을 쥐고 있는지 확인할 것")
    only_far = [b for b in far if b not in both and b not in fatal]
    if only_far:
        warnings.append("말단 본이 메쉬에서 멀다: "
                        + ", ".join(f"{b} {far[b]}" for b in only_far)
                        + f" (> {DISTAL_DIST_MAX}) — 정렬을 확인할 것")
    only_empty = [b for b in empty if b not in both]
    if only_empty:
        warnings.append(f"지배 정점이 없는 본: {', '.join(only_empty)} — 그 본이 회전해도 "
                        f"따라올 지오메트리가 없다")
    if crossed:
        warnings.append("좌우 교차 배정: "
                        + ", ".join(f"{b} {p}%" for b, p in sorted(crossed.items(), key=lambda kv: -kv[1]))
                        + f" (> {CROSS_MAX_PCT}%) — 다리·팔이 붙은 메쉬에서 웨이트가 반대편으로 넘어갔다")
    le = rc.get("limb_edges")                 # 구버전 JSON 에는 없다 — 없으면 ⑤ 를 보지 않는다
    limb_n = None
    if le:
        limb_n = le.get("arm_leg", 0) + le.get("arm_lowtorso", 0)
        if limb_n > LIMB_EDGES_MAX:
            top = ", ".join(f"{k.replace('|', '–')} {c}" for k, c in list(le.get("top", {}).items())[:3])
            warnings.append(
                f"떨어져 있어야 할 부위가 이어져 있다: 팔–다리 {le.get('arm_leg', 0)} + "
                f"팔–하부몸통 {le.get('arm_lowtorso', 0)} 엣지 (> {LIMB_EDGES_MAX}) — {top}. "
                f"팔을 움직이면 그 사이가 늘어난다. 재생 영상에서 손·허벅지를 확인할 것")
    flags = {"far": far, "empty": empty, "crossed": crossed, "fatal": fatal,
             "limb_edges": limb_n}
    return reasons, warnings, flags


def judge(m):
    reasons, warnings = [], []
    sc = m.get("scale_check") or {}
    if m.get("scale") is None:
        reasons.append("aligned_params.json 에 scale 이 없다")
    if sc.get("error"):
        # 판정에 쓸 크기를 얻지 못했다. 옛 범위로 조용히 돌아가지 않는다.
        reasons.append(f"스케일 판정 불가 — {sc['error']}")
    else:
        th, nr, pr = sc.get("tpose_height"), sc.get("norm_ratio"), sc.get("pose_ratio")
        if th is None or nr is None:
            reasons.append("스케일 판정 불가 — SMPL · 메쉬 크기가 주어지지 않았다")
        else:
            if not (TPOSE_H_MIN <= th <= TPOSE_H_MAX):
                reasons.append(f"SMPL T포즈 키 {th} 가 {TPOSE_H_MIN}-{TPOSE_H_MAX} 밖이다 — "
                               f"WHAM 체형 추정 이상 신호")
            if not (NORM_MIN <= nr <= NORM_MAX):
                reasons.append(f"정규화 일관성 {nr} 이 {NORM_MIN}-{NORM_MAX} 밖이다 — 메쉬와 SMPL 의 "
                               f"모양(높이 ÷ 최장변)이 다르다. 메쉬 잘림 · 부유 지오메트리 신호")
            if pr is not None and not (POSE_H_MIN <= pr <= POSE_H_MAX):
                warnings.append(f"키프레임 자세 높이가 T포즈 키의 {pr} 배다 (범위 {POSE_H_MIN}-{POSE_H_MAX} 밖) "
                                f"— 몸을 숙였거나 팔을 머리 위로 든 자세다. 얼굴이 보이는지 "
                                f"키프레임을 확인할 것")
    iou = m.get("bbox_iou")
    if iou is None:
        reasons.append("aligned_params.json 에 bbox_iou 가 없다")
    elif iou < IOU_MIN:
        reasons.append(f"bbox IoU {iou} < {IOU_MIN} — 정렬이 어긋났다")
    jd = m.get("joint_dist")
    if jd is None:
        warnings.append("관절-메쉬 거리가 주어지지 않아 좌표계 판정을 확인하지 못했다")
    elif jd > JOINT_DIST_MAX:
        reasons.append(f"관절-메쉬 거리 {jd} > {JOINT_DIST_MAX} — 좌표계 판정이 틀렸을 수 있다")
    ua = m.get("unassigned_pct")
    if ua is not None and ua > UNASSIGNED_MAX:
        reasons.append(f"웨이트 무배정 {ua}% > {UNASSIGNED_MAX}% — 전이가 끝나지 않았다")
    detail = m.get("fallback_detail")
    r2, w2, flags = check_rig(m.get("rig_check"), detail)
    reasons += r2
    warnings += w2
    m["rig_flags"] = flags
    fb = m.get("fallback_pct")
    cls, why = classify_fallback(detail)
    over = fb is not None and fb > FALLBACK_WARN_PCT
    m["fallback_check"] = {"class": cls, "why": why, "over_warn_pct": over}
    if fb is None:
        warnings.append("직선거리 폴백률이 주어지지 않았다")
    else:
        size = (f"직선거리 폴백 {fb}% 가 {FALLBACK_WARN_PCT}% 를 넘는다" if over
                else f"직선거리 폴백 {fb}% 는 {FALLBACK_WARN_PCT}% 아래다")
        if cls == "risky":
            # 총량과 무관하게 경고한다 — 총량은 품질을 가르지 못한다 (④ 메모).
            warnings.append(
                f"{size} — 분포 위험: {'; '.join(why)}. "
                f"먼 데서 빌린 웨이트가 붙었다 — 포즈 시험 필수")
        elif over and cls == "benign":
            top = ", ".join(f"{b} {c}" for b, c in list(detail.get("by_bone", {}).items())[:3])
            warnings.append(
                f"{size} — 분포 무해: 소스거리 p90 {detail['src_dist']['p90']} "
                f"(상위 본: {top})")
        elif over:
            # 분포 자료가 없거나(None) 정점이 너무 적다(too_few). 조용히 넘기지 않는다.
            warnings.append(f"{size} — 분포를 판정하지 못했다({cls}). 포즈 시험으로 확인할 것")
    return ("FAIL" if reasons else "PASS"), reasons, warnings


def obj_extent(path):
    """OBJ 의 정점 범위 [x, y, z]. 못 읽으면 예외."""
    lo, hi = [float("inf")] * 3, [float("-inf")] * 3
    n = 0
    with open(path) as f:
        for line in f:
            if line.startswith("v "):
                c = [float(x) for x in line.split()[1:4]]
                lo = [min(a, b) for a, b in zip(lo, c)]
                hi = [max(a, b) for a, b in zip(hi, c)]
                n += 1
    if n == 0:
        raise RuntimeError(f"정점이 없다: {path}")
    return [h - l for l, h in zip(lo, hi)]


def scale_check(p):
    """aligned_params → 스케일 판정에 쓸 크기들. 얻지 못하면 {"error": 사유}.

    새 aligned_params.json 에는 trellis_extent · smpl_extent 가 있다 (정렬할 때 잰 값, z 가
    높이). 2026-10-13 이전 것에는 없어서 SMPL OBJ 에서 직접 재고(카메라 좌표라 y 가 높이,
    rot_x 가 ±90 일 때만), 메쉬는 "가장 긴 변 = 1" 로 정규화됐다고 보고 스케일에서 되짚는다.
    """
    scale, smpl = p.get("scale"), p.get("smpl")
    if scale is None or not smpl:
        return {"error": "aligned_params.json 에 scale 또는 smpl 경로가 없다"}
    smpl = os.path.expanduser(smpl)
    tpose = os.path.join(os.path.dirname(smpl), "smpl_tpose.obj")
    try:
        tpose_h = obj_extent(tpose)[1]                      # OBJ 는 y 가 높이
        if p.get("smpl_extent") and p.get("trellis_extent"):
            se, te = p["smpl_extent"], p["trellis_extent"]
            s_h, s_max, t_h, t_max, src = se[2], max(se), te[2], max(te), "aligned_params"
        else:
            if abs(abs(p.get("rot_x", 0)) - 90) > 1e-6:
                return {"error": f"옛 aligned_params (크기 기록 없음)인데 rot_x 가 {p.get('rot_x')} 라 "
                                 f"SMPL 의 높이 축을 알 수 없다 — 5-2 를 다시 돌릴 것"}
            se = obj_extent(smpl)
            s_h, s_max = se[1], max(se)
            t_h, t_max, src = scale * s_h, 1.0, "obj (메쉬 최장변 = 1 가정)"
    except (OSError, RuntimeError, ValueError) as e:
        return {"error": f"SMPL 메쉬를 읽지 못했다: {e}"}
    return {"tpose_height": round(tpose_h, 4), "smpl_pose_height": round(s_h, 4),
            "smpl_max_extent": round(s_max, 4), "trellis_height": round(t_h, 4),
            "trellis_max_extent": round(t_max, 4),
            "norm_ratio": round((t_h / t_max) / (s_h / s_max), 4),
            "pose_ratio": round(s_h / tpose_h, 4), "source": src}


def parse_args():
    ap = argparse.ArgumentParser(description="G2r 게이트 — SMPL 정렬·리깅 판정")
    ap.add_argument("--params", required=True, help="aligned_params.json 경로")
    ap.add_argument("--out", required=True, help="판정 결과를 쓸 폴더")
    ap.add_argument("--name", default=None, help="샘플 이름. 기본값: --out 폴더 이름")
    ap.add_argument("--joint-dist", type=float, default=None,
                    help="create_smpl_armature.py 가 찍은 평균 관절-메쉬 거리")
    ap.add_argument("--fallback-pct", type=float, default=None,
                    help="transfer_weights.py 의 직선거리 폴백 비율(%%)")
    ap.add_argument("--unassigned-pct", type=float, default=0.0,
                    help="웨이트 무배정 비율(%%). 기본 0")
    ap.add_argument("--transferred", default=None,
                    help="transferred_params.json 경로. 폴백 분포(fallback_detail)를 읽어 "
                         "총량과 무관하게 판정한다. --fallback-pct 를 생략하면 "
                         "폴백률도 여기서 읽는다")
    return ap.parse_args()


def main():
    a = parse_args()
    out = os.path.expanduser(a.out)
    os.makedirs(out, exist_ok=True)
    name = a.name or os.path.basename(os.path.normpath(out))
    p = json.load(open(os.path.expanduser(a.params)))
    t = json.load(open(os.path.expanduser(a.transferred))) if a.transferred else {}
    metrics = {
        "scale": p.get("scale"),
        "scale_check": scale_check(p),
        "bbox_iou": p.get("bbox_iou"),
        "joint_dist": a.joint_dist,
        "fallback_pct": a.fallback_pct if a.fallback_pct is not None else t.get("fallback_pct"),
        "unassigned_pct": a.unassigned_pct,
        "rot_x": p.get("rot_x"),
        "fallback_detail": t.get("fallback_detail"),
        "rig_check": t.get("rig_check"),
    }
    verdict, reasons, warnings = judge(metrics)
    result = {
        "gate": "G2r", "version": 1, "name": name, "verdict": verdict,
        "reasons": reasons, "warnings": warnings, "metrics": metrics,
        "thresholds": {
            "tpose_h_min": TPOSE_H_MIN, "tpose_h_max": TPOSE_H_MAX,
            "norm_min": NORM_MIN, "norm_max": NORM_MAX,
            "pose_h_min": POSE_H_MIN, "pose_h_max": POSE_H_MAX, "iou_min": IOU_MIN,
            "joint_dist_max": JOINT_DIST_MAX, "fallback_warn_pct": FALLBACK_WARN_PCT,
            "unassigned_max": UNASSIGNED_MAX,
            "fb_src_p90_max": FB_SRC_P90_MAX,
            "fb_min_verts": FB_MIN_VERTS,
            "distal_dist_max": DISTAL_DIST_MAX, "distal_dist_fail": DISTAL_DIST_FAIL,
            "cross_max_pct": CROSS_MAX_PCT,
            "cross_min_verts": CROSS_MIN_VERTS, "dom_min_pct": DOM_MIN_PCT,
            "fail_bones": list(FAIL_BONES), "limb_edges_max": LIMB_EDGES_MAX,
            "status": THRESHOLD_STATUS,
        },
        "source": {"type": "aligned_params", "path": a.params},
    }
    path = os.path.join(out, "gate_g2r.json")
    with open(path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    mark = "✅" if verdict == "PASS" else "❌"
    sc = metrics["scale_check"]
    print(f"{mark} [{verdict}] {name}  스케일 {metrics['scale']} (T포즈 키 {sc.get('tpose_height')} · "
          f"정규화 {sc.get('norm_ratio')} · 자세 {sc.get('pose_ratio')})  IoU {metrics['bbox_iou']}  "
          f"관절거리 {metrics['joint_dist']}  폴백 {metrics['fallback_pct']}%")
    for r in reasons:
        print(f"    사유: {r}")
    for w in warnings:
        print(f"    주의: {w}")
    print(f"    → {path}")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
