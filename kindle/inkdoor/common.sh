#!/bin/sh
# Shared settings and helpers for the inkdoor scripts on the Kindle.
DIR=/mnt/us/inkdoor
# Strip Windows line endings so config.sh can be edited on any computer
tr -d "\r" < "$DIR/config.sh" > /tmp/inkdoor-config.sh
. /tmp/inkdoor-config.sh
LOG="$DIR/log.txt"
LOCKDIR=/tmp/inkdoor.lock      # holds the PID of the running loop
IMG=/tmp/inkdoor.png
HEADERS=/tmp/inkdoor.headers   # the last download's response headers
LIGHT_SAVED="$DIR/light-saved" # the frontlight level from before the night (survives a reboot)
# White-light brightness files of the models where lipc level 0 still glows: Paperwhite 1, then
# Paperwhite 2, Voyage and Paperwhite 3. A fixed list, never a glob: warm-light models turn off at
# lipc level 0, and their amber nodes in /sys/class/backlight must not be touched.
LIGHT_NODES="/sys/devices/system/fl_tps6116x/fl_tps6116x0/fl_intensity /sys/class/backlight/max77696-bl/brightness"

# Guard against bad values in config.sh
case "$INTERVAL" in ''|*[!0-9]*) INTERVAL=300 ;; esac
case "$FULL_REFRESH_EVERY" in ''|*[!0-9]*|0) FULL_REFRESH_EVERY=6 ;; esac
[ "$INTERVAL" -ge 30 ] || INTERVAL=30

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
    MSG_KPM_MISSING="O KPM nao esta instalado neste Kindle."
    MSG_KPM_BAD_URL="A URL em inkdoor/config.sh precisa ser http://.../kindle.png"
    MSG_KPM_OK="OK! Para atualizar depois: ;kpm update e ;kpm upgrade na busca."
    MSG_KPM_FAILED="FALHOU: o KPM nao conseguiu instalar o inkdoor."
    MSG_KPM_HINT="Confira a URL em inkdoor/config.sh e se o admin do servidor esta ligado."
    ;;
  *)
    MSG_NO_CONNECTION="cannot reach the computer"
    MSG_ADDRESS="Address"
    MSG_WIFI="Connecting to Wi-Fi..."
    MSG_WIFI_FAILED="FAILED: Wi-Fi did not connect"
    MSG_OK="OK! Image downloaded. You can now use 'inkdoor - start display'."
    MSG_DOWNLOAD_FAILED="FAILED: could not download the image."
    MSG_HINT="Check the IP in inkdoor/config.sh and that 'inkdoor serve' is running on the computer."
    MSG_KPM_MISSING="KPM is not installed on this Kindle."
    MSG_KPM_BAD_URL="URL in inkdoor/config.sh must be http://.../kindle.png"
    MSG_KPM_OK="OK! To update later: ;kpm update, then ;kpm upgrade in the search bar."
    MSG_KPM_FAILED="FAILED: KPM could not install inkdoor."
    MSG_KPM_HINT="Check URL in inkdoor/config.sh and that the server's admin is on."
    ;;
esac

log() {
  # keep the log small: it lives on the Kindle's user storage
  if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 102400 ]; then
    tail -n 200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
  fi
  echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"
}

# Takes the single-instance lock. mkdir is atomic, so two quick taps cannot start two loops.
# A lock left by a loop that died (without a reboot) is taken over.
take_lock() {
  if mkdir "$LOCKDIR" 2>/dev/null; then
    echo $$ > "$LOCKDIR/pid"
    return 0
  fi
  if kill -0 "$(cat "$LOCKDIR/pid" 2>/dev/null)" 2>/dev/null; then
    return 1
  fi
  echo $$ > "$LOCKDIR/pid"
  return 0
}

is_running() {
  [ -d "$LOCKDIR" ] && kill -0 "$(cat "$LOCKDIR/pid" 2>/dev/null)" 2>/dev/null
}

download() {
  rm -f "$IMG.tmp" "$HEADERS"
  if command -v curl >/dev/null 2>&1; then
    curl -s -f -m 30 -D "$HEADERS" -o "$IMG.tmp" "$URL"
  else
    # -S prints the response headers (on stderr) instead of the progress
    wget -S -T 30 -O "$IMG.tmp" "$URL" 2> "$HEADERS"
  fi
  # only replace the screen with a real PNG
  if [ -s "$IMG.tmp" ] && head -c 4 "$IMG.tmp" | grep -q PNG; then
    mv "$IMG.tmp" "$IMG"
    return 0
  fi
  return 1
}

# Seconds to wait before the next download: what the server asked for (X-Inkdoor-Next: it renders
# again when a meeting starts or ends), at least 30 and at most INTERVAL. An older server sends
# nothing, and the wait is INTERVAL.
next_wait() {
  n="$(sed -n 's/^[[:space:]]*[Xx]-[Ii]nkdoor-[Nn]ext:[[:space:]]*\([0-9][0-9]*\).*/\1/p' \
    "$HEADERS" 2>/dev/null | tail -n 1)"
  case "$n" in
    ''|??????*) echo "$INTERVAL"; return ;;    # nothing, or too long to be a real wait
  esac
  [ "$n" -ge 30 ] || n=30
  [ "$n" -le "$INTERVAL" ] || n=$INTERVAL
  echo "$n"
}

# Follows the server's X-Inkdoor-Light (a night schedule): "off" saves the frontlight level once and
# turns the light off, "on" brings the saved level back. Anything else, or an older server that
# sends nothing, leaves the light alone. POSIX sh has no "local": every variable starts with light_
# so the loop's own variables are safe, and every path returns 0.
apply_light() {
  light_value="$(sed -n 's/^[[:space:]]*[Xx]-[Ii]nkdoor-[Ll]ight:[[:space:]]*\([a-z]*\).*/\1/p' \
    "$HEADERS" 2>/dev/null | tail -n 1)"
  case "$light_value" in
    off) light_turn_off ;;
    on) light_restore ;;
  esac
  return 0
}

light_turn_off() {
  light_level="$(lipc-get-prop com.lab126.powerd flIntensity 2>/dev/null)"
  case "$light_level" in ''|*[!0-9]*) light_level="" ;; esac
  light_saved="$(cat "$LIGHT_SAVED" 2>/dev/null)"
  case "$light_saved" in
    ''|*[!0-9]*)
      # nothing saved yet, or a file that is not a level (a write cut short): save it now. A light
      # turned off without a saved level could never be brought back: leave it alone
      [ -n "$light_level" ] || return 0
      if ! echo "$light_level" > "$LIGHT_SAVED"; then
        rm -f "$LIGHT_SAVED"
        return 0
      fi
      log "light off (saved level $light_level)"
      ;;
  esac
  if [ "$light_level" != "0" ]; then
    # sysfs only after powerd agrees on 0, so the morning's level is a real change for it
    lipc-set-prop com.lab126.powerd flIntensity 0 >/dev/null 2>&1 || return 0
  fi
  for light_node in $LIGHT_NODES; do
    [ -w "$light_node" ] || continue
    [ "$(cat "$light_node" 2>/dev/null)" = "0" ] && continue
    echo 0 2>/dev/null > "$light_node"
  done
  return 0
}

light_restore() {
  [ -f "$LIGHT_SAVED" ] || return 0
  light_level="$(cat "$LIGHT_SAVED" 2>/dev/null)"
  case "$light_level" in
    ''|*[!0-9]*) rm -f "$LIGHT_SAVED"; return 0 ;;   # not a level: nothing to bring back
  esac
  # on a failure the file stays, and the next download tries again
  lipc-set-prop com.lab126.powerd flIntensity "$light_level" >/dev/null 2>&1 || return 0
  rm -f "$LIGHT_SAVED"
  log "light on (level $light_level)"
  return 0
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
