"""
SMPL 리깅 4단계 마무리: animated.blend -> Unity 반입용 FBX.

메쉬 + SMPL 골격 + 웨이트 + 베이킹된 WHAM 애니메이션을 FBX 로 내보냅니다.
SMPL_body(보조 메쉬)는 내보내기에서 제외합니다 — Unity 에 필요한 건
TRELLIS 좀비뿐입니다.

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background \
      --python export_unity_fbx.py -- \
      --blend ~/data/06_rig/zombie_sample1/animated.blend \
      --out ~/data/07_unity/zombie_sample1/zombie_wham.fbx

**캐릭터 FBX 1개 + 클립 FBX 여러 개 (2026-10-12~).** 동작마다 메쉬를 넣으면 클립당 53MB 이고
Unity 에서 임포트 설정이 반복된다. 메쉬는 한 번만, 동작은 골격만 내보낸다:

      --blend <리그>/transferred.blend --out walker.fbx --no-anim              # 캐릭터 (메쉬 + 골격)
      --blend <클립>/animated.blend --out walker@walk_02.fbx \
          --armature-only --take-name walk_02                                  # 클립 (골격 + 동작)

Unity 는 `<모델>@<클립>.fbx` 를 그 모델의 애니메이션 파일로 읽는다. 클립 FBX 의 Rig 탭에서
Avatar Definition 을 **Copy From Other Avatar** 로 두고 캐릭터 FBX 의 아바타를 지정한다.
"""
import argparse
import sys

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--blend", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rig-name", default="SMPL_rig")
    ap.add_argument("--smpl-name", default="SMPL_body",
                    help="내보내기에서 제외할 보조 메쉬")
    ap.add_argument("--keep-smpl", action="store_true",
                    help="SMPL_body 도 포함하고 싶으면 지정")
    ap.add_argument("--armature-only", action="store_true",
                    help="메쉬 없이 골격과 동작만 내보낸다 (클립 FBX)")
    ap.add_argument("--no-anim", action="store_true",
                    help="동작 없이 메쉬와 골격만 내보낸다 (캐릭터 FBX)")
    ap.add_argument("--take-name", default=None,
                    help="FBX 테이크(Unity 클립) 이름. 기본은 Blender 씬 이름")
    ap.add_argument("--no-embed-textures", action="store_true",
                    help="텍스처를 FBX 에 넣지 않는다 (텍스처는 PNG 로 따로 납품할 때)")
    return ap.parse_args(argv)


def main():
    a = parse_args()
    bpy.ops.wm.open_mainfile(filepath=a.blend)

    rig = bpy.data.objects.get(a.rig_name)
    if rig is None:
        raise RuntimeError(f"{a.rig_name} 없음")

    # SMPL 보조 메쉬 제거 (역할 종료)
    if not a.keep_smpl:
        smpl = bpy.data.objects.get(a.smpl_name)
        if smpl:
            bpy.data.objects.remove(smpl, do_unlink=True)
            print(f"제외: {a.smpl_name}")

    if a.armature_only and a.no_anim:
        raise RuntimeError("--armature-only 와 --no-anim 을 함께 주면 내보낼 것이 없다")
    if a.no_anim:
        # 캐릭터 FBX 는 rest 자세로 내보낸다. 액션이 걸려 있으면 그 프레임의 자세로 구워진다.
        if rig.animation_data:
            rig.animation_data.action = None
        for pb in rig.pose.bones:
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.location = (0, 0, 0)
    if a.take_name:
        # 액션 하나를 씬 범위로 굽는 설정이라 테이크 이름이 씬 이름을 따른다.
        bpy.context.scene.name = a.take_name

    # 아마추어 + 그 자식 메쉬만 선택 (클립 FBX 는 아마추어만)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    if not a.armature_only:
        for child in rig.children_recursive:
            child.select_set(True)
    bpy.context.view_layer.objects.active = rig
    n_sel = len(bpy.context.selected_objects)
    print(f"내보낼 오브젝트 {n_sel}개")

    bpy.ops.export_scene.fbx(
        filepath=a.out,
        use_selection=True,
        # --- 골격 ---
        add_leaf_bones=False,          # Unity 에 불필요한 말단 본 방지
        armature_nodetype="NULL",
        use_armature_deform_only=True,
        # --- 애니메이션 ---
        bake_anim=not a.no_anim,
        bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False,
        bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True,
        # --- 좌표/스케일 (Blender Z-up -> Unity Y-up) ---
        apply_scale_options="FBX_SCALE_ALL",
        axis_forward="-Z",
        axis_up="Y",
        # --- 기타 ---
        path_mode="STRIP" if a.no_embed_textures else "COPY",
        embed_textures=not a.no_embed_textures,
        mesh_smooth_type="FACE",
    )
    print(f"저장: {a.out}")
    print("Unity: 임포트 -> Rig 탭 Generic -> Animation 탭에서 클립 확인 -> 씬 재생")
    print("      Humanoid 로 두면 근육 변환에서 동작이 왜곡된다 (rest 가 T포즈가 아니라서).")
    # T포즈 rest 리그 재생성은 별도 과제 EH-211.


if __name__ == "__main__":
    main()
