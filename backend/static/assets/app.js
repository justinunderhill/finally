const state = {
  prices: {},
  previousPrices: {},
  histories: {},
  selected: "AAPL",
  portfolio: null,
  portfolioHistory: [],
  watchlist: [],
  lastTradeSide: "buy",
};

const els = {
  totalValue: document.getElementById("totalValue"),
  cashBalance: document.getElementById("cashBalance"),
  portfolioPl: document.getElementById("portfolioPl"),
  connectionDot: document.getElementById("connectionDot"),
  connectionText: document.getElementById("connectionText"),
  watchlist: document.getElementById("watchlist"),
  selectedTicker: document.getElementById("selectedTicker"),
  selectedMeta: document.getElementById("selectedMeta"),
  selectedPrice: document.getElementById("selectedPrice"),
  priceChart: document.getElementById("priceChart"),
  pnlChart: document.getElementById("pnlChart"),
  positionsTable: document.getElementById("positionsTable"),
  heatmap: document.getElementById("heatmap"),
  tradeForm: document.getElementById("tradeForm"),
  tradeTicker: document.getElementById("tradeTicker"),
  tradeQuantity: document.getElementById("tradeQuantity"),
  tradeStatus: document.getElementById("tradeStatus"),
  watchlistForm: document.getElementById("watchlistForm"),
  watchTicker: document.getElementById("watchTicker"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  chatMessages: document.getElementById("chatMessages"),
};

function money(value) {
  return Number(value || 0).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

function signedMoney(value) {
  const n = Number(value || 0);
  return `${n >= 0 ? "+" : ""}${money(n)}`;
}

function setConnection(status) {
  els.connectionDot.className = `dot dot-${status}`;
  els.connectionText.textContent =
    status === "green" ? "Connected" : status === "yellow" ? "Reconnecting" : "Disconnected";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

async function refreshAll() {
  const [watchlist, portfolio, history] = await Promise.all([
    api("/api/watchlist"),
    api("/api/portfolio"),
    api("/api/portfolio/history"),
  ]);
  state.watchlist = watchlist.map((item) => item.ticker);
  state.portfolio = portfolio;
  state.portfolioHistory = history;
  for (const item of watchlist) {
    if (item.price != null) {
      applyPrice(item.ticker, item);
    }
  }
  renderAll();
}

function applyPrice(ticker, update) {
  const price = Number(update.price);
  state.previousPrices[ticker] = state.prices[ticker]?.price;
  state.prices[ticker] = update;
  if (!state.histories[ticker]) {
    state.histories[ticker] = [];
  }
  if (Number.isFinite(price)) {
    state.histories[ticker].push(price);
    state.histories[ticker] = state.histories[ticker].slice(-120);
  }
}

function startStream() {
  const events = new EventSource("/api/stream/prices");
  events.onopen = () => setConnection("green");
  events.onerror = () => setConnection("yellow");
  events.onmessage = (event) => {
    const updates = JSON.parse(event.data);
    for (const [ticker, update] of Object.entries(updates)) {
      applyPrice(ticker, update);
    }
    renderWatchlist();
    renderSelected();
    drawPriceChart();
  };
}

function renderAll() {
  renderHeader();
  renderWatchlist();
  renderSelected();
  renderPositions();
  renderHeatmap();
  drawPriceChart();
  drawPnlChart();
}

function renderHeader() {
  const portfolio = state.portfolio;
  if (!portfolio) return;
  els.totalValue.textContent = money(portfolio.total_value);
  els.cashBalance.textContent = money(portfolio.cash_balance);
  els.portfolioPl.textContent = signedMoney(portfolio.unrealized_pl);
  els.portfolioPl.className = portfolio.unrealized_pl >= 0 ? "num-up" : "num-down";
}

function renderWatchlist() {
  const tickers = state.watchlist.length ? state.watchlist : Object.keys(state.prices);
  els.watchlist.innerHTML = "";
  if (!tickers.length) {
    els.watchlist.innerHTML = '<div class="empty-state">No tickers</div>';
    return;
  }
  for (const ticker of tickers) {
    const update = state.prices[ticker] || {};
    const previous = state.previousPrices[ticker];
    const directionClass =
      previous == null || previous === update.price
        ? ""
        : update.price > previous
          ? " flash-up"
          : " flash-down";
    const row = document.createElement("div");
    row.className = `watch-row ${ticker === state.selected ? "active" : ""}`;
    row.innerHTML = `
      <div class="ticker">${ticker}</div>
      <div class="price${directionClass}">${update.price ? money(update.price) : "--"}</div>
      <div class="${update.change_percent >= 0 ? "num-up" : "num-down"}">${formatPercent(update.change_percent)}</div>
      <div class="spark">${sparklineSvg(state.histories[ticker] || [])}</div>
      <button class="remove-button" title="Remove ${ticker}" data-remove="${ticker}">x</button>
    `;
    row.addEventListener("click", (event) => {
      if (event.target.dataset.remove) return;
      selectTicker(ticker);
    });
    row.querySelector("[data-remove]").addEventListener("click", async () => {
      await removeTicker(ticker);
    });
    els.watchlist.appendChild(row);
  }
}

function renderSelected() {
  const ticker = state.selected;
  const update = state.prices[ticker] || {};
  els.selectedTicker.textContent = ticker;
  els.selectedPrice.textContent = update.price ? money(update.price) : "$0.00";
  els.selectedMeta.textContent = `${formatPercent(update.change_percent)} last move`;
  els.tradeTicker.value = ticker;
}

function renderPositions() {
  const positions = state.portfolio?.positions || [];
  els.positionsTable.innerHTML = "";
  if (!positions.length) {
    els.positionsTable.innerHTML =
      '<tr><td colspan="6" class="empty-cell">No open positions</td></tr>';
    return;
  }
  for (const position of positions) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td><strong>${position.ticker}</strong></td>
      <td>${Number(position.quantity).toFixed(4)}</td>
      <td>${money(position.avg_cost)}</td>
      <td>${money(position.current_price)}</td>
      <td>${money(position.market_value)}</td>
      <td class="${position.unrealized_pl >= 0 ? "num-up" : "num-down"}">${signedMoney(position.unrealized_pl)}</td>
    `;
    els.positionsTable.appendChild(row);
  }
}

function renderHeatmap() {
  const positions = state.portfolio?.positions || [];
  els.heatmap.innerHTML = "";
  if (!positions.length) {
    els.heatmap.innerHTML = '<div class="empty-state">No open positions</div>';
    return;
  }
  const total = positions.reduce((sum, item) => sum + item.market_value, 0) || 1;
  for (const position of positions) {
    const tile = document.createElement("div");
    const gain = position.unrealized_pl >= 0;
    const weight = Math.max(0.16, position.market_value / total);
    tile.className = "heat-tile";
    tile.style.flex = `${weight} 1 0`;
    tile.style.background = gain
      ? `rgba(35, 196, 131, ${Math.min(0.38, 0.14 + weight)})`
      : `rgba(240, 82, 82, ${Math.min(0.38, 0.14 + weight)})`;
    tile.innerHTML = `
      <strong>${position.ticker}</strong>
      <span>${money(position.market_value)}</span>
      <span class="${gain ? "num-up" : "num-down"}">${formatPercent(position.unrealized_pl_percent)}</span>
    `;
    els.heatmap.appendChild(tile);
  }
}

function drawPriceChart() {
  drawLineChart(els.priceChart, state.histories[state.selected] || [], {
    line: "#209dd7",
    fill: "rgba(32, 157, 215, 0.12)",
  });
}

function drawPnlChart() {
  const values = state.portfolioHistory.map((point) => point.total_value);
  drawLineChart(els.pnlChart, values, {
    line: "#ecad0a",
    fill: "rgba(236, 173, 10, 0.12)",
  });
}

function drawLineChart(canvas, values, colors) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * dpr));
  canvas.height = Math.max(1, Math.floor(rect.height * dpr));
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, rect.width, rect.height);

  ctx.strokeStyle = "rgba(71, 85, 105, 0.55)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 4; i += 1) {
    const y = (rect.height / 4) * i;
    ctx.beginPath();
    ctx.moveTo(12, y);
    ctx.lineTo(rect.width - 12, y);
    ctx.stroke();
  }

  if (values.length < 2) {
    ctx.fillStyle = "#8b949e";
    ctx.font = "13px system-ui";
    ctx.fillText("Waiting for data", 16, 28);
    return;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  const xStep = (rect.width - 24) / (values.length - 1);
  const points = values.map((value, index) => ({
    x: 12 + index * xStep,
    y: 12 + (1 - (value - min) / spread) * (rect.height - 24),
  }));

  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.lineTo(points.at(-1).x, rect.height - 12);
  ctx.lineTo(points[0].x, rect.height - 12);
  ctx.closePath();
  ctx.fillStyle = colors.fill;
  ctx.fill();

  ctx.beginPath();
  points.forEach((point, index) => {
    if (index === 0) ctx.moveTo(point.x, point.y);
    else ctx.lineTo(point.x, point.y);
  });
  ctx.strokeStyle = colors.line;
  ctx.lineWidth = 2;
  ctx.stroke();
}

function sparklineSvg(values) {
  if (values.length < 2) return "";
  const width = 88;
  const height = 22;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / spread) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const up = values.at(-1) >= values[0];
  return `<svg viewBox="0 0 ${width} ${height}" width="88" height="22" preserveAspectRatio="none">
    <polyline points="${points}" fill="none" stroke="${up ? "#23c483" : "#f05252"}" stroke-width="2" />
  </svg>`;
}

function formatPercent(value) {
  const n = Number(value || 0);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}

function selectTicker(ticker) {
  state.selected = ticker;
  renderWatchlist();
  renderSelected();
  drawPriceChart();
}

async function removeTicker(ticker) {
  try {
    await api(`/api/watchlist/${ticker}`, { method: "DELETE" });
    await refreshAll();
  } catch (error) {
    els.tradeStatus.textContent = error.message;
  }
}

els.watchlistForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const ticker = els.watchTicker.value.trim().toUpperCase();
  if (!ticker) return;
  try {
    await api("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ ticker }),
    });
    els.watchTicker.value = "";
    await refreshAll();
  } catch (error) {
    els.tradeStatus.textContent = error.message;
  }
});

els.tradeForm.addEventListener("click", (event) => {
  if (event.target.dataset.side) {
    state.lastTradeSide = event.target.dataset.side;
  }
});

els.tradeForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    ticker: els.tradeTicker.value.trim().toUpperCase(),
    quantity: Number(els.tradeQuantity.value),
    side: state.lastTradeSide,
  };
  try {
    const result = await api("/api/portfolio/trade", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.portfolio = result.portfolio;
    els.tradeStatus.textContent = `${payload.side.toUpperCase()} ${payload.quantity} ${payload.ticker} filled`;
    await refreshAll();
  } catch (error) {
    els.tradeStatus.textContent = error.message;
  }
});

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = els.chatInput.value.trim();
  if (!message) return;
  appendMessage("user", message);
  els.chatInput.value = "";
  appendMessage("assistant", "Working...");
  try {
    const response = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    });
    els.chatMessages.lastElementChild.textContent = response.message;
    state.portfolio = response.portfolio;
    await refreshAll();
  } catch (error) {
    els.chatMessages.lastElementChild.textContent = error.message;
  }
});

function appendMessage(role, text) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = text;
  els.chatMessages.appendChild(node);
  els.chatMessages.scrollTop = els.chatMessages.scrollHeight;
}

window.addEventListener("resize", () => {
  drawPriceChart();
  drawPnlChart();
});

appendMessage("assistant", "Portfolio context is loaded. I can analyze holdings and execute simulated trades.");
refreshAll().catch((error) => {
  setConnection("red");
  els.tradeStatus.textContent = error.message;
});
startStream();
