#!/bin/bash
# deploy-devastator.sh - gpu-arbiter on devastator, as aschneider. Idempotent.
#   bash deploy-devastator.sh recorder   # root timer: gpu_sample.py every minute (needs sudo -n)
#   bash deploy-devastator.sh arbiter    # user unit on 127.0.0.1:8390, env file, ComfyUI dirs
#   bash deploy-devastator.sh status
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNITS="$SRC/../../systemd-unit-files"
APP="$HOME/.local/share/gpu-arbiter/app"
ENVF="$HOME/.config/gpu-arbiter/arbiter.env"
case "${1:-}" in
  recorder)
    sudo -n install -D -m 0755 "$SRC/gpu_sample.py" /usr/local/lib/gpu-arbiter/gpu_sample.py
    sudo -n install -m 0644 "$UNITS/gpu-sample.service" "$UNITS/gpu-sample.timer" /etc/systemd/system/
    sudo -n systemctl daemon-reload && sudo -n systemctl enable --now gpu-sample.timer
    ;;
  arbiter)
    mkdir -p "$APP" "$(dirname "$ENVF")" "$HOME/.config/systemd/user" /docker/comfyui/{input,output,models}
    install -m 0644 "$SRC/arbiter.py" "$SRC/comfy.py" "$APP/"
    install -m 0644 "$SRC/extra_model_paths.yaml" /docker/comfyui/extra_model_paths.yaml
    [ -f "$ENVF" ] || install -m 0600 "$SRC/arbiter.env.example" "$ENVF"
    install -m 0644 "$UNITS/gpu-arbiter.service" "$HOME/.config/systemd/user/gpu-arbiter.service"
    systemctl --user daemon-reload && systemctl --user enable gpu-arbiter.service >/dev/null && systemctl --user restart gpu-arbiter.service
    sleep 1; curl -sf http://127.0.0.1:8390/status
    ;;
  status)
    curl -s http://127.0.0.1:8390/status; echo; cat "$HOME/.local/state/gpu-arbiter/mode"
    python3 /usr/local/lib/gpu-arbiter/gpu_sample.py --summary
    ;;
  *) sed -n 2,5p "$0"; exit 2 ;;
esac
