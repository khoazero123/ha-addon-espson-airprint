# Epson Printer Tools — Home Assistant add-on

Home Assistant add-on for Epson inkjet printers: discover the printer on the LAN, run
**nozzle check** and **head cleaning**, record when the printer last printed and when the
head was last cleaned, and share it to iPhone/iPad/Mac as an **AirPrint** queue.

Built by reverse-engineering the Epson Smart Panel app (PCAP, Android) against an
Epson EcoTank L8050. Both maintenance actions are native **ESC/P-R** jobs submitted over
**LPR (TCP 515)** with job id `A1` — the printer's own app does exactly this, no proprietary
cloud call:

| Action | Payload | Prints? | Command |
|---|---|---|---|
| Nozzle check | 158 B | yes, 1 page | `NC` |
| Head cleaning | 92 B | no | `CH` |

The only byte range that differs between two runs of the same job is the 8-byte `TI`
timestamp (`00 | year BE | month | day | hour | minute | second`), so the add-on rebuilds
that field at runtime and keeps the rest of the payload byte-identical to the capture.

## Features

- **LAN discovery** — scans the local /24 (auto-detected interface, or `scan_subnet`),
  finds printers that answer the Epson status API on
  `POST /remote_operation/v1/device/get_status`, and reads identity over SNMP.
- **Manual IP** — type an address for printers on another subnet or when scanning is blocked.
- **Nozzle check / head cleaning** — one button each in the ingress UI and in Home Assistant.
- **Usage telemetry** — `prtMarkerLifeCount` (total pages) polled over SNMP; when the counter
  grows, the add-on stamps *last print*, so jobs sent from phones, CUPS or Epson Connect are
  caught too. Cleaning never prints, so *last head cleaning* is stamped when the job is sent.
- **AirPrint bridge** — CUPS inside the add-on holds a queue for the printer (ESC/P-R driver,
  relaying to the printer's raw port 9100) and advertises it over mDNS/DNS-SD, so iOS and
  macOS list it in the print dialog without any app.
- **Optional MQTT discovery** — `sensor` (status, pages, last print, last clean),
  `binary_sensor` (AirPrint bridge) and two `button` entities in Home Assistant.

## Installation

1. Home Assistant → **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add `https://github.com/khoazero123/ha-addon-espson-airprint`
3. Install **Epson Printer Tools** (builds locally, aarch64/amd64), start it, open the
   add-on page and press **Open Web UI** (ingress panel *Epson Printer*).

The container uses the host network: it needs LPR 515, SNMP 161 and IPP 631 on the LAN, plus
UDP 5353 for mDNS.

## Configuration

```yaml
printer_ip: ""            # empty = discover/scan through the UI, else e.g. 192.168.1.108
scan_subnet: ""           # empty = auto-detect, else e.g. 192.168.1.0/24
poll_interval: 60         # seconds between counter polls (15-3600)
utc_offset: 7             # fixed local offset: the container carries no tzdata
mqtt_enabled: false
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
mqtt_prefix: epson_printer
airprint_enabled: true
airprint_name: Epson L8050 AirPrint
airprint_location: ""
```

Supervisor rewrites `options.json` on every start, so values changed in the web UI are stored
in `/data/settings.json` and merged over the options at boot.

## AirPrint

The add-on runs CUPS with the Epson ESC/P-R PPD (`printer-driver-escpr`) and Avahi:

- queue device: `socket://<printer_ip>:9100` (raw ESC/P-R, no cloud round-trip)
- queue name: sanitized from `airprint_name` (spaces become `_`)
- mDNS instance: `<airprint_name>`, host `<host-name>.local` on the LAN interface only
- IPP endpoint: `ipp://<home-assistant-ip>:631/printers/<queue>`

iOS/iPadOS: open any document → Share → Print → the printer shows up under the given name.
If it does not appear, check the *AirPrint* card in the web UI: `mDNS/DNS-SD` must be `ON`,
and the queue must be `sẵn sàng` (*ready*).

## Removing the old CUPS-on-NAS container

This add-on replaces a standalone `cups-airprint` container. After installing:

```bash
docker stop cups-airprint
docker update --restart=no cups-airprint   # keeps it from coming back after a reboot
```

## Building locally (development)

```bash
docker build -t epson-addon:dev epson_printer_tools
docker run --rm --network host -e DATA_DIR=/tmp/data -e INGRESS_PORT=8080 epson-addon:dev
```

Deploy to Home Assistant OS:

```bash
scp -r epson_printer_tools root@homeassistant:/addons/
ha supervisor reload
ha addons install local_epson_printer_tools    # rebuild instead of install when already there
ha addons start local_epson_printer_tools
```

Note: the Supervisor caches a local add-on's definition under `/data/apps/local/<slug>`;
if a version or option change does not show up, copy the new `config.yaml` there as well and
run `ha supervisor reload`.

## Verified on

- Home Assistant OS 17.1 / Supervisor, aarch64, Mosquitto 7.0.1, Ubuntu 24.04 based image.
- Discovery: 253 hosts probed in 3.2 s, one hit with SNMP identity
  (`EPSON L8050 Series`, serial `XB52027329`).
- Maintenance jobs verified byte-exact against the app capture (92 B / 158 B).
- AirPrint: `Epson L8050 AirPrint` advertised on `end0`, `192.168.1.90:631`,
  `pdl=application/pdf,application/postscript,image/jpeg,image/png,image/pwg-raster,image/urf`,
  `URF=V1.4,CP1,W8,PQ4,OFU0,SRGB24,RS300,FN3`, Mopria certified 1.3;
  `ipptool get-printer-attributes` returns `printer-is-accepting-jobs=true`, `printer-state=idle`.

## Publishing images

`.github/workflows/build.yaml` builds both architectures and pushes
`ghcr.io/<owner>/<arch>-epson-printer-tools:<version>` on a `v*` tag. When those images
exist, add this line to `epson_printer_tools/config.yaml` so installations pull instead of
building locally (Supervisor prefers `image` over `build`):

```yaml
image: ghcr.io/khoazero123/{arch}-epson-printer-tools
```

## License

MIT
