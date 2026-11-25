#!/usr/bin/env bash
# hwsetup.sh -- 1.5.2: video card (GPU) setup for hardware transcoding.  SOURCED by install.sh and update.sh;
# not meant to be run on its own.  Expects: say/ok/warn, PROJECT_DIR, VENV_PY, SVC_USER, RUN_AS (array), SKIP_APT.
#
#   hw_scan        lists the video cards (PCI display class) -> HW_INTEL / HW_AMD / HW_NVIDIA = yes|no
#   hw_packages    best effort: VA-API / oneVPL drivers for Intel, Mesa VA for AMD (never fails the install)
#   hw_groups      service user -> video + render groups (access to /dev/dri/renderD*)
#   hw_choose BY   test-encodes on each card and saves the first method that works in Settings, but ONLY when
#                  nothing is saved yet -- a choice made in Settings > Transcoding is never overridden
#
# Test hooks (container tests without a GPU): MS_HW_SYSFS / MS_HW_DEV / MS_FFMPEG are passed to the app.

HW_INTEL=no; HW_AMD=no; HW_NVIDIA=no

hw_scan() {
  local sys="${MS_HW_SYSFS:-/sys}" d cls ven dev name n=0
  for d in "$sys"/bus/pci/devices/*; do
    [ -r "$d/class" ] || continue
    cls="$(cat "$d/class" 2>/dev/null)"; case "$cls" in 0x03*) ;; *) continue ;; esac
    ven="$(cat "$d/vendor" 2>/dev/null)"; dev="$(cat "$d/device" 2>/dev/null)"
    name=""
    if [ -z "${MS_HW_SYSFS:-}" ] && command -v lspci >/dev/null 2>&1; then
      name="$(lspci -s "${d##*/}" 2>/dev/null | sed 's/^[^:]*:[^:]*: *//' | head -1)"
    fi
    case "$ven" in
      0x8086) HW_INTEL=yes; name="${name:-Intel graphics}" ;;
      0x1002) HW_AMD=yes;   name="${name:-AMD graphics}" ;;
      0x10de) HW_NVIDIA=yes; name="${name:-NVIDIA graphics}" ;;
      *)      name="${name:-display controller}" ;;
    esac
    n=$((n + 1))
    echo "    card: ${d##*/} [${ven#0x}:${dev#0x}] $name"
  done
  [ "$n" -gt 0 ] || echo "    no video card found -- videos will be converted on the CPU"
  local r; for r in "${MS_HW_DEV:-/dev}"/dri/renderD*; do [ -e "$r" ] && echo "    render node: $r"; done
  if [ "$HW_NVIDIA" = "yes" ]; then
    if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi -L 2>/dev/null | sed 's/^/    nvidia-smi: /' | head -4
    else warn "NVIDIA card found but no NVIDIA driver (nvidia-smi) -- install it for NVENC:  sudo ubuntu-drivers install"; fi
  fi
  return 0
}

_hw_apt_one() {   # install one package if the archive has it; never fails
  local p="$1"
  dpkg -s "$p" >/dev/null 2>&1 && { echo "    $p: already installed"; return 0; }
  local pol; pol="$(apt-cache policy "$p" 2>/dev/null || true)"   # no "| grep -q": SIGPIPE + pipefail = false miss
  if [[ "$pol" =~ Candidate:\ [0-9] ]]; then
    if DEBIAN_FRONTEND=noninteractive apt-get install -y "$p" >/dev/null 2>&1; then echo "    $p: installed"; return 0; fi
    warn "$p: install failed (skipped)"; return 1
  fi
  echo "    $p: not in the package archive (skipped)"; return 1
}

hw_packages() {
  if [ "${SKIP_APT:-no}" = "yes" ] || [ "${MS_SKIP_APT:-}" = "1" ]; then echo "    skipping GPU packages (--skip-apt)"; return 0; fi
  command -v apt-get >/dev/null 2>&1 || return 0
  [ "$HW_INTEL$HW_AMD$HW_NVIDIA" = "nonono" ] && { echo "    no GPU packages needed"; return 0; }
  _hw_apt_one pciutils || true
  if [ "$HW_INTEL" = "yes" ]; then
    # iHD VA-API driver (Broadwell .. Arc); the non-free build adds encoding on more chips (multiverse)
    _hw_apt_one intel-media-va-driver-non-free || _hw_apt_one intel-media-va-driver || true
    _hw_apt_one vainfo || true
    # oneVPL dispatcher + GPU runtime: needed for Intel QSV on Arc / 11th gen and newer (VAAPI works without)
    _hw_apt_one libvpl2 || true
    _hw_apt_one libmfx-gen1.2 || true
  fi
  if [ "$HW_AMD" = "yes" ]; then
    _hw_apt_one mesa-va-drivers || true
    _hw_apt_one vainfo || true
  fi
  return 0
}

hw_groups() {
  [ -n "${SVC_USER:-}" ] && id "$SVC_USER" >/dev/null 2>&1 || return 0
  local g; for g in video render; do getent group "$g" >/dev/null && usermod -aG "$g" "$SVC_USER" 2>/dev/null || true; done
  echo "    service user groups: $(id -nG "$SVC_USER" 2>/dev/null)"
}

hw_choose() {   # $1 = install | update
  local out
  out="$(cd "$PROJECT_DIR" && "${RUN_AS[@]}" env ${MS_HW_SYSFS:+MS_HW_SYSFS="$MS_HW_SYSFS"} ${MS_HW_DEV:+MS_HW_DEV="$MS_HW_DEV"} \
         ${MS_FFMPEG:+MS_FFMPEG="$MS_FFMPEG"} "$VENV_PY" -m app.cli hw-setup --if-unset --by "$1" 2>/dev/null)" \
    || { warn "video card test did not run -- Settings > Transcoding can test it later"; return 0; }
  local mode kept
  mode="$(echo "$out" | sed -n 's/^HW_MODE=//p' | tail -1)"; kept="$(echo "$out" | sed -n 's/^HW_KEPT=//p' | tail -1)"
  echo "$out" | sed -n 's/^HW_CARD=/    card: /p; s/^HW_TEST=/    test: /p; s/^HW_HINT=/    hint: /p'
  if [ "$kept" = "yes" ]; then ok "hardware transcoding: kept your setting ($mode)"
  elif [ "$mode" = "off" ] || [ -z "$mode" ]; then ok "hardware transcoding: off -- no working video card, videos are converted on the CPU"
  else ok "hardware transcoding: $mode on $(echo "$out" | sed -n 's/^HW_DEVICE=//p' | tail -1) (change it in Settings > Transcoding)"; fi
}
