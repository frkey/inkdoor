#!/usr/bin/env bash
# Installs or updates inkdoor as a systemd service on Debian 12+ or Ubuntu 22.04+.
#
#   install.sh [--lang en-US|pt-BR] [--timezone Area/City] [--ref BRANCH_OR_TAG]
#
# Run it as root on the machine (or container) that will serve the Kindle image.
# Running it again updates inkdoor and restarts the service. config.toml is never overwritten.
#
# Layout:
#   /opt/inkdoor              code and virtualenv
#   /etc/inkdoor/config.toml  your config (readable by root and the inkdoor user only)
#   /var/lib/inkdoor          rendered image
#   /usr/local/bin/inkdoor    runs inkdoor with that config, e.g. "inkdoor check"
set -euo pipefail

REPO="${INKDOOR_REPO:-https://github.com/frkey/inkdoor.git}"
REF="${INKDOOR_REF:-master}"
LANGUAGE="${INKDOOR_LANG:-}"
TIMEZONE=""
BAD_OPTION=""

APP_DIR=/opt/inkdoor
CONF_DIR=/etc/inkdoor
CONF="$CONF_DIR/config.toml"
STATE_DIR=/var/lib/inkdoor
UNIT=/etc/systemd/system/inkdoor.service
WRAPPER=/usr/local/bin/inkdoor

while [ $# -gt 0 ]; do
  case "$1" in
    --lang) LANGUAGE="${2:-}"; shift 2 || shift ;;
    --timezone) TIMEZONE="${2:-}"; shift 2 || shift ;;
    --ref) REF="${2:-}"; shift 2 || shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) BAD_OPTION="$1"; shift ;;
  esac
done

# Without --lang, follow the system locale
if [ -z "$LANGUAGE" ]; then
  case "${LC_ALL:-${LANG:-}}" in pt*) LANGUAGE="pt-BR" ;; esac
fi

case "$LANGUAGE" in
  pt*)
    MSG_NEED_ROOT="Rode este script como root."
    MSG_NEED_APT="Este instalador funciona só no Debian e no Ubuntu (apt)."
    MSG_NEED_SYSTEMD="O systemd não está rodando; o inkdoor precisa dele para rodar como serviço."
    MSG_BAD_OPTION="Opção desconhecida: %s (veja --help)."
    MSG_BAD_LANG="Idioma desconhecido: %s (use en-US ou pt-BR)."
    MSG_PACKAGES="Instalando pacotes do sistema..."
    MSG_OLD_PYTHON="O inkdoor precisa do Python 3.10 ou mais novo (Debian 12+ ou Ubuntu 22.04+)."
    MSG_DOWNLOAD="Baixando o inkdoor (%s)..."
    MSG_NOT_GIT="%s existe mas não é um clone do git; mova a pasta e rode de novo."
    MSG_PIP="Instalando o pacote Python..."
    MSG_CONFIG_NEW="Criei %s a partir do exemplo."
    MSG_CONFIG_KEPT="Mantive o %s que já existia."
    MSG_NO_TIMEZONE="Não detectei o fuso horário; ajuste timezone em %s."
    MSG_SERVICE="Instalando o serviço do systemd..."
    MSG_NEXT_STEPS="
Próximos passos:
  1. Cole os links das agendas:  nano $CONF
  2. Teste os links:             inkdoor check
  3. Ligue o serviço:            systemctl start inkdoor"
    MSG_RUNNING="
O inkdoor está rodando. No Kindle, em inkdoor/config.sh, use:
  URL=\"%s\""
    MSG_FAILED="O serviço não subiu. Veja: journalctl -u inkdoor -n 50"
    ;;
  *)
    MSG_NEED_ROOT="Run this script as root."
    MSG_NEED_APT="This installer supports Debian and Ubuntu (apt) only."
    MSG_NEED_SYSTEMD="systemd is not running; inkdoor needs it to run as a service."
    MSG_BAD_OPTION="Unknown option: %s (see --help)."
    MSG_BAD_LANG="Unknown language: %s (use en-US or pt-BR)."
    MSG_PACKAGES="Installing system packages..."
    MSG_OLD_PYTHON="inkdoor needs Python 3.10 or newer (Debian 12+ or Ubuntu 22.04+)."
    MSG_DOWNLOAD="Downloading inkdoor (%s)..."
    MSG_NOT_GIT="%s exists but is not a git checkout; move it away and run again."
    MSG_PIP="Installing the Python package..."
    MSG_CONFIG_NEW="Created %s from the example."
    MSG_CONFIG_KEPT="Kept the existing %s."
    MSG_NO_TIMEZONE="Could not detect the time zone; set timezone in %s."
    MSG_SERVICE="Installing the systemd service..."
    MSG_NEXT_STEPS="
Next steps:
  1. Paste your calendar links:  nano $CONF
  2. Test them:                  inkdoor check
  3. Start the service:          systemctl start inkdoor"
    MSG_RUNNING="
inkdoor is running. On the Kindle, in inkdoor/config.sh, use:
  URL=\"%s\""
    MSG_FAILED="The service did not start. See: journalctl -u inkdoor -n 50"
    ;;
esac

# say FORMAT [ARGS...]: print a message; the formats above are trusted
say() {
  local format="$1"
  shift
  # shellcheck disable=SC2059
  printf -- "$format\n" "$@"
}

die() {
  say "$@" >&2
  exit 1
}

[ -z "$BAD_OPTION" ] || die "$MSG_BAD_OPTION" "$BAD_OPTION"
case "$LANGUAGE" in ''|en-US|pt-BR) ;; *) die "$MSG_BAD_LANG" "$LANGUAGE" ;; esac
[ "$(id -u)" -eq 0 ] || die "$MSG_NEED_ROOT"
command -v apt-get >/dev/null || die "$MSG_NEED_APT"
[ -d /run/systemd/system ] || die "$MSG_NEED_SYSTEMD"

say "$MSG_PACKAGES"
export DEBIAN_FRONTEND=noninteractive DEBCONF_NOWARNINGS=yes
apt-get update -qq
apt-get install -y -qq --no-install-recommends python3 python3-venv git ca-certificates >/dev/null
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || die "$MSG_OLD_PYTHON"

say "$MSG_DOWNLOAD" "$REF"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" remote set-url origin "$REPO"
  git -C "$APP_DIR" fetch --quiet --depth 1 origin "$REF"
  git -C "$APP_DIR" checkout --quiet --force FETCH_HEAD
elif [ -e "$APP_DIR" ]; then
  die "$MSG_NOT_GIT" "$APP_DIR"
else
  git clone --quiet --depth 1 --branch "$REF" "$REPO" "$APP_DIR"
fi

say "$MSG_PIP"
[ -x "$APP_DIR/.venv/bin/python" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet --disable-pip-version-check --upgrade "$APP_DIR"

id inkdoor >/dev/null 2>&1 ||
  useradd --system --user-group --home-dir "$STATE_DIR" --no-create-home --shell /usr/sbin/nologin inkdoor
install -d -m 755 -o inkdoor -g inkdoor "$STATE_DIR"
install -d -m 750 -o root -g inkdoor "$CONF_DIR"

NEW_CONFIG=0
if [ -f "$CONF" ]; then
  say "$MSG_CONFIG_KEPT" "$CONF"
else
  NEW_CONFIG=1
  cp "$APP_DIR/config.example.toml" "$CONF"
  if [ -n "$LANGUAGE" ]; then
    sed -i "s|^language = \"[^\"]*\"|language = \"$LANGUAGE\"|" "$CONF"
  fi
  if [ -z "$TIMEZONE" ]; then  # e.g. /usr/share/zoneinfo/America/Sao_Paulo
    TIMEZONE="$(readlink /etc/localtime 2>/dev/null | sed -n 's|^.*/zoneinfo/\(posix/\)\{0,1\}||p')"
  fi
  case "$TIMEZONE" in
    ''|UTC|Etc/UTC|Etc/Universal) say "$MSG_NO_TIMEZONE" "$CONF" ;;
    *) sed -i "s|^timezone = \"[^\"]*\"|timezone = \"$TIMEZONE\"|" "$CONF" ;;
  esac
  say "$MSG_CONFIG_NEW" "$CONF"
fi
chown root:inkdoor "$CONF"
chmod 640 "$CONF"

say "$MSG_SERVICE"
cat > "$WRAPPER" <<'EOF'
#!/bin/sh
# Runs inkdoor with the service's config and output folder (installed by deploy/install.sh)
set -- --config /etc/inkdoor/config.toml --output /var/lib/inkdoor "$@"
if [ "$(id -u)" -eq 0 ]; then
  exec runuser -u inkdoor -- /opt/inkdoor/.venv/bin/inkdoor "$@"
fi
exec /opt/inkdoor/.venv/bin/inkdoor "$@"
EOF
chmod 755 "$WRAPPER"
install -m 644 "$APP_DIR/deploy/inkdoor.service" "$UNIT"
systemctl daemon-reload
systemctl enable --quiet inkdoor

if [ "$NEW_CONFIG" -eq 1 ]; then
  say "$MSG_NEXT_STEPS"
  exit 0
fi

systemctl restart inkdoor
sleep 3
systemctl is-active --quiet inkdoor || die "$MSG_FAILED"
PORT="$(awk -F= '/^\[server\]/ { s = 1; next } /^\[/ { s = 0 }
  s && $1 ~ /^[ \t]*port[ \t]*$/ { sub(/#.*/, "", $2); gsub(/[ \t"]/, "", $2); print $2; exit }' "$CONF")"
IP="$(ip -4 -o address show scope global 2>/dev/null | awk '{ sub(/\/.*/, "", $4); print $4; exit }')"
say "$MSG_RUNNING" "http://${IP:-<ip>}:${PORT:-8000}/kindle.png"
