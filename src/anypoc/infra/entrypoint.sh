#!/bin/bash
set -e

TARGET_USER="${ANYPOC_RUNTIME_USER:-playground}"
TARGET_HOME="/home/${TARGET_USER}"
VENV_BIN="/opt/anypoc/.venv/bin"
UV_BIN="/opt/uv"
NODE_BIN="/opt/node/bin"
LOCAL_BIN="${TARGET_HOME}/.local/bin"
RUSTUP_HOME="/opt/rustup"

log() {
  echo "[entrypoint] $(date '+%H:%M:%S') $*"
}

refresh_target_home() {
  TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
}

ensure_runtime_dirs() {
  local runtime_group
  runtime_group="$(id -gn "$TARGET_USER")"

  mkdir -p \
    "$TARGET_HOME/.anypoc/projects" \
    "$TARGET_HOME/.cache/anypoc" \
    "$TARGET_HOME/.local/bin" \
    "$TARGET_HOME/.cargo/bin"
  chown "$TARGET_USER:$runtime_group" \
    "$TARGET_HOME" \
    "$TARGET_HOME/.anypoc" \
    "$TARGET_HOME/.anypoc/projects" \
    "$TARGET_HOME/.cache" \
    "$TARGET_HOME/.cache/anypoc" \
    "$TARGET_HOME/.local" \
    "$TARGET_HOME/.local/bin" \
    "$TARGET_HOME/.cargo" \
    "$TARGET_HOME/.cargo/bin"
}

configure_runtime_user() {
  if [ "$(id -u)" -ne 0 ]; then
    refresh_target_home
    return
  fi

  if [ -z "$HOST_UID" ] || [ -z "$HOST_GID" ]; then
    log "HOST_UID/HOST_GID not set; using image defaults for ${TARGET_USER}"
    refresh_target_home
    ensure_runtime_dirs
    return
  fi

  local current_uid current_gid existing_group existing_user
  current_uid="$(id -u "$TARGET_USER")"
  current_gid="$(id -g "$TARGET_USER")"

  if [ "$HOST_GID" != "$current_gid" ]; then
    existing_group="$(getent group "$HOST_GID" | cut -d: -f1 || true)"
    if [ -n "$existing_group" ] && [ "$existing_group" != "$TARGET_USER" ]; then
      log "Using existing group ${existing_group} (GID=${HOST_GID}) for ${TARGET_USER}"
      usermod -g "$HOST_GID" "$TARGET_USER"
    else
      log "Remapping ${TARGET_USER} group to GID=${HOST_GID}"
      groupmod -o -g "$HOST_GID" "$TARGET_USER"
    fi
  fi

  if [ "$HOST_UID" != "$current_uid" ]; then
    existing_user="$(getent passwd "$HOST_UID" | cut -d: -f1 || true)"
    if [ -n "$existing_user" ] && [ "$existing_user" != "$TARGET_USER" ]; then
      log "UID ${HOST_UID} already belongs to ${existing_user}; leaving ${TARGET_USER} at UID=${current_uid}"
    else
      log "Remapping ${TARGET_USER} to UID=${HOST_UID}"
      usermod -o -u "$HOST_UID" "$TARGET_USER"
    fi
  fi

  refresh_target_home
  ensure_runtime_dirs
}

setup_auth() {
  if [ -f /tmp/caw_auth/setup-container.sh ]; then
    log "Running caw auth setup-container.sh..."
    /tmp/caw_auth/setup-container.sh /tmp/caw_auth "$TARGET_HOME" "$TARGET_USER"
    log "caw auth setup complete"
  fi
}

run_startup_hooks() {
  if [ -d /docker-entrypoint.d ]; then
    log "Running project-specific startup scripts..."
    for f in /docker-entrypoint.d/*.sh; do
      if [ -f "$f" ] && [ -x "$f" ]; then
        log "  Running $f"
        . "$f"
      fi
    done
    log "Startup scripts completed"
  fi
}

exec_as_target_user() {
  if command -v runuser >/dev/null 2>&1; then
    exec runuser -u "$TARGET_USER" -- env \
      HOME="$TARGET_HOME" \
      USER="$TARGET_USER" \
      LOGNAME="$TARGET_USER" \
      CARGO_HOME="$CARGO_HOME" \
      RUSTUP_HOME="$RUSTUP_HOME" \
      PATH="$PATH" \
      "$@"
  fi

  local quoted_env quoted_cmd
  printf -v quoted_env \
    'HOME=%q USER=%q LOGNAME=%q CARGO_HOME=%q RUSTUP_HOME=%q PATH=%q' \
    "$TARGET_HOME" \
    "$TARGET_USER" \
    "$TARGET_USER" \
    "$CARGO_HOME" \
    "$RUSTUP_HOME" \
    "$PATH"
  printf -v quoted_cmd '%q ' "$@"
  exec su -s /bin/bash "$TARGET_USER" -c "export $quoted_env; exec $quoted_cmd"
}

run_as_target_user() {
  export HOME="$TARGET_HOME"
  export USER="$TARGET_USER"
  export LOGNAME="$TARGET_USER"
  export CARGO_HOME="${TARGET_HOME}/.cargo"
  export RUSTUP_HOME
  export PATH="$VENV_BIN:$UV_BIN:$NODE_BIN:$LOCAL_BIN:/usr/local/bin:/usr/bin:/bin"

  if [ "$(id -u)" -ne 0 ]; then
    if [ "$#" -eq 0 ]; then
      exec /bin/bash -i
    fi
    exec "$@"
  fi

  if [ "$#" -eq 0 ]; then
    log "Starting interactive bash session as ${TARGET_USER}"
    exec_as_target_user /bin/bash -i
  fi

  log "Running command as ${TARGET_USER}: $*"
  exec_as_target_user "$@"
}

log "Starting entrypoint script..."
configure_runtime_user
setup_auth
run_startup_hooks
run_as_target_user "$@"
