#!/bin/bash
# 캐릭터 리그에 동작 클립들을 굽고(늘어난 엣지 덤프 + 원본 대조 영상) 한 줄씩 요약한다.
#   OUTDIR=<결과 폴더> bake_character.sh <리그 샘플> x <클립 id ...>     (둘째 인자는 쓰지 않는다)
#   리그 폴더에 rest_pose.json(make_rest_pose.py)이 있어야 한다. 데이터 루트는 $PIPELINE_VOL/data (기본 ~/data).
set -u; RIGN=$1; CH=$2; shift 2
T=$(cd "$(dirname "$0")" && pwd); S=$T/../../scripts; B=${BLENDER:-/Applications/Blender4.5.app/Contents/MacOS/Blender}
D=${PIPELINE_VOL:-$HOME}/data; RIG=$D/06_rig/$RIGN
OUT=${OUTDIR:?OUTDIR 필요}; mkdir -p $OUT/_dump
H=$(python3 -c "import json;print(json.load(open('$RIG/rest_pose.json'))['smpl_height'])")
for c in "$@"; do
  M=$RIG/motions/$c; mkdir -p $M
  P=$D/04_wham/${c}_masked/wham_output_stitched.pkl; [ -f $P ] || P=$D/04_wham/${c}_masked/wham_output.pkl
  python3 $S/convert_wham_npz.py --pkl $P --out $M/wham_pose.npz > $M/conv.log 2>&1 || { echo "FAIL convert $c"; continue; }
  # T포즈 메쉬가 없는 클립(5-1 을 못 돌린 것)은 같은 캐릭터 다른 클립들의 평균 신장을 쓴다 — FALLBACK_H
  if [ -f $D/05_smpl_mesh/$c/smpl_tpose.obj ]; then r=$(python3 -c "
ys=[float(l.split()[2]) for l in open('$D/05_smpl_mesh/$c/smpl_tpose.obj') if l.startswith('v ')];print($H/(max(ys)-min(ys)))"); else r=$(python3 -c "print($H/${FALLBACK_H:?T포즈 메쉬가 없는데 FALLBACK_H 도 없다})"); echo "  ($c: T포즈 메쉬 없음 — 평균 신장 $FALLBACK_H 사용)"; fi
  $B --background --python $S/apply_wham_pose.py -- --blend $RIG/transferred.blend --npz $M/wham_pose.npz --ref-pose $RIG/rest_pose.json --height-ratio $r --action-name $c --out $M/animated.blend > $M/bake.log 2>&1
  [ -f $M/animated.blend ] || { echo "FAIL bake $c"; continue; }
  $B --background --python $T/dump2.py -- $M/animated.blend $OUT/_dump/L_${RIGN}_$c 2 0 > /dev/null 2>&1
  $B --background --python $S/render_playback.py -- --blend $M/animated.blend --out $M/_playback > $M/render.log 2>&1
  V=$(ls $D/00_raw/${c}__*.mp4 $D/00_raw/$(echo $c | sed -E "s/_(mp|s2new)$//")__*.mp4 2>/dev/null | head -1)
  ffmpeg -y -loglevel error -i $V -framerate 24 -i $M/_playback/%04d.png -filter_complex "[0:v]scale=540:960,setsar=1[a];[1:v]scale=540:960,setsar=1[b];[a][b]hstack=inputs=2" -c:v libx264 -pix_fmt yuv420p -crf 18 -an $OUT/${c}_original_vs_rig.mp4 || echo "FAIL ffmpeg $c"
  python3 -c "
import json;J=json.load(open('$OUT/_dump/L_${RIGN}_$c.json'));d=J['long'];f5=max(d,key=lambda f:d[f][0]);print('OK $c 신장비 %.4f | >0.05 %d(f%s) · >0.10 %d · 최장 %.3f'%($r,d[f5][0],f5,max(v[1] for v in d.values()),max(v[2] for v in d.values())),sorted(d[f5][3].items(),key=lambda x:-x[1])[:3] if len(d[f5])>3 else '')"
done
echo BAKEDONE
