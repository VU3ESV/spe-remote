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
        const d = JSON.parse(evt.data);
        if (d.power_result) {
          handlePowerResult(d);
        } else {
          updateUI(d);
        }
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

  // Power on/off with confirmation and busy state
  window.sendPower = function (cmd) {
    const label = cmd === "power_on" ? "POWER ON" : "POWER OFF";
    if (!confirm(`Are you sure you want to ${label} the amplifier?`)) return;

    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(cmd);
      // Set busy state on both buttons
      document.getElementById("btnPowerOn").classList.add("busy");
      document.getElementById("btnPowerOff").classList.add("busy");
      // Auto-clear busy after 5s safety timeout
      setTimeout(clearPowerBusy, 5000);
    }
  };

  function clearPowerBusy() {
    document.getElementById("btnPowerOn").classList.remove("busy");
    document.getElementById("btnPowerOff").classList.remove("busy");
  }

  function handlePowerResult(d) {
    clearPowerBusy();
    const alertBar = document.getElementById("alertBar");
    const action = d.power_result === "power_on" ? "POWER ON" : "POWER OFF";
    if (d.status === "ok") {
      alertBar.className = "alert-bar power-ok";
      alertBar.textContent = `${action} command sent successfully`;
    } else {
      alertBar.className = "alert-bar error";
      alertBar.textContent = `${action} failed — check serial connection`;
    }
    // Clear the alert after 4 seconds
    setTimeout(() => {
      alertBar.className = "alert-bar clear";
      alertBar.textContent = "";
    }, 4000);
  }

  // --- Model auto-detection ---
  // Maps the SPE ID code (data[1] in the status string) to display name,
  // power-bar full-scale wattage, tick labels, and whether to show the
  // 2K-FA-only extra temp readings (lower heatsink + combiner).
  const MODELS = {
    "13K": { name: "SPE 1.3K-FA", maxW: 1500, ticks: ["0","250","500","750","1.0k","1.3k","1.5k"], extraTemps: false },
    "15K": { name: "SPE 1.5K-FA", maxW: 1500, ticks: ["0","250","500","750","1.0k","1.3k","1.5k"], extraTemps: false },
    "20K": { name: "SPE 2K-FA",   maxW: 2000, ticks: ["0","250","500","1.0k","1.3k","1.5k","2.0k"], extraTemps: true },
  };
  const MODEL_DEFAULT = { name: "SPE Expert", maxW: 1500,
    ticks: ["0","250","500","750","1.0k","1.3k","1.5k"], extraTemps: false };

  let currentModelKey = "";
  let currentModel = MODEL_DEFAULT;

  function applyModel(modelCode) {
    if (modelCode === currentModelKey) return;  // No-op if unchanged
    currentModelKey = modelCode;
    currentModel = MODELS[modelCode] || MODEL_DEFAULT;

    // Header label
    document.getElementById("modelLabel").textContent = currentModel.name;

    // Power-bar tick labels
    const ticksEl = document.getElementById("powerTicks");
    if (ticksEl) {
      ticksEl.innerHTML = currentModel.ticks.map(t => `<span>${t}</span>`).join("");
    }

    // 2K-FA extra temps (lower heatsink + combiner)
    const extraEl = document.getElementById("extraTemps");
    if (extraEl) extraEl.style.display = currentModel.extraTemps ? "" : "none";
  }

  // --- UI Update ---
  function updateUI(d) {
    // Model auto-detection (header, power scale, extra temps)
    if (d.model !== undefined) applyModel(d.model || "");

    // Power
    const pOut = parseInt(d.p_out, 10) || 0;
    document.getElementById("powerValue").textContent = pOut;
    const pct = Math.min((pOut / currentModel.maxW) * 100, 100);
    document.getElementById("powerBar").style.width = pct + "%";

    // SWR
    const swr = parseFloat(d.swr) || 1;
    const swrDisplay = swr > 0 ? `SWR: 1:${d.swr}` : "SWR: ---";
    document.getElementById("swrDisplay").textContent = swrDisplay;
    document.getElementById("valSWR").textContent = `1:${d.swr}`;

    // Drain, temp, voltage. The server stamps temperature_unit ("C"/"F")
    // onto every state — the amp itself doesn't tell us which unit it
    // reports in, so this comes from config.yaml on the Pi.
    const unit = d.temperature_unit === "F" ? "F" : "C";
    document.getElementById("valDrain").textContent = d.drain;
    document.getElementById("valTemp").innerHTML = `${d.pa_temp}&deg;${unit}`;
    document.getElementById("valVolt").textContent = d.voltage;

    // 2K-FA extra temps (only rendered if applyModel revealed the row)
    if (currentModel.extraTemps) {
      const lwr = document.getElementById("valTempLower");
      const cmb = document.getElementById("valTempCombiner");
      if (lwr && d.pa_temp_lower !== undefined) lwr.textContent = d.pa_temp_lower;
      if (cmb && d.pa_temp_combiner !== undefined) cmb.textContent = d.pa_temp_combiner;
      // Update the °C / °F suffix on both extra-temp chips.
      document.querySelectorAll(".tempUnitSuffix").forEach(el => el.textContent = unit);
    }

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
    // Scale the temperature gauge by unit. 80°C ≈ 176°F so the Fahrenheit
    // dial gets a 0–180 range; warning thresholds in tempColors are
    // proportional, so they convert automatically.
    const tempMax = unit === "F" ? 180 : 80;
    drawGauge("gaugeTemp", parseFloat(d.pa_temp) || 0, 0, tempMax, tempColors);
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
