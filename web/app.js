// SPE Remote Control - WebSocket Client
(function () {
  "use strict";

  // --- WebSocket ---
  let ws = null;
  let reconnectDelay = 1000;
  const MAX_RECONNECT = 16000;

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => {
      reconnectDelay = 1000;
      setConnected(true);
    };

    ws.onclose = () => {
      setConnected(false);
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT);
    };

    ws.onerror = () => ws.close();

    ws.onmessage = (evt) => {
      try {
        updateUI(JSON.parse(evt.data));
      } catch (e) {
        console.error("Parse error:", e);
      }
    };
  }

  function setConnected(ok) {
    document.getElementById("statusDot").classList.toggle("connected", ok);
    document.getElementById("statusText").textContent = ok ? "Connected" : "Disconnected";
  }

  // Expose for inline onclick
  window.sendCmd = function (cmd) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(cmd);
    }
  };

  // --- UI Update ---
  function updateUI(d) {
    // Power
    const pOut = parseInt(d.p_out, 10) || 0;
    document.getElementById("powerValue").textContent = pOut;
    const pct = Math.min((pOut / 1500) * 100, 100);
    document.getElementById("powerBar").style.width = pct + "%";

    // SWR
    const swr = parseFloat(d.swr) || 1;
    const swrDisplay = swr > 0 ? `SWR: 1:${d.swr}` : "SWR: ---";
    document.getElementById("swrDisplay").textContent = swrDisplay;
    document.getElementById("valSWR").textContent = `1:${d.swr}`;

    // Drain, temp, voltage
    document.getElementById("valDrain").textContent = d.drain;
    document.getElementById("valTemp").innerHTML = `${d.pa_temp}&deg;C`;
    document.getElementById("valVolt").textContent = d.voltage;

    // Info chips
    const txEl = document.getElementById("txStatus");
    const chipTX = document.getElementById("chipTX");
    txEl.textContent = d.tx_status;
    chipTX.classList.toggle("tx-on", d.tx_status === "TX");
    chipTX.classList.toggle("rx-on", d.tx_status === "RX");

    document.getElementById("bandDisplay").textContent = d.band;
    document.getElementById("antDisplay").textContent = d.tx_antenna;
    document.getElementById("inputDisplay").textContent = d.input;
    document.getElementById("levelDisplay").textContent = d.p_level;

    // Operate button highlight
    document.getElementById("btnOper").classList.toggle("active", d.op_status === "Oper");

    // Alerts
    const alertBar = document.getElementById("alertBar");
    if (d.error && d.error.trim()) {
      alertBar.className = "alert-bar error";
      alertBar.textContent = d.error;
    } else if (d.warnings && d.warnings.trim()) {
      alertBar.className = "alert-bar warning";
      alertBar.textContent = d.warnings;
    } else {
      alertBar.className = "alert-bar clear";
      alertBar.textContent = "";
    }

    // Draw gauges
    drawGauge("gaugeSWR", parseFloat(d.swr) || 1, 1, 3.5, swrColors);
    drawGauge("gaugeDrain", parseFloat(d.drain) || 0, 0, 60, drainColors);
    drawGauge("gaugeTemp", parseFloat(d.pa_temp) || 0, 0, 80, tempColors);
    drawGauge("gaugeVolt", parseFloat(d.voltage) || 0, 40, 60, voltColors);
  }

  // --- Gauge Drawing ---
  const swrColors = [
    [0, "#4caf50"], [0.4, "#4caf50"], [0.6, "#ff9800"], [0.8, "#f44336"], [1, "#f44336"]
  ];
  const drainColors = [
    [0, "#00bcd4"], [0.7, "#00bcd4"], [0.85, "#ff9800"], [1, "#f44336"]
  ];
  const tempColors = [
    [0, "#00bcd4"], [0.5, "#4caf50"], [0.75, "#ff9800"], [1, "#f44336"]
  ];
  const voltColors = [
    [0, "#f44336"], [0.2, "#ff9800"], [0.3, "#4caf50"], [0.7, "#4caf50"], [0.85, "#ff9800"], [1, "#f44336"]
  ];

  function drawGauge(canvasId, value, min, max, colorStops) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const w = canvas.width;
    const h = canvas.height;
    const cx = w / 2;
    const cy = h - 5;
    const r = Math.min(cx, cy) - 8;

    ctx.clearRect(0, 0, w, h);

    const startAngle = Math.PI;
    const endAngle = 2 * Math.PI;
    const range = max - min;
    const norm = Math.max(0, Math.min(1, (value - min) / range));
    const valueAngle = startAngle + norm * Math.PI;

    // Background arc
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, endAngle);
    ctx.lineWidth = 10;
    ctx.strokeStyle = "#1a1a2e";
    ctx.stroke();

    // Colored arc
    const grad = ctx.createLinearGradient(cx - r, cy, cx + r, cy);
    for (const [stop, color] of colorStops) {
      grad.addColorStop(stop, color);
    }
    ctx.beginPath();
    ctx.arc(cx, cy, r, startAngle, valueAngle);
    ctx.lineWidth = 10;
    ctx.lineCap = "round";
    ctx.strokeStyle = grad;
    ctx.stroke();

    // Needle
    const nx = cx + (r - 5) * Math.cos(valueAngle);
    const ny = cy + (r - 5) * Math.sin(valueAngle);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(nx, ny);
    ctx.lineWidth = 2;
    ctx.strokeStyle = "#e0e0e0";
    ctx.stroke();

    // Center dot
    ctx.beginPath();
    ctx.arc(cx, cy, 3, 0, 2 * Math.PI);
    ctx.fillStyle = "#e0e0e0";
    ctx.fill();
  }

  // --- Init ---
  connect();
})();
