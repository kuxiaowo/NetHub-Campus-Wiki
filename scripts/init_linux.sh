#!/usr/bin/env bash

# NetHub Campus Wiki Linux initializer.
# Creates/updates the Conda environment, initializes an empty database and
# installs two systemd --user services without requiring root privileges.

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
ENV_FILE="$PROJECT_DIR/.env"
ENV_EXAMPLE="$PROJECT_DIR/.env.example"
SYSTEMD_USER_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
ADMIN_USERNAME=""
ADMIN_DISPLAY_NAME=""

log() {
  printf '[init] %s\n' "$*"
}

die() {
  printf '[init] 错误：%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
用法：scripts/init_linux.sh [--admin USERNAME] [--display-name NAME]

  --admin USERNAME       初始化数据库后交互式创建首个管理员
  --display-name NAME    管理员显示姓名（需与 --admin 一起使用）
  -h, --help             显示帮助
EOF
}

while (($#)); do
  case "$1" in
    --admin)
      (($# >= 2)) || die "--admin 缺少昵称"
      ADMIN_USERNAME="$2"
      shift 2
      ;;
    --display-name)
      (($# >= 2)) || die "--display-name 缺少姓名"
      ADMIN_DISPLAY_NAME="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "未知参数：$1"
      ;;
  esac
done

if [[ -n "$ADMIN_DISPLAY_NAME" && -z "$ADMIN_USERNAME" ]]; then
  die "--display-name 必须与 --admin 一起使用"
fi

[[ "$(uname -s)" == "Linux" ]] || die "此脚本只支持 Linux"
[[ -f "$ENV_EXAMPLE" ]] || die "缺少 $ENV_EXAMPLE"
command -v conda >/dev/null 2>&1 || die "未找到 conda，请先安装 Miniconda 或 Anaconda"
command -v systemctl >/dev/null 2>&1 || die "未找到 systemctl；此部署方式需要 systemd"
command -v systemd-analyze >/dev/null 2>&1 || die "未找到 systemd-analyze"

CONDA_EXE="$(command -v conda)"

if [[ ! -f "$ENV_FILE" ]]; then
  cp -- "$ENV_EXAMPLE" "$ENV_FILE"
  log "已从 .env.example 创建 .env"
else
  # Preserve existing values and append newly introduced settings with defaults.
  while IFS= read -r example_line || [[ -n "$example_line" ]]; do
    if [[ "$example_line" =~ ^([A-Z][A-Z0-9_]*)= ]]; then
      key="${BASH_REMATCH[1]}"
      if ! grep -qE "^[[:space:]]*${key}=" "$ENV_FILE"; then
        printf '%s\n' "$example_line" >>"$ENV_FILE"
        log "已向 .env 补充 $key"
      fi
    fi
  done <"$ENV_EXAMPLE"
fi
chmod 600 "$ENV_FILE"

read_env() {
  local key="$1"
  local fallback="${2-}"
  local value
  value="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
  value="${value%$'\r'}"
  value="${value#\"}"
  value="${value%\"}"
  value="${value#\'}"
  value="${value%\'}"
  printf '%s' "${value:-$fallback}"
}

CONDA_ENV_NAME="$(read_env CONDA_ENV_NAME nethub-campus-wiki)"
PYTHON_VERSION="$(read_env PYTHON_VERSION 3.12)"
SERVICE_PREFIX="$(read_env SYSTEMD_SERVICE_PREFIX nethub-campus-wiki)"

[[ "$CONDA_ENV_NAME" =~ ^[A-Za-z0-9_.-]+$ ]] || die "CONDA_ENV_NAME 含有不支持的字符"
[[ "$PYTHON_VERSION" =~ ^[0-9]+([.][0-9]+){1,2}$ ]] || die "PYTHON_VERSION 格式不正确"
[[ "$SERVICE_PREFIX" =~ ^[A-Za-z0-9_.@-]+$ ]] || die "SYSTEMD_SERVICE_PREFIX 含有不支持的字符"

if ! "$CONDA_EXE" run -n "$CONDA_ENV_NAME" python --version >/dev/null 2>&1; then
  log "创建 Conda 环境 $CONDA_ENV_NAME（Python $PYTHON_VERSION）"
  "$CONDA_EXE" create --yes --name "$CONDA_ENV_NAME" "python=$PYTHON_VERSION" pip
else
  log "复用 Conda 环境 $CONDA_ENV_NAME"
fi

log "安装/更新 Python 依赖"
"$CONDA_EXE" run -n "$CONDA_ENV_NAME" python -m pip install --requirement "$PROJECT_DIR/requirements.txt"

if [[ -z "$(read_env AUTH_SECRET_KEY)" ]]; then
  AUTH_SECRET_KEY="$("$CONDA_EXE" run --no-capture-output -n "$CONDA_ENV_NAME" python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  ENV_FILE="$ENV_FILE" AUTH_SECRET_KEY="$AUTH_SECRET_KEY" \
    "$CONDA_EXE" run --no-capture-output -n "$CONDA_ENV_NAME" python - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["ENV_FILE"])
secret = os.environ["AUTH_SECRET_KEY"]
lines = path.read_text(encoding="utf-8").splitlines()
updated = []
replaced = False
for line in lines:
    if line.lstrip().startswith("AUTH_SECRET_KEY="):
        updated.append(f"AUTH_SECRET_KEY={secret}")
        replaced = True
    else:
        updated.append(line)
if not replaced:
    updated.append(f"AUTH_SECRET_KEY={secret}")
path.write_text("\n".join(updated) + "\n", encoding="utf-8")
PY
  log "已生成独立的 AUTH_SECRET_KEY"
fi

log "创建数据库结构并执行迁移（不会插入示例业务数据）"
(
  cd -- "$PROJECT_DIR"
  "$CONDA_EXE" run -n "$CONDA_ENV_NAME" python -c \
    'from backend.database import get_db_connection; connection = get_db_connection(); connection.close()'
)

mkdir -p -- "$SYSTEMD_USER_DIR"
API_UNIT="${SERVICE_PREFIX}-api.service"
FRONTEND_UNIT="${SERVICE_PREFIX}-frontend.service"

cat >"$SYSTEMD_USER_DIR/$API_UNIT" <<EOF
[Unit]
Description=NetHub Campus Wiki API
After=network.target

[Service]
Type=simple
WorkingDirectory="$PROJECT_DIR"
EnvironmentFile="$ENV_FILE"
ExecStart="$CONDA_EXE" run --no-capture-output -n $CONDA_ENV_NAME python -m backend.main
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

cat >"$SYSTEMD_USER_DIR/$FRONTEND_UNIT" <<EOF
[Unit]
Description=NetHub Campus Wiki frontend
After=network.target $API_UNIT
Wants=$API_UNIT

[Service]
Type=simple
WorkingDirectory="$PROJECT_DIR"
EnvironmentFile="$ENV_FILE"
ExecStart="$CONDA_EXE" run --no-capture-output -n $CONDA_ENV_NAME python frontend_server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

log "校验并启用 systemd 用户服务"
systemd-analyze --user verify "$SYSTEMD_USER_DIR/$API_UNIT" "$SYSTEMD_USER_DIR/$FRONTEND_UNIT"
systemctl --user daemon-reload
systemctl --user enable --now "$API_UNIT" "$FRONTEND_UNIT"

if [[ -n "$ADMIN_USERNAME" ]]; then
  admin_args=(--username "$ADMIN_USERNAME")
  if [[ -n "$ADMIN_DISPLAY_NAME" ]]; then
    admin_args+=(--display-name "$ADMIN_DISPLAY_NAME")
  fi
  (
    cd -- "$PROJECT_DIR"
    "$CONDA_EXE" run --no-capture-output -n "$CONDA_ENV_NAME" \
      python -m backend.bootstrap_admin "${admin_args[@]}"
  )
fi

log "初始化完成"
log "API 服务：$API_UNIT"
log "前端服务：$FRONTEND_UNIT"
log "查看日志：journalctl --user -u $API_UNIT -u $FRONTEND_UNIT -f"
if command -v loginctl >/dev/null 2>&1; then
  linger="$(loginctl show-user "$USER" --property=Linger --value 2>/dev/null || true)"
  if [[ "$linger" != "yes" ]]; then
    log "提示：当前未启用 linger，注销后用户服务会停止；如需开机运行，请由管理员执行：loginctl enable-linger $USER"
  fi
fi
