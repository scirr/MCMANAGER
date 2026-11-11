#!/bin/bash
# Usage: mac_fresh.sh <MCManager-macOS.zip>
step=""
fail() {
  local detail
  detail=$(printf '%s' "$2" | sed -e 's/%/%25/g' -e ':a;N;$!ba;s/\n/%0A/g' -e 's/\r//g')
  echo "::error title=Parcours macOS $step::$step: $1%0A$detail"
  exit 1
}
begin() { step="$1"; echo "::group::$1"; }
endstep() { echo "::endgroup::"; }

zip="$1"
home_dir="$HOME/MC Manager caf$(printf '\303\251')"
mkdir -p "$home_dir"
begin "install"
ditto -x -k "$zip" "$home_dir" || fail "cannot unzip"
app="$home_dir/MCManager"
[ -f "$app/install.sh" ] || fail "install.sh not found" "$(ls "$home_dir")"
out=$(cd "$app" && ./install.sh 2>&1) || fail "install.sh failed" "$(printf '%s' "$out" | tail -25)"
echo "$out" | tail -15
py="$app/venv/bin/python"
mc() { "$py" "$app/mc_cli.py" "$@"; }
export PATH="$HOME/bin:/usr/local/bin:$PATH"
out=$(mc version 2>&1) || fail "mc version failed" "$out"
command -v mc >/dev/null || fail "the global mc command is missing" "PATH=$PATH"
endstep

begin "LaunchAgent"
plist="$HOME/Library/LaunchAgents/io.github.scirr.mcmanager.plist"
[ -f "$plist" ] || fail "LaunchAgent plist missing" "$(ls "$HOME/Library/LaunchAgents" 2>&1)"
plutil -lint "$plist" || fail "invalid plist"
launchctl print "gui/$(id -u)/io.github.scirr.mcmanager" >lc.txt 2>&1 || fail "LaunchAgent not loaded" "$(tail -15 lc.txt)"
grep -E "state|pid|program" lc.txt | head
endstep

rcon_wait() {
  local i out
  for i in $(seq 1 60); do
    out=$(mc rcon list 2>&1) && echo "$out" | grep -q players && { echo "$out"; return 0; }
    sleep 5
  done
  logs=$(find "$HOME/MCManager" "$app" "$HOME/Library" \( -name latest.log -o -name daemon.log \) 2>/dev/null | head -3 | while read -r f; do echo "--- $f"; tail -20 "$f"; done)
  fail "RCON did not answer within 300s" "$out
--- mc start:
$start_out
$logs"
}

port=25600
for loader in Vanilla Fabric; do
  begin "$loader 1.21.1"
  name="t-$(echo "$loader" | tr 'A-Z' 'a-z')"
  out=$(mc deploy --name "$name" --loader "$loader" --version 1.21.1 --port "$port" --rcon-port $((port+1)) --ram 1G --accept-eula --yes 2>&1) || fail "deploy $loader failed" "$(printf '%s' "$out" | tail -25)"
  echo "$out" | tail -5
  mc use "$name" >/dev/null 2>&1
  start_out=$(mc start 2>&1) || fail "start failed" "$start_out"
  rcon_wait
  out=$(mc doctor 2>&1); code=$?
  echo "$out" | tail -20
  [ $code -le 3 ] || fail "mc doctor crashed (exit $code)" "$(printf '%s' "$out" | tail -15)"
  out=$(mc stop 2>&1) || fail "stop failed" "$out"
  for i in $(seq 1 30); do mc rcon list >/dev/null 2>&1 || break; sleep 3; done
  mc rcon list >/dev/null 2>&1 && fail "the server still answers after stop"
  endstep
  port=$((port+2))
done

begin "uninstall"
(cd "$app" && printf 'Y\n' | ./uninstall.sh >uninstall.txt 2>&1) || fail "uninstall.sh failed" "$(tail -20 "$app/uninstall.txt")"
[ ! -f "$plist" ] || fail "LaunchAgent plist still there"
launchctl print "gui/$(id -u)/io.github.scirr.mcmanager" >/dev/null 2>&1 && fail "LaunchAgent still loaded"
[ ! -e "$HOME/bin/mc" ] && [ ! -e /usr/local/bin/mc ] || fail "mc command still there"
endstep
