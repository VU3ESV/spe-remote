# SPE Amplifier Remote Control

A modern Python 3 remote control server for **SPE Expert** HF amplifiers (1.5K-FA, 2K-FA, etc.) with a built-in web interface. Runs on a Raspberry Pi and serves a real-time dashboard to any browser on your network.

![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Features

- **Self-contained** — single process serves both WebSocket API and web UI (no Apache/Nginx needed)
- **Multi-client** — multiple browsers/devices can monitor the amplifier simultaneously
- **Real-time gauges** — SWR, drain current, PA temperature, voltage with canvas-based arc gauges
- **Responsive** — works on desktop, tablet, and mobile
- **Auto-reconnect** — WebSocket and serial both reconnect automatically on failure
- **Async I/O** — non-blocking serial communication using `pyserial-asyncio`
- **Configurable** — YAML config file for serial port, baud rate, polling intervals

## Screenshots

The web client displays:
- Power output bar (0–1500 W) with gradient
- SWR, drain, temperature, and voltage gauges
- TX/RX status with visual indicator
- Band, antenna, input, and level information
- Warning and error alerts
- Control buttons: Operate, ANT, TUNE, INPUT, GAIN

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

### 3. Configure

Edit `config.yaml` to match your setup:

```yaml
serial:
  port: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AI040V80-if00-port0
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

# Or check dmesg
dmesg | grep ttyUSB
```

Using `/dev/serial/by-id/...` paths is recommended — they persist across reboots unlike `/dev/ttyUSB0`.

### 4. Start the Server

```bash
./run.sh
```

### 5. Open the Web Interface

Navigate to `http://<your-pi-ip>:8888/` in any browser.

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
├── spe/
│   ├── __init__.py
│   ├── config.py            # YAML config loader
│   ├── protocol.py          # SPE serial protocol parser
│   ├── serial_handler.py    # Async serial I/O with reconnect
│   ├── websocket_handler.py # Multi-client WebSocket handler
│   └── app.py               # Tornado application setup
└── web/
    ├── index.html           # Web client
    ├── style.css            # Dark theme styles
    └── app.js               # WebSocket client + gauge rendering
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

**Send commands (text messages):**

| Command    | Action                  |
|------------|-------------------------|
| `oper`     | Toggle Operate/Standby  |
| `antenna`  | Cycle TX antenna        |
| `input`    | Toggle input            |
| `tune`     | Start ATU tuning        |
| `gain`     | Toggle gain             |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Serial error: [Errno 2] No such file` | Check serial port path in `config.yaml` |
| `Permission denied: /dev/ttyUSB0` | Add user to dialout group: `sudo usermod -aG dialout $USER` then re-login |
| Web page not loading | Check firewall: `sudo ufw allow 8888/tcp` |
| Gauges not updating | Check browser console for WebSocket errors |
| Multiple `/dev/ttyUSBx` devices | Use `/dev/serial/by-id/...` path instead |

## Credits

- **Original script**: OH2GEK — Python 2 server with WebSocket interface for SPE amplifiers
- **Modernized version**: VU2CPL — Python 3 port with async I/O, multi-client support, built-in web client, and responsive UI

## License

MIT License — see [LICENSE](LICENSE) for details.
