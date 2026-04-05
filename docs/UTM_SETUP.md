# UTM VM Setup Reference

Quick reference for configuring a UTM VM to work with the PerfectCue Bridge.

---

## VM Settings Summary

| Setting | Value |
|---------|-------|
| Backend | **QEMU** (not Apple Virtualization) |
| OS | Linux / Ubuntu |
| Architecture | ARM64 (Apple Silicon) or x86_64 (Intel) |
| RAM | 512 MB minimum, 1 GB recommended |
| CPU cores | 1–2 |
| Disk | 8 GB |
| Network | Host Only (+ NAT optional) |
| USB controller | USB 3.0 (xHCI) |
| USB sharing | Enabled, max devices: 3 |

---

## Why QEMU Backend

USB passthrough in UTM is **only supported by the QEMU backend**.
The Apple Virtualization framework does not expose USB sharing.

When creating a new VM for this use case:
- Select **Virtualize** (Apple Silicon) or **Emulate** (Intel)
- Choose **Linux**
- Do **not** select Apple Virtualization

---

## Network Modes

### Host Only (required for web UI access from Mac)

Gives the VM an IP on a private network shared only with the Mac.
The Mac can reach the VM at `192.168.64.x` and the VM can reach
the Mac at `192.168.64.1`.

Find the Mac's host-only IP:
```bash
ifconfig bridge100 | grep "inet "
```

### Shared Network / NAT (optional, for VM internet access)

Add a second network adapter in VM settings set to Shared Network.
Use this for `apt update` / `git clone` from inside the VM.

---

## USB Passthrough Checklist

1. VM must use **QEMU backend**
2. **USB Sharing enabled** in VM Settings → Input
3. VM must be **running** before you attach the device
4. Click the **USB plug icon** in the UTM toolbar while VM is running
5. Select the PerfectCue receiver from the list
6. macOS releases the device — verify inside VM with `lsusb`
7. Bridge user must be in `input` group (handled by `install.sh`)

### Auto-attach

Some UTM versions remember previously attached devices and
re-attach them automatically on VM start. If not, attach manually
via the toolbar USB icon each session as part of show setup.

---

## Finding the VM IP

Inside the VM:

```bash
ip addr show
# Look for inet on enp0s... or eth0
```

Or from the Mac once SSH is running:

```bash
# Scan UTM host-only subnet
arp -a | grep 192.168.64
```

---

## Headless Operation

Once SSH is configured, the UTM console window is not needed.
Start the VM headless from the Mac terminal using `utmctl`:

```bash
# List VMs
utmctl list

# Start headless
utmctl start "PerfectCue Bridge"

# Stop
utmctl stop "PerfectCue Bridge"
```

`utmctl` is installed at `/Applications/UTM.app/Contents/MacOS/utmctl`.
Add it to your PATH:

```bash
export PATH="$PATH:/Applications/UTM.app/Contents/MacOS"
```
