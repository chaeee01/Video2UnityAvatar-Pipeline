import bpy
print('=== 이미지 목록 ===')
for img in bpy.data.images:
    print(img.name, img.size[:], img.source, img.filepath, img.packed_file is not None)
print('=== 머티리얼 노드 ===')
for mat in bpy.data.materials:
    if not mat.use_nodes:
        continue
    for n in mat.node_tree.nodes:
        if n.type == 'TEX_IMAGE':
            print(mat.name, '->', n.image.name if n.image else None)
