#!/bin/bash
# 이미지 v2 시작 스크립트 (2026-11-06) — RunPod 식: PUBLIC_KEY 가 있으면 authorized_keys 에 넣고 sshd 를 띄운 뒤 대기,
# 없으면 sshd 없이 대기한다. 어느 쪽이든 컨테이너는 살아 있다 — 템플릿에 Start Command 가 필요 없다(v1 은 `sleep infinity` 필요).
# 호스트 키는 이미지에 굽지 않고 첫 시작 때 만든다. SSH 세션에는 컨테이너 환경 변수(PATH · MAMBA_ROOT_PREFIX · RUNPOD_* ·
# PIPELINE_*)가 상속되지 않으므로 /etc/rp_environment 에 적어 로그인 셸이 읽게 한다.
set -e
{
  env | grep -E '^(PATH|MAMBA_ROOT_PREFIX|PYTHONUNBUFFERED|PIPELINE_[A-Z_]*|RUNPOD_[A-Z_]*|HF_HOME|CUDA_VISIBLE_DEVICES|NVIDIA_[A-Z_]*)=' \
    | while IFS='=' read -r k v; do printf 'export %s=%q\n' "$k" "$v"; done
} > /etc/rp_environment
# 대화형 셸: .bashrc 맨 앞에 넣는다 — Ubuntu 기본 .bashrc 는 비대화형이면 첫머리에서 return 한다.
for f in /root/.bashrc /root/.profile; do
  touch "$f"; grep -q rp_environment "$f" || sed -i '1i [ -f /etc/rp_environment ] \&\& . /etc/rp_environment' "$f"
done
if [ -n "${PUBLIC_KEY:-}" ]; then
  mkdir -p /root/.ssh && chmod 700 /root/.ssh
  # 비대화형 SSH 명령(ssh host 'cmd' · rsync)에도 환경이 들어가게 — sshd PermitUserEnvironment
  env | grep -E '^(PATH|MAMBA_ROOT_PREFIX|PYTHONUNBUFFERED|PIPELINE_[A-Z_]*|RUNPOD_[A-Z_]*|HF_HOME|CUDA_VISIBLE_DEVICES|NVIDIA_[A-Z_]*)=' \
    > /root/.ssh/environment; chmod 600 /root/.ssh/environment
  printf '%s\n' "$PUBLIC_KEY" >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
  ssh-keygen -A > /dev/null
  mkdir -p /run/sshd
  /usr/sbin/sshd -o PermitRootLogin=prohibit-password -o PasswordAuthentication=no -o PermitUserEnvironment=yes
  echo "[start] sshd 시작 (PUBLIC_KEY $(printf '%s' "$PUBLIC_KEY" | awk '{print $1}'))"
else
  echo "[start] PUBLIC_KEY 없음 — sshd 없이 대기"
fi
exec sleep infinity
