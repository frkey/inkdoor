#!/bin/sh
# Shared settings and helpers for the inkdoor scripts on the Kindle.
DIR=/mnt/us/inkdoor
# Strip Windows line endings so config.sh can be edited on any computer
tr -d "\r" < "$DIR/config.sh" > /tmp/inkdoor-config.sh
. /tmp/inkdoor-config.sh
LOG="$DIR/log.txt"
PIDFILE=/tmp/inkdoor.pid
IMG=/tmp/inkdoor.png

# Messages. The Kindle's built-in screen font has no accents, so keep them ASCII.
case "$LANGUAGE" in
  pt*)
    MSG_NO_CONNECTION="sem conexao com o PC"
    MSG_ADDRESS="Endereco"
    MSG_WIFI="Conectando ao Wi-Fi..."
    MSG_WIFI_FAILED="FALHOU: o Wi-Fi nao conectou"
    MSG_OK="OK! Imagem baixada. Pode usar 'inkdoor - start display'."
    MSG_DOWNLOAD_FAILED="FALHOU: nao consegui baixar a imagem."
    MSG_HINT="Confira o IP em inkdoor/config.sh e se o 'inkdoor serve' esta rodando no PC."
    ;;
  *)
    MSG_NO_CONNECTION="cannot reach the computer"
    MSG_ADDRESS="Address"
    MSG_WIFI="Connecting to Wi-Fi..."
    MSG_WIFI_FAILED="FAILED: Wi-Fi did not connect"
    MSG_OK="OK! Image downloaded. You can now use 'inkdoor - start display'."
    MSG_DOWNLOAD_FAILED="FAILED: could not download the image."
    MSG_HINT="Check the IP in inkdoor/config.sh and that 'inkdoor serve' is running on the computer."
    ;;
esac

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

download() {
  rm -f "$IMG.tmp"
  if command -v curl >/dev/null 2>&1; then
    curl -s -f -m 30 -o "$IMG.tmp" "$URL"
  else
    wget -q -T 30 -O "$IMG.tmp" "$URL"
  fi
  # only replace the screen with a real PNG
  if [ -s "$IMG.tmp" ] && head -c 4 "$IMG.tmp" | grep -q PNG; then
    mv "$IMG.tmp" "$IMG"
    return 0
  fi
  return 1
}

ensure_wifi() {
  lipc-set-prop com.lab126.wifid enable 1 >/dev/null 2>&1
  i=0
  while [ $i -lt 30 ]; do
    [ "$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null)" = "CONNECTED" ] && return 0
    sleep 2
    i=$((i + 1))
  done
  return 1
}
