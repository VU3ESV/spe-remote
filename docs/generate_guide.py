#!/usr/bin/env python3
"""Generate the SPE Remote Control User Guide PDF."""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether,
)

# Colors
DARK_BG = HexColor("#1a1a2e")
ACCENT = HexColor("#00bcd4")
PANEL = HexColor("#16213e")
TEXT_LIGHT = HexColor("#333333")
HEADER_BG = HexColor("#0f3460")
WHITE = HexColor("#ffffff")
BLACK = HexColor("#000000")
LIGHT_GREY = HexColor("#f0f0f0")
MED_GREY = HexColor("#cccccc")

# Styles
style_title = ParagraphStyle(
    "Title", fontName="Helvetica-Bold", fontSize=28,
    textColor=HEADER_BG, alignment=TA_CENTER, spaceAfter=6,
)
style_subtitle = ParagraphStyle(
    "Subtitle", fontName="Helvetica", fontSize=14,
    textColor=ACCENT, alignment=TA_CENTER, spaceAfter=20,
)
style_credits = ParagraphStyle(
    "Credits", fontName="Helvetica", fontSize=10,
    textColor=TEXT_LIGHT, alignment=TA_CENTER, spaceAfter=4,
)
style_h1 = ParagraphStyle(
    "H1", fontName="Helvetica-Bold", fontSize=18,
    textColor=HEADER_BG, spaceBefore=16, spaceAfter=8,
)
style_h2 = ParagraphStyle(
    "H2", fontName="Helvetica-Bold", fontSize=13,
    textColor=ACCENT, spaceBefore=12, spaceAfter=6,
)
style_body = ParagraphStyle(
    "Body", fontName="Helvetica", fontSize=10,
    textColor=TEXT_LIGHT, alignment=TA_JUSTIFY,
    spaceBefore=3, spaceAfter=6, leading=14,
)
style_code = ParagraphStyle(
    "Code", fontName="Courier", fontSize=9,
    textColor=BLACK, backColor=LIGHT_GREY,
    spaceBefore=4, spaceAfter=6, leading=13,
    leftIndent=12, rightIndent=12,
    borderPadding=(6, 6, 6, 6),
)
style_bullet = ParagraphStyle(
    "Bullet", fontName="Helvetica", fontSize=10,
    textColor=TEXT_LIGHT, leftIndent=20, bulletIndent=8,
    spaceBefore=2, spaceAfter=2, leading=14,
)
style_note = ParagraphStyle(
    "Note", fontName="Helvetica-Oblique", fontSize=9,
    textColor=HexColor("#666666"), leftIndent=12,
    spaceBefore=4, spaceAfter=8, leading=12,
)

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=MED_GREY, spaceBefore=8, spaceAfter=8)

def bullet(text):
    return Paragraph(f"\u2022  {text}", style_bullet)

def code(text):
    return Paragraph(text.replace("\n", "<br/>"), style_code)

def build_pdf(output_path):
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title="SPE Remote Control User Guide",
        author="VU2CPL",
    )

    story = []

    # ---- COVER ----
    story.append(Spacer(1, 60))
    story.append(Paragraph("SPE Amplifier<br/>Remote Control", style_title))
    story.append(Spacer(1, 8))
    story.append(Paragraph("User Guide", style_subtitle))
    story.append(Spacer(1, 20))
    story.append(hr())
    story.append(Spacer(1, 10))
    story.append(Paragraph("For SPE Expert 1.5K-FA / 2K-FA HF Amplifiers", style_credits))
    story.append(Spacer(1, 30))
    story.append(Paragraph("Original script by <b>OH2GEK</b>", style_credits))
    story.append(Paragraph("Modernized and extended by <b>VU2CPL</b>", style_credits))
    story.append(Spacer(1, 40))

    # Version info table
    info_data = [
        ["Version", "2.0 (Python 3)"],
        ["Platform", "Raspberry Pi / Linux / macOS"],
        ["Interface", "Web browser (any device)"],
        ["Connection", "USB / RS-232 Serial"],
    ]
    info_table = Table(info_data, colWidths=[4*cm, 8*cm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_LIGHT),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (0, -1), 12),
    ]))
    story.append(info_table)

    story.append(PageBreak())

    # ---- TABLE OF CONTENTS ----
    story.append(Paragraph("Table of Contents", style_h1))
    story.append(hr())
    toc_items = [
        "1. Introduction",
        "2. Requirements",
        "3. Installation",
        "4. Configuration",
        "5. Starting the Server",
        "6. Web Interface Guide",
        "7. Controls Reference",
        "8. Running as a System Service",
        "9. WebSocket API",
        "10. Troubleshooting",
    ]
    for item in toc_items:
        story.append(Paragraph(item, style_body))
    story.append(PageBreak())

    # ---- 1. INTRODUCTION ----
    story.append(Paragraph("1. Introduction", style_h1))
    story.append(hr())
    story.append(Paragraph(
        "SPE Remote Control is a modern Python 3 application that allows you to monitor and "
        "control SPE Expert HF amplifiers remotely from any web browser. It communicates with "
        "the amplifier via USB or RS-232 serial connection and serves a real-time web dashboard "
        "over your local network.",
        style_body,
    ))
    story.append(Paragraph("Key Features:", style_h2))
    for feat in [
        "<b>Self-contained</b> - single process serves both the WebSocket API and web UI. No separate web server (Apache, Nginx) needed.",
        "<b>Multi-client</b> - multiple browsers and devices can monitor the amplifier simultaneously.",
        "<b>Real-time gauges</b> - SWR, drain current, PA temperature, and voltage displayed with animated arc gauges.",
        "<b>Responsive design</b> - works on desktop, tablet, and mobile screens.",
        "<b>Auto-reconnect</b> - both WebSocket and serial connections reconnect automatically on failure.",
        "<b>Async I/O</b> - non-blocking serial communication using pyserial-asyncio for reliable performance.",
        "<b>Configurable</b> - YAML configuration file for serial port, baud rate, polling intervals, and more.",
    ]:
        story.append(bullet(feat))

    story.append(PageBreak())

    # ---- 2. REQUIREMENTS ----
    story.append(Paragraph("2. Requirements", style_h1))
    story.append(hr())
    story.append(Paragraph("Hardware:", style_h2))
    for req in [
        "Raspberry Pi (any model - Pi 2, 3, 4, 5, or Zero 2 W) or any Linux/macOS computer",
        "SPE Expert amplifier (1.5K-FA, 2K-FA, or compatible model)",
        "USB cable or RS-232 serial connection to the amplifier",
        "Network connection (Ethernet or Wi-Fi)",
    ]:
        story.append(bullet(req))

    story.append(Paragraph("Software:", style_h2))
    for req in [
        "Python 3.9 or newer (included in Raspberry Pi OS)",
        "python3-venv package (for virtual environment)",
        "Git (for cloning the repository)",
    ]:
        story.append(bullet(req))

    story.append(Paragraph("Python Dependencies (installed automatically):", style_h2))
    dep_data = [
        ["Package", "Version", "Purpose"],
        ["tornado", ">= 6.0", "Web server and WebSocket framework"],
        ["pyserial-asyncio", ">= 0.6", "Async serial port communication"],
        ["pyyaml", ">= 6.0", "YAML configuration file parsing"],
    ]
    dep_table = Table(dep_data, colWidths=[4*cm, 3*cm, 7*cm])
    dep_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.5, MED_GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(Spacer(1, 6))
    story.append(dep_table)

    story.append(PageBreak())

    # ---- 3. INSTALLATION ----
    story.append(Paragraph("3. Installation", style_h1))
    story.append(hr())

    story.append(Paragraph("Step 1: Clone the Repository", style_h2))
    story.append(code(
        "git clone https://github.com/AnonMaoj/spe-remote.git<br/>"
        "cd spe-remote"
    ))

    story.append(Paragraph("Step 2: Run Setup", style_h2))
    story.append(code("./setup.sh"))
    story.append(Paragraph(
        "The setup script creates a Python virtual environment and installs all dependencies. "
        "On Raspberry Pi OS, it will also install python3-venv if needed.",
        style_body,
    ))

    story.append(Paragraph("Step 3: Add User to dialout Group", style_h2))
    story.append(Paragraph(
        "To access serial ports without sudo, add your user to the dialout group:",
        style_body,
    ))
    story.append(code("sudo usermod -aG dialout $USER"))
    story.append(Paragraph(
        "Log out and log back in for the group change to take effect.",
        style_note,
    ))

    story.append(PageBreak())

    # ---- 4. CONFIGURATION ----
    story.append(Paragraph("4. Configuration", style_h1))
    story.append(hr())
    story.append(Paragraph(
        "All settings are in the <b>config.yaml</b> file in the project root directory. "
        "Edit this file to match your setup.",
        style_body,
    ))
    story.append(code(
        "serial:<br/>"
        "&nbsp;&nbsp;port: /dev/serial/by-id/usb-FTDI_FT232R_USB_UART_...<br/>"
        "&nbsp;&nbsp;baudrate: 115200<br/>"
        "&nbsp;&nbsp;timeout: 1.0<br/>"
        "<br/>"
        "server:<br/>"
        "&nbsp;&nbsp;port: 8888<br/>"
        '&nbsp;&nbsp;host: "0.0.0.0"<br/>'
        "<br/>"
        "polling:<br/>"
        "&nbsp;&nbsp;tx_interval: 0.2<br/>"
        "&nbsp;&nbsp;idle_interval: 1.0<br/>"
        "&nbsp;&nbsp;heartbeat: 15<br/>"
        "<br/>"
        "logging:<br/>"
        "&nbsp;&nbsp;level: INFO"
    ))

    story.append(Paragraph("Configuration Options:", style_h2))
    config_data = [
        ["Setting", "Default", "Description"],
        ["serial.port", "/dev/ttyUSB0", "Serial port path to amplifier"],
        ["serial.baudrate", "115200", "Serial baud rate"],
        ["server.port", "8888", "HTTP/WebSocket listen port"],
        ["server.host", "0.0.0.0", "Listen address (0.0.0.0 = all interfaces)"],
        ["polling.tx_interval", "0.2", "Poll interval during TX (seconds)"],
        ["polling.idle_interval", "1.0", "Poll interval during RX/Standby"],
        ["polling.heartbeat", "15", "Force state broadcast interval"],
        ["logging.level", "INFO", "Log verbosity (DEBUG/INFO/WARNING/ERROR)"],
    ]
    config_table = Table(config_data, colWidths=[4*cm, 2.5*cm, 7.5*cm])
    config_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.5, MED_GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(Spacer(1, 6))
    story.append(config_table)

    story.append(Paragraph("Finding Your Serial Port:", style_h2))
    story.append(code(
        "# List USB serial devices<br/>"
        "ls /dev/serial/by-id/<br/>"
        "<br/>"
        "# Or check dmesg after plugging in the USB cable<br/>"
        "dmesg | grep ttyUSB"
    ))
    story.append(Paragraph(
        "Tip: Use /dev/serial/by-id/... paths instead of /dev/ttyUSB0. "
        "The by-id paths are stable across reboots and don't change if other USB devices are connected.",
        style_note,
    ))

    story.append(PageBreak())

    # ---- 5. STARTING ----
    story.append(Paragraph("5. Starting the Server", style_h1))
    story.append(hr())
    story.append(Paragraph("Start with the run script:", style_body))
    story.append(code("./run.sh"))
    story.append(Paragraph("Or start directly with the virtual environment Python:", style_body))
    story.append(code("venv/bin/python server.py"))
    story.append(Paragraph("To use a custom config file:", style_body))
    story.append(code("venv/bin/python server.py /path/to/custom-config.yaml"))
    story.append(Paragraph(
        "On successful startup you will see:",
        style_body,
    ))
    story.append(code(
        "2024-01-15 10:30:00 [INFO] spe: Server listening on http://0.0.0.0:8888/<br/>"
        "2024-01-15 10:30:00 [INFO] spe: Serial port: /dev/ttyUSB0 @ 115200 baud<br/>"
        "2024-01-15 10:30:00 [INFO] spe.serial_handler: Connecting to /dev/ttyUSB0...<br/>"
        "2024-01-15 10:30:00 [INFO] spe.serial_handler: Serial connected"
    ))
    story.append(Paragraph(
        "Open your browser and navigate to <b>http://&lt;pi-ip-address&gt;:8888/</b>",
        style_body,
    ))

    story.append(PageBreak())

    # ---- 6. WEB INTERFACE ----
    story.append(Paragraph("6. Web Interface Guide", style_h1))
    story.append(hr())
    story.append(Paragraph(
        "The web interface provides a real-time view of the amplifier's status with interactive controls.",
        style_body,
    ))

    story.append(Paragraph("Connection Indicator", style_h2))
    story.append(Paragraph(
        "The green/red dot at the top shows WebSocket connection status. "
        "If disconnected, the client will automatically attempt to reconnect with increasing delays.",
        style_body,
    ))

    story.append(Paragraph("Power Output Display", style_h2))
    story.append(Paragraph(
        "The large power bar shows the current output power in watts (0-1500W). "
        "The gradient color changes from green through cyan and yellow to red as power increases. "
        "SWR is displayed in the top-right corner.",
        style_body,
    ))

    story.append(Paragraph("Gauges", style_h2))
    story.append(Paragraph(
        "Four semi-circular arc gauges display real-time readings:",
        style_body,
    ))
    gauge_data = [
        ["Gauge", "Range", "Warning Zone"],
        ["SWR", "1:1 to 1:3.5", "Above 1:2.0 (orange), above 1:2.8 (red)"],
        ["Drain Current", "0 - 60 A", "Above 42 A (orange), above 51 A (red)"],
        ["PA Temperature", "0 - 80 C", "Above 60 C (orange), above 64 C (red)"],
        ["Voltage", "40 - 60 V", "Below 44 V or above 55 V (warning)"],
    ]
    gauge_table = Table(gauge_data, colWidths=[3.5*cm, 3.5*cm, 7*cm])
    gauge_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.5, MED_GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(Spacer(1, 6))
    story.append(gauge_table)

    story.append(Paragraph("Status Chips", style_h2))
    story.append(Paragraph(
        "A row of status chips shows: TX/RX status (red pulse during TX, green during RX), "
        "current band, antenna number, input number, and power level setting.",
        style_body,
    ))

    story.append(Paragraph("Alert Bar", style_h2))
    story.append(Paragraph(
        "Warning and error messages from the amplifier are displayed at the bottom "
        "in an orange (warning) or red (error) bar.",
        style_body,
    ))

    story.append(PageBreak())

    # ---- 7. CONTROLS ----
    story.append(Paragraph("7. Controls Reference", style_h1))
    story.append(hr())
    ctrl_data = [
        ["Button", "Action", "Description"],
        ["Operate", "Toggle Operate/Standby", "Switches the amplifier between Operate and Standby modes. Button highlights cyan when in Operate mode."],
        ["ANT", "Cycle TX Antenna", "Cycles through available TX antenna outputs (ANT 1, ANT 2, etc.)."],
        ["TUNE", "Start ATU Tuning", "Initiates the internal antenna tuning unit (ATU) cycle. Ensure RF drive is present."],
        ["INPUT", "Toggle Input", "Switches between available input connectors."],
        ["GAIN", "Toggle Gain", "Cycles through gain/power level settings."],
    ]
    ctrl_table = Table(ctrl_data, colWidths=[2.5*cm, 3.5*cm, 8*cm])
    ctrl_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.5, MED_GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(ctrl_table)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Note: All connected clients can send commands. In a multi-client setup, "
        "coordinate with other operators to avoid conflicting commands.",
        style_note,
    ))

    story.append(PageBreak())

    # ---- 8. SYSTEMD SERVICE ----
    story.append(Paragraph("8. Running as a System Service", style_h1))
    story.append(hr())
    story.append(Paragraph(
        "To start the server automatically on boot, create a systemd service file:",
        style_body,
    ))
    story.append(Paragraph("Step 1: Create the Service File", style_h2))
    story.append(code("sudo nano /etc/systemd/system/spe-remote.service"))
    story.append(Paragraph("Paste the following content:", style_body))
    story.append(code(
        "[Unit]<br/>"
        "Description=SPE Amplifier Remote Control<br/>"
        "After=network.target<br/>"
        "<br/>"
        "[Service]<br/>"
        "Type=simple<br/>"
        "User=pi<br/>"
        "WorkingDirectory=/home/pi/spe-remote<br/>"
        "ExecStart=/home/pi/spe-remote/venv/bin/python server.py<br/>"
        "Restart=always<br/>"
        "RestartSec=5<br/>"
        "<br/>"
        "[Install]<br/>"
        "WantedBy=multi-user.target"
    ))
    story.append(Paragraph(
        "Adjust User and WorkingDirectory to match your actual username and install path.",
        style_note,
    ))

    story.append(Paragraph("Step 2: Enable and Start", style_h2))
    story.append(code(
        "sudo systemctl daemon-reload<br/>"
        "sudo systemctl enable spe-remote<br/>"
        "sudo systemctl start spe-remote"
    ))

    story.append(Paragraph("Step 3: Check Status", style_h2))
    story.append(code(
        "sudo systemctl status spe-remote<br/>"
        "journalctl -u spe-remote -f"
    ))

    story.append(PageBreak())

    # ---- 9. WEBSOCKET API ----
    story.append(Paragraph("9. WebSocket API", style_h1))
    story.append(hr())
    story.append(Paragraph(
        "The server exposes a WebSocket endpoint for custom clients and integrations.",
        style_body,
    ))
    story.append(Paragraph("Endpoint:", style_h2))
    story.append(code("ws://&lt;host&gt;:8888/ws"))

    story.append(Paragraph("Received JSON (amplifier state):", style_h2))
    story.append(code(
        '{<br/>'
        '&nbsp;&nbsp;"op_status": "Oper",<br/>'
        '&nbsp;&nbsp;"tx_status": "TX",<br/>'
        '&nbsp;&nbsp;"band": "80m",<br/>'
        '&nbsp;&nbsp;"p_out": "1353",<br/>'
        '&nbsp;&nbsp;"swr": "1.54",<br/>'
        '&nbsp;&nbsp;"voltage": "54.6",<br/>'
        '&nbsp;&nbsp;"drain": "27.3",<br/>'
        '&nbsp;&nbsp;"pa_temp": "26",<br/>'
        '&nbsp;&nbsp;"warnings": "",<br/>'
        '&nbsp;&nbsp;"error": ""<br/>'
        '}'
    ))

    story.append(Paragraph("Send Commands (text messages):", style_h2))
    cmd_data = [
        ["Command", "Action"],
        ["oper", "Toggle Operate/Standby"],
        ["antenna", "Cycle TX antenna"],
        ["input", "Toggle input"],
        ["tune", "Start ATU tuning"],
        ["gain", "Toggle gain"],
    ]
    cmd_table = Table(cmd_data, colWidths=[4*cm, 8*cm])
    cmd_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (0, -1), "Courier"),
        ("FONTNAME", (1, 1), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.5, MED_GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(Spacer(1, 6))
    story.append(cmd_table)

    story.append(PageBreak())

    # ---- 10. TROUBLESHOOTING ----
    story.append(Paragraph("10. Troubleshooting", style_h1))
    story.append(hr())

    issues = [
        ("Serial error: No such file or directory",
         "The serial port path in config.yaml does not exist. Check the cable is plugged in and verify "
         "the port with: ls /dev/serial/by-id/"),
        ("Permission denied on serial port",
         "Add your user to the dialout group: sudo usermod -aG dialout $USER, then log out and back in."),
        ("Web page not loading",
         "Check that the server is running and the port is not blocked by a firewall. "
         "Try: sudo ufw allow 8888/tcp"),
        ("Gauges not updating",
         "Open browser developer console (F12) and check for WebSocket connection errors. "
         "Verify the server IP and port are correct."),
        ("Multiple /dev/ttyUSB devices",
         "Use the /dev/serial/by-id/ path which is unique to each USB-serial adapter. "
         "This prevents confusion when multiple USB devices are connected."),
        ("Server crashes on startup",
         "Check the log output for errors. Common causes: wrong Python version (need 3.9+), "
         "missing dependencies (re-run ./setup.sh), or serial port already in use by another program."),
        ("High CPU usage",
         "Increase polling.idle_interval in config.yaml to reduce serial polling frequency when idle. "
         "The default 1.0 second should be fine for most setups."),
    ]

    for problem, solution in issues:
        story.append(KeepTogether([
            Paragraph(f"<b>Problem:</b> {problem}", style_body),
            Paragraph(f"<b>Solution:</b> {solution}", style_body),
            Spacer(1, 8),
        ]))

    story.append(hr())
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "For additional help, open an issue on the GitHub repository.",
        style_body,
    ))
    story.append(Spacer(1, 30))
    story.append(Paragraph(
        "73 de OH2GEK &amp; VU2CPL",
        ParagraphStyle("Footer", fontName="Helvetica-Bold", fontSize=12,
                       textColor=ACCENT, alignment=TA_CENTER),
    ))

    # Build
    doc.build(story)
    print(f"PDF created: {output_path}")


if __name__ == "__main__":
    build_pdf("docs/SPE_Remote_Control_User_Guide.pdf")
