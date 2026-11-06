#!/bin/bash
# TrialBox 5090-like simulation box: two vLLM servers capped to ~28 GB total of the 96 GB card, behind nginx :80.
exec > >(tee -a /var/log/tb-startup.log /dev/ttyS0) 2>&1
set -x
KEY=$(curl -s -H Metadata-Flavor:Google http://metadata.google.internal/computeMetadata/v1/instance/attributes/tb-key)  # random API key set at VM creation
VLLM=vllm/vllm-openai:v0.32.0
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
if ! docker info 2>/dev/null | grep -qi nvidia; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update && apt-get install -y nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker && systemctl restart docker
fi
nvidia-smi
mkdir -p /models
docker rm -f judge verifier front 2>/dev/null
docker network create tb 2>/dev/null
# 32 GB card emulation: 0.60*32/96=0.20 judge, 0.28*32/96=0.093 verifier (deploy/docker-compose.rtx5090.yml)
docker run -d --name judge --network tb --gpus all --ipc host -v /models:/root/.cache/huggingface --restart unless-stopped $VLLM \
  --model nvidia/Gemma-4-26B-A4B-NVFP4 --served-model-name local/gemma-4-26b-a4b-nvfp4 \
  --max-model-len 8192 --max-num-seqs 4 --enforce-eager --gpu-memory-utilization 0.22 --api-key "$KEY" \
  --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}'
for i in $(seq 1 120); do
  docker exec judge python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" 2>/dev/null && break
  docker ps -a --filter name=judge --format '{{.Status}}' | grep -q Exited && break
  [ $((i % 8)) = 0 ] && docker logs judge 2>&1 | grep -aE 'Error|error|memory|Memory|KV cache|Started server' | tail -6 | sed 's/^/TBJ /'
  sleep 15
done
docker logs judge 2>&1 | grep -aE 'Error|error|memory|Memory|KV cache|Started' | tail -15 | sed 's/^/TBJ /'
docker run -d --name verifier --network tb --gpus all --ipc host -v /models:/root/.cache/huggingface --restart unless-stopped $VLLM \
  --model cyankiwi/Qwen3.5-9B-AWQ-4bit --served-model-name local/qwen3.5-9b-awq \
  --max-model-len 8192 --max-num-seqs 4 --enforce-eager --gpu-memory-utilization 0.105 --api-key "$KEY" \
  --limit-mm-per-prompt '{"image":0,"video":0}' --default-chat-template-kwargs '{"enable_thinking": false}'
cat > /root/nginx.conf <<'NG'
events {}
http { server { listen 80; client_max_body_size 10m; proxy_read_timeout 600s;
  location /judge/    { proxy_pass http://judge:8000/; }
  location /verifier/ { proxy_pass http://verifier:8000/; } } }
NG
docker run -d --name front --network tb -p 80:80 -v /root/nginx.conf:/etc/nginx/nginx.conf:ro --restart unless-stopped nginx:1.27-alpine
for i in $(seq 1 80); do docker exec verifier python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" 2>/dev/null && break; [ $((i % 8)) = 0 ] && docker logs verifier 2>&1 | grep -aE 'Error|memory|KV cache' | tail -4 | sed 's/^/TBV /'; sleep 15; done
docker logs verifier 2>&1 | grep -aE 'Error|error|memory|Memory|KV cache|Started' | tail -15 | sed 's/^/TBV /'
nvidia-smi --query-gpu=memory.used,memory.total --format=csv
echo STARTUP-DONE
