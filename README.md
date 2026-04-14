# SPE Amplifier Remote Control

A modern Python 3 remote control server for **SPE Expert** HF amplifiers (1.3K-FA, 1.5K-FA, 2K-FA) with a built-in web interface. Runs on a Raspberry Pi and serves a real-time dashboard to any browser on your network.

![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Features

- **Power On/Off** — remote power control via DTR line (on) and serial command 0x0A (off)
- **Full SPE protocol** — all 20 commands from the official Application Programmer's Guide Rev 1.1
- **Self-contained** — single process serves both WebSocket API and web UI (no Apache/Nginx needed)
- **Multi-client** — multiple browsers/devices can monitor the amplifier simultaneously
- **Real-time gauges** — SWR, drain current, PA temperature, voltage with canvas-based arc gauges
- **Responsive** — works on desktop, tablet, and mobile
- **Auto-reconnect** — WebSocket and serial both reconnect automatically on failure
- **Async I/O** — non-blocking serial communication using `pyserial-asyncio`
- **Configurable** — YAML config file for serial port, baud rate, polling intervals

## Web Interface

The web client displays:
- **Power ON / OFF** buttons with confirmation dialog and busy animation
- Power output bar (0–1500 W) with gradient
- SWR, drain current, temperature, and voltage gauges
- TX/RX status indicator (red pulse during TX, green during RX)
- Band, antenna, input, and power level information
- Warning and error alerts from the amplifier
- Control buttons: Operate, ANT, TUNE, INPUT, POWER, BAND +/−

## Requirements

- Raspberry Pi (any model) or any Linux/macOS/Windows machine
- Python 3.9+
- SPE Expert amplifier connected via USB or RS-232
- `python3-venv` package (on Debian/Raspberry Pi OS)

## Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/vu2cpl/spe-remote.git
cd spe-remote
```

### 2. Run Setup

```bash
./setup.sh
```

This creates a Python virtual environment and installs all dependencies. On Raspberry Pi OS, it will also install `python3-venv` if needed.

### 3. Serial Port Access

```bash
sudo usermod -aG dialout $USER
# Log out and back in for this to take effect
```

### 4. Configure

Edit `config.yaml` to match your setup:

```yaml
serial:
  port: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_XXXXXXXX-if00-port0
  baudrate: 115200
  timeout: 1.0

server:
  port: 8888
  host: "0.0.0.0"

polling:
  tx_interval: 0.2      # Poll rate during TX (seconds)
  idle_interval: 1.0     # Poll rate during RX/Standby
  heartbeat: 15          # Force state push interval

logging:
  level: INFO
```

**Finding your serial port:**

```bash
# List USB serial devices
ls /dev/serial/by-id/

# Or check dmesg after plugging in
dmesg | grep ttyUSB
```

Using `/dev/serial/by-id/...` paths is recommended — they persist across reboots unlike `/dev/ttyUSB0`.

### 5. Start the Server

```bash
./run.sh
```
#### 5.1. Start the Server in a Detached Mode 

```bash
nohup ./run.sh &
```

### 6. Open the Web Interface

Navigate to `http://<your-pi-ip>:8888/` in any browser.

## SPE Serial Protocol

Based on the **SPE Application Programmer's Guide Rev 1.1** for Expert 1.3K-FA / 1.5K-FA / 2K-FA.

### Packet Format

```
0x55 0x55 0x55 [CNT] [DATA...] [CHK]
```

For single-byte commands: `CNT=0x01`, `CHK=DATA` (same byte).

### Command Set

| Hex  | Command        | WebSocket msg  | Description |
|------|----------------|----------------|-------------|
| 0x01 | INPUT          | `input`        | Toggle input port |
| 0x02 | BAND −         | `band_dn`      | Band down |
| 0x03 | BAND +         | `band_up`      | Band up |
| 0x04 | ANTENNA        | `antenna`      | Cycle TX antenna |
| 0x05 | L−             | —              | ATU L minus |
| 0x06 | L+             | —              | ATU L plus |
| 0x07 | C−             | —              | ATU C minus |
| 0x08 | C+             | —              | ATU C plus |
| 0x09 | TUNE           | `tune`         | Start ATU tuning |
| 0x0A | SWITCH OFF     | `power_off`    | Power OFF amplifier |
| 0x0B | POWER          | `power_level`  | Toggle power level (L/M/H) |
| 0x0C | DISPLAY        | `display`      | Display toggle |
| 0x0D | OPERATE        | `oper`         | Toggle Operate/Standby |
| 0x0E | CAT            | —              | CAT mode |
| 0x0F | LEFT ARROW     | —              | Menu navigation left |
| 0x10 | RIGHT ARROW    | —              | Menu navigation right |
| 0x11 | SET            | —              | Menu enter/set |
| 0x82 | BACKLIGHT ON   | `backlight_on` | Turn backlight on |
| 0x83 | BACKLIGHT OFF  | `backlight_off`| Turn backlight off |
| 0x90 | STATUS         | (auto)         | Request status string |

### Power On/Off

| Action     | Method | Notes |
|------------|--------|-------|
| **Power ON** | DTR hardware line toggle | No serial command exists; uses DTR/RTS sequence via USB-serial adapter |
| **Power OFF** | Serial command `0x0A` | SWITCH OFF — equivalent to pressing the front-panel OFF button |

> **Note:** When DTR is held high, it takes power mastering control — the amplifier shows "POWER SWITCH HELD BY REMOTE" warning and the front-panel power switch is overridden. Startup takes 3–4.5 seconds.

### Status String

The amplifier returns a 67-character ASCII comma-separated status string with 19 fields:

| Field | Contents |
|-------|----------|
| ID | `20K` (2K-FA) or `13K` (1.3K-FA) |
| Standby/Operate | `S` or `O` |
| RX/TX | `R` or `T` |
| Memory Bank | `A`, `B`, or `x` |
| Input | `1` or `2` |
| Band | `00` (160m) to `11` (4m) |
| TX Antenna + ATU | `0`–`6`, with `t`/`b`/`a` suffix |
| RX Antenna | Antenna number or `0r` |
| Power Level | `L`, `M`, or `H` |
| Output Power | Watts (4 chars) |
| SWR ATU | VSWR before ATU |
| SWR ANT | VSWR at antenna |
| V PA | Supply voltage |
| I PA | Drain current |
| Temp (upper) | Heatsink temp °C |
| Temp (lower) | Lower heatsink (2K-FA only) |
| Temp (combiner) | Combiner temp (2K-FA only) |
| Warnings | Single char code (see below) |
| Alarms | Single char code (see below) |

**Warning codes:** `M`=Alarm, `A`=No antenna, `S`=SWR, `B`=No band, `P`=Power limit, `O`=Overheat, `Y`=ATU N/A, `W`=Tune no power, `K`=ATU bypass, `R`=Remote hold, `T`=Combiner heat, `C`=Combiner fault, `N`=None

**Alarm codes:** `S`=SWR limit, `A`=Amp protection, `D`=Overdrive, `H`=Excess heat, `C`=Combiner fault, `N`=None

## Running as a System Service

To start the server automatically on boot:

```bash
sudo nano /etc/systemd/system/spe-remote.service
```

Paste:

```ini
[Unit]
Description=SPE Amplifier Remote Control
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/spe-remote
ExecStart=/home/pi/spe-remote/venv/bin/python server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable spe-remote
sudo systemctl start spe-remote
```

Check status:

```bash
sudo systemctl status spe-remote
journalctl -u spe-remote -f
```

## Project Structure

```
spe-remote/
├── config.yaml              # Configuration file
├── requirements.txt         # Python dependencies
├── setup.sh                 # One-time setup script
├── run.sh                   # Start script
├── server.py                # Main entry point
├── power_spe_on.py          # Original OH2GEK power-on script (reference)
├── spe/
│   ├── __init__.py
│   ├── config.py            # YAML config loader
│   ├── protocol.py          # SPE serial protocol (all 20 commands)
│   ├── power_control.py     # Power on (DTR) / off (0x0A) controller
│   ├── serial_handler.py    # Async serial I/O with reconnect
│   ├── websocket_handler.py # Multi-client WebSocket handler
│   └── app.py               # Tornado application setup
├── web/
│   ├── index.html           # Web client
│   ├── style.css            # Dark theme styles
│   └── app.js               # WebSocket client + gauge rendering
└── docs/
    ├── SPE_Remote_Control_User_Guide.pdf
    └── generate_guide.py    # PDF generator script
```

## WebSocket API

Connect to `ws://<host>:8888/ws`

**Received JSON (amplifier state):**

```json
{
  "op_status": "Oper",
  "tx_status": "TX",
  "input": "1",
  "band": "80m",
  "tx_antenna": "1",
  "p_level": "10",
  "p_out": "1353",
  "swr": "1.54",
  "aswr": "1.12",
  "voltage": "54.6",
  "drain": "27.3",
  "pa_temp": "26",
  "warnings": "",
  "error": ""
}
```

**Received JSON (power action result):**

```json
{
  "power_result": "power_on",
  "status": "ok"
}
```

**Send commands (text messages):**

| Command        | Action                        |
|----------------|-------------------------------|
| `power_on`     | Power ON via DTR toggle       |
| `power_off`    | Power OFF via serial cmd 0x0A |
| `oper`         | Toggle Operate/Standby        |
| `antenna`      | Cycle TX antenna              |
| `input`        | Toggle input port             |
| `tune`         | Start ATU tuning              |
| `power_level`  | Toggle power level (L/M/H)   |
| `band_up`      | Band up                       |
| `band_dn`      | Band down                     |
| `display`      | Toggle display                |
| `backlight_on` | Backlight on                  |
| `backlight_off`| Backlight off                 |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Serial error: [Errno 2] No such file` | Check serial port path in `config.yaml` |
| `Permission denied: /dev/ttyUSB0` | Add user to dialout group: `sudo usermod -aG dialout $USER` then re-login |
| Web page not loading | Check firewall: `sudo ufw allow 8888/tcp` |
| Gauges not updating | Check browser console for WebSocket errors |
| Multiple `/dev/ttyUSBx` devices | Use `/dev/serial/by-id/...` path instead |
| Power ON not working | Check FTDI USB-serial adapter supports DTR — verify with `dmesg` |
| "POWER SWITCH HELD BY REMOTE" | Normal when DTR is held high after power on |

## Credits

- **Original script**: [OH2GEK](https://github.com/oh2gek/SPE-1.3-2K-FA-Remote-server) — Python 2 server with WebSocket interface for SPE amplifiers
- **Modernized version**: VU2CPL — Python 3 port with async I/O, multi-client support, power on/off, full SPE protocol, built-in web client, and responsive UI
- **Protocol reference**: SPE Application Programmer's Guide Rev 1.1 for Expert 1.3K-FA / 2K-FA

## License

MIT License — see [LICENSE](LICENSE) for details.
