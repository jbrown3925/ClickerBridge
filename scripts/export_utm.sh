#!/usr/bin/env bash
# =============================================================================
# export_utm.sh — Export a UTM VM as a portable .utm bundle
#
# Run on your Mac after the bridge is fully configured inside the VM.
# Compresses the qcow2 disk image with zstd and strips machine-specific
# identifiers so the bundle can be imported on another machine.
#
# Usage:
#   bash scripts/export_utm.sh "PerfectCue Bridge" ~/Desktop/perfectcue-bridge-vm.utm
#
# Requirements:
#   brew install qemu          (for qemu-img)
# =============================================================================
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ── Args ───────────────────────────────────────────────────────────────
VM_NAME="${1:-}"
OUTPUT="${2:-}"

[[ -z "$VM_NAME" ]] && error "Usage: $0 \"VM Name\" output.utm"
[[ -z "$OUTPUT"  ]] && error "Usage: $0 \"VM Name\" output.utm"

# ── Locate UTM storage ─────────────────────────────────────────────────
UTM_DOCS="$HOME/Library/Containers/com.utmapp.UTM/Data/Documents"
UTM_APP_DOCS="$HOME/Library/Group Containers/WDNLXADSXT.group.com.utmapp.UTM/Library/Containers/com.utmapp.UTM/Data/Documents"

if [[ -d "$UTM_DOCS" ]]; then
    DOCS="$UTM_DOCS"
elif [[ -d "$UTM_APP_DOCS" ]]; then
    DOCS="$UTM_APP_DOCS"
else
    error "Could not find UTM documents directory. Is UTM installed?"
fi

VM_PATH="$DOCS/${VM_NAME}.utm"
[[ -d "$VM_PATH" ]] || error "VM not found: $VM_PATH"

info "Found VM: $VM_PATH"

# ── Require qemu-img ───────────────────────────────────────────────────
if ! command -v qemu-img &>/dev/null; then
    error "qemu-img not found. Install with: brew install qemu"
fi

# ── Stop VM if running ─────────────────────────────────────────────────
UTMCTL="/Applications/UTM.app/Contents/MacOS/utmctl"
if [[ -x "$UTMCTL" ]]; then
    VM_STATE=$("$UTMCTL" status "$VM_NAME" 2>/dev/null | awk '{print $NF}' || echo "unknown")
    if [[ "$VM_STATE" == "started" ]]; then
        warn "VM is running — stopping it before export..."
        "$UTMCTL" stop "$VM_NAME"
        sleep 3
    fi
fi

# ── Build output bundle ────────────────────────────────────────────────
OUTPUT="${OUTPUT%.utm}.utm"
WORK_DIR=$(mktemp -d)
BUNDLE="$WORK_DIR/$(basename "$OUTPUT")"
mkdir -p "$BUNDLE/Data"

info "Copying config.plist..."
cp "$VM_PATH/config.plist" "$BUNDLE/config.plist"

# Strip machine-specific platform identifier so bundle is portable
/usr/libexec/PlistBuddy -c \
    "delete :System:GenericPlatform:machineIdentifier" \
    "$BUNDLE/config.plist" 2>/dev/null || true

# ── Compress disk image(s) ─────────────────────────────────────────────
DISK_COUNT=0
for img in "$VM_PATH/Data/"*.{qcow2,img,raw} 2>/dev/null; do
    [[ -f "$img" ]] || continue
    BASENAME=$(basename "$img")
    info "Compressing $BASENAME..."
    qemu-img convert \
        -p \
        -O qcow2 \
        -c \
        -o compression_type=zstd \
        "$img" \
        "$BUNDLE/Data/$BASENAME"
    DISK_COUNT=$((DISK_COUNT + 1))
done

[[ $DISK_COUNT -eq 0 ]] && error "No disk images found in $VM_PATH/Data/"

# ── Copy EFI vars if present ───────────────────────────────────────────
for f in "$VM_PATH/Data/"*.fd "$VM_PATH/Data/"efi_vars*; do
    [[ -f "$f" ]] || continue
    info "Copying $(basename "$f")..."
    cp "$f" "$BUNDLE/Data/"
done

# ── Move to final output path ──────────────────────────────────────────
mv "$BUNDLE" "$OUTPUT"
rm -rf "$WORK_DIR"

# ── Summary ────────────────────────────────────────────────────────────
SIZE=$(du -sh "$OUTPUT" | cut -f1)
echo ""
echo "╔══════════════════════════════════════════╗"
info "Export complete!"
echo ""
echo "  Output : $OUTPUT"
echo "  Size   : $SIZE"
echo ""
echo "  To import on another Mac:"
echo "  1. Copy $(basename "$OUTPUT") to the target Mac"
echo "  2. Double-click it — UTM will import it"
echo "  3. On first boot, attach the PerfectCue via UTM USB menu"
echo "╚══════════════════════════════════════════╝"
