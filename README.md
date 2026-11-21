# Epson Printer Tools — Home Assistant add-on

Home Assistant add-on for Epson inkjet printers: find the printer on the LAN, run
**nozzle check** and **head cleaning**, and keep a record of when the printer last
printed and when the head was last cleaned.

Built from reverse-engineering the Epson Smart Panel app traffic (PCAP, Android) against
an Epson EcoTank L8050. Both maintenance actions are native **ESC/P-R** jobs submitted
over **LPR (TCP 515)** with job id `A1` — no CUPS, no driver, no cloud:

| Action | Payload | Prints? | Command |
|---|---|---|---|
| Nozzle check | 158 B | yes, 1 page | `NC` |
| Head cleaning | 92 B | no | `CH` |

The only variable byte range between two runs of the same job is the 8-byte `TI`
timestamp (`00 | year BE | month | day | hour | minute | second`), so the add-on builds
it at runtime and the rest of the payload stays byte-identical to the capture.

## Features

- **LAN discovery** — scans the local /24 (auto-detected, or `scan_subnet` option) for
  printers that answer the Epson status API on `POST /remote_operation/v1/device/get_status`,
  then reads identity over SNMP.
- **Manual IP** — type an address if the printer is on another subnet or the scan is blocked.
- **Nozzle check / head cleaning** from the sidebar panel (ingress UI).
- **Usage telemetry** — `prtMarkerLifeCount` (total pages) polled over SNMP; when the counter
  increases the add-on stamps *last print*, which also catches jobs sent from phones, CUPS
  or Epson Connect. Cleaning never prints, so *last head cleaning* is stamped when the job
  is submitted.
- **Optional MQTT discovery** — exposes `sensor` (status, pages, last print, last clean)
  and two `button` entities in Home Assistant.

## Installation

1. Home Assistant → **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add `https://github.com/KhoaZero123/ha-epson-printer-tools`
3. Install **Epson Printer Tools**, start it, then open **Web UI** from the add-on page
   (Settings → Add-ons → Epson Printer Tools → *Open Web UI*). Leave `printer_ip` empty and
   press *Quét LAN*, or type the address yourself.

Local testing without publishing:

```bash
scp -r epson_printer_tools root@homeassistant:/addons/
ha addons reload
ha addons install local_epson_printer_tools
```

## Configuration

```yaml
printer_ip: ""            # empty = discover through the UI, else e.g. 192.168.1.108
scan_subnet: ""           # empty = auto-detect, else e.g. 192.168.1.0/24
poll_interval: 60         # seconds between counter polls (15-3600)
utc_offset: 7             # fixed local offset: the container has no tzdata
mqtt_enabled: false
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
mqtt_prefix: epson_printer
```

## How the derived timestamps work

The printer has no clock and no job log: its local API only reports `printer-state`, and
the web UI hides counters behind an admin password. What it does expose is a monotonic
page counter (`1.3.6.1.2.1.43.10.2.1.4.1.1`). The add-on polls it and stores the moment it
increases, in `/data/state.json`. That is a derivation, not a device-stored timestamp — a
poll interval of 60 s means the recorded time can be up to one interval late.

Verified values on an L8050: `prtMarkerLifeCount`, `prtMarkerMarkLifeCount`,
`prtGeneralSerialNumber` (`43.5.1.1.17.1`), `hrDeviceDescr` (`25.3.2.1.3.1`), `sysUpTime`.

## Scope and safety

- Only two jobs are ever sent, both are the ones the vendor app sends.
- Head cleaning consumes ink and takes 1–3 minutes; the printer reports `processing` while
  it runs. Nozzle check prints one page.
- Works with any Epson inkjet that accepts the same ESC/P-R `REMOTE1` maintenance commands;
  other models are untested.

## Publishing images

`.github/workflows/build.yaml` builds both architectures and pushes
`ghcr.io/<owner>/<arch>-epson-printer-tools:<version>` on a `v*` tag. When those images
exist, add this line to `epson_printer_tools/config.yaml` so installations pull instead of
building locally (Supervisor prefers `image` over `build`):

```yaml
image: ghcr.io/khoazero123/{arch}-epson-printer-tools
```

## Verified on

- Home Assistant OS 17 / Supervisor on aarch64, Mosquitto 7.0.1, Epson EcoTank L8050
  (`07.69.TN31OA`), printer firmware answering `get_status` on port 80.
- Discovery: 253 hosts probed in 3.2 s, one hit with SNMP identity.
- MQTT: two buttons + four sensors appear under one device; pressing *Head cleaning*
  from HA sends the 92 B job and stamps *Last head cleaning*.

## License

MIT
