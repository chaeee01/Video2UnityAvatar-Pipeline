"""
GLB → FBX 배치 변환 (Blender headless).

씬을 비우고 GLB를 임포트한 뒤 FBX로 내보냅니다. 텍스처는 FBX에 임베드하므로
(path_mode=COPY) 결과 파일 하나만 옮기면 유니티에서 그대로 열립니다.

  /Applications/Blender4.5.app/Contents/MacOS/Blender --background \
      --python glb_to_fbx.py -- \
      --glb ~/Downloads/char1.glb \
      --outdir ~/Desktop/char_fbx

--glb 는 여러 개를 한 번에 줄 수도 있습니다 (파일마다 씬을 새로 비웁니다).
출력 이름은 입력 파일명을 따릅니다 (char1.glb → char1.fbx).
"""
import argparse
import os
import sys

import bpy


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True, nargs="+", help="입력 GLB/GLTF (여러 개 가능)")
    ap.add_argument("--outdir", required=True, help="FBX 출력 디렉터리")
    return ap.parse_args(argv)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def convert(glb_path, outdir):
    clear_scene()
    bpy.ops.import_scene.gltf(filepath=glb_path)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"메쉬를 찾지 못함: {glb_path}")
    verts = sum(len(o.data.vertices) for o in meshes)

    name = os.path.splitext(os.path.basename(glb_path))[0] + ".fbx"
    out = os.path.join(outdir, name)
    bpy.ops.export_scene.fbx(
        filepath=out,
        use_selection=False,
        path_mode="COPY",        # 텍스처를 FBX 안에 임베드
        embed_textures=True,
        add_leaf_bones=False,    # 유니티에서 불필요한 말단 본 방지
        mesh_smooth_type="FACE",
    )
    size = os.path.getsize(out)
    print(f"  메쉬 {len(meshes)}개 / 정점 {verts:,} → {out} ({size/1e6:.2f} MB)")
    return out, size


def main():
    a = parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    for i, glb in enumerate(a.glb, 1):
        print(f"[{i}/{len(a.glb)}] {glb}")
        convert(os.path.expanduser(glb), os.path.expanduser(a.outdir))
    print("완료")


if __name__ == "__main__":
    main()
