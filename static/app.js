const $ = (id) => document.getElementById(id);
let accountChart;
let quotePrice = null;
let quotedSymbol = "";
let quoteRequestId = 0;
let quoteTimer;
let searchTimer;
let searchRequestId = 0;
let activeSuggestion = -1;
const quotePromises = new Map();
const quoteCache = new Map();
let selectedSide = "buy";

function money(value) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);
}

function dateLabel(value) {
  return new Date(`${value}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The request failed.");
  return data;
}

function renderAccountChart(history) {
  const canvas = $("stats-chart");
  if (!canvas || typeof Chart === "undefined") return;
  if (accountChart) accountChart.destroy();

  const points = history || [];
  if (!points.length) return;
  const context = canvas.getContext("2d");
  const gradient = context.createLinearGradient(0, 0, 0, 280);
  gradient.addColorStop(0, "rgba(82, 121, 111, 0.22)");
  gradient.addColorStop(1, "rgba(82, 121, 111, 0.015)");
  accountChart = new Chart(context, {
    type: "line",
    data: {
      labels: points.map((point) => point.date),
      datasets: [{
        label: "Account value",
        data: points.map((point) => point.equity),
        borderColor: "#52796f",
        backgroundColor: gradient,
        borderWidth: 2.5,
        fill: true,
        tension: 0.35,
        pointRadius: 0,
        pointHoverRadius: 5,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#2f3e46",
          padding: 11,
          displayColors: false,
          callbacks: {
            title: (items) => dateLabel(items[0].label),
            label: (item) => money(item.raw),
          },
        },
      },
      scales: {
        x: {
          type: "category",
          grid: { display: false },
          border: { display: false },
          ticks: {
            color: "#82918b",
            maxTicksLimit: 6,
            maxRotation: 0,
            callback: (value, index) => dateLabel(points[index].date),
          },
        },
        y: {
          grid: { color: "rgba(47, 62, 70, 0.09)" },
          border: { display: false },
          ticks: {
            color: "#82918b",
            maxTicksLimit: 5,
            callback: (value) => `$${Number(value).toLocaleString("en-US", { notation: "compact" })}`,
          },
        },
      },
    },
  });
}

function renderDashboard(data) {
  $("account-equity").textContent = money(data.equity);
  $("account-cash").textContent = money(data.cash);
  const history = data.history || [];
  const firstValue = history[0]?.equity ?? data.equity;
  const change = data.equity - firstValue;
  const changePercent = firstValue ? (change / firstValue) * 100 : 0;
  const changeEl = $("account-change");
  changeEl.textContent = `${change >= 0 ? "+" : "−"}${money(Math.abs(change))} (${change >= 0 ? "+" : "−"}${Math.abs(changePercent).toFixed(2)}%)`;
  changeEl.classList.toggle("negative", change < 0);
  changeEl.classList.toggle("positive", change >= 0);
  $("account-caption").textContent = "Cash plus the current value of your stocks";

  renderAccountChart(history);
  renderTrades(data.trades || []);
}

function renderTrades(trades) {
  const list = $("trade-history-list");
  $("trade-history-count").textContent = `${trades.length} ${trades.length === 1 ? "TRADE" : "TRADES"}`;
  list.replaceChildren();
  if (!trades.length) {
    const empty = document.createElement("p");
    empty.className = "trade-history-empty";
    empty.textContent = "Your trades will appear here after you place one.";
    list.append(empty);
    return;
  }

  trades.forEach((trade) => {
    const row = document.createElement("article");
    row.className = "trade-history-row";
    const badge = document.createElement("span");
    badge.className = `trade-history-badge ${trade.side}`;
    badge.textContent = trade.side === "buy" ? "B" : "S";

    const details = document.createElement("div");
    details.className = "trade-history-details";
    const title = document.createElement("strong");
    title.textContent = `${trade.side.toUpperCase()} ${trade.symbol}`;
    const meta = document.createElement("span");
    meta.textContent = `${Number(trade.quantity).toLocaleString("en-US")} shares · ${dateLabel(trade.date)}`;
    details.append(title, meta);

    const amount = document.createElement("strong");
    amount.className = `trade-history-amount ${trade.side}`;
    const sign = trade.side === "buy" ? "−" : "+";
    amount.textContent = `${sign}${money(trade.quantity * trade.price)}`;
    row.append(badge, details, amount);
    list.append(row);
  });
}

function clearQuote(message = "Enter a ticker to load its market quote.") {
  quotePrice = null;
  quotedSymbol = "";
  $("demo-quote").textContent = message;
  updateTradeEstimate();
}

function hideSuggestions() {
  const input = $("trade-symbol");
  const list = $("symbol-suggestions");
  list.hidden = true;
  list.replaceChildren();
  input.setAttribute("aria-expanded", "false");
  input.removeAttribute("aria-activedescendant");
  activeSuggestion = -1;
}

async function searchSymbols(query) {
  const requestId = ++searchRequestId;
  if (!query.trim()) {
    hideSuggestions();
    return;
  }
  try {
    const data = await api(`/api/symbol-search?q=${encodeURIComponent(query.trim())}`);
    if (requestId !== searchRequestId || $("trade-symbol").value.trim() !== query.trim()) return;
    const list = $("symbol-suggestions");
    list.replaceChildren();
    (data.results || []).forEach((item, index) => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "symbol-suggestion";
      option.id = `symbol-option-${index}`;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      const symbol = document.createElement("strong");
      symbol.textContent = item.symbol;
      const details = document.createElement("span");
      details.textContent = [item.name, item.exchange].filter(Boolean).join(" · ");
      option.append(symbol, details);
      option.addEventListener("pointerenter", () => warmQuote(item.symbol));
      option.addEventListener("mousedown", (event) => event.preventDefault());
      option.addEventListener("click", () => selectSymbol(item));
      list.append(option);
    });
    if (list.childElementCount) {
      list.hidden = false;
      $("trade-symbol").setAttribute("aria-expanded", "true");
    } else {
      hideSuggestions();
    }
  } catch {
    if (requestId === searchRequestId) hideSuggestions();
  }
}

function selectSymbol(item) {
  $("trade-symbol").value = item.symbol;
  hideSuggestions();
  clearTimeout(quoteTimer);
  lookupQuote(item.symbol, item.name);
}

function getQuote(symbol) {
  const cached = quoteCache.get(symbol);
  if (cached && cached.expiresAt > Date.now()) return Promise.resolve(cached.quote);
  if (quotePromises.has(symbol)) return quotePromises.get(symbol);
  const promise = api(`/api/quote/${encodeURIComponent(symbol)}`)
    .then((quote) => {
      quoteCache.set(symbol, { quote, expiresAt: Date.now() + 60_000 });
      return quote;
    })
    .finally(() => quotePromises.delete(symbol));
  quotePromises.set(symbol, promise);
  return promise;
}

function warmQuote(symbol) {
  getQuote(symbol).catch(() => {});
}

function moveSuggestion(delta) {
  const list = $("symbol-suggestions");
  const options = [...list.querySelectorAll(".symbol-suggestion")];
  if (!options.length) return false;
  activeSuggestion = activeSuggestion < 0
    ? (delta > 0 ? 0 : options.length - 1)
    : (activeSuggestion + delta + options.length) % options.length;
  options.forEach((option, index) => {
    const active = index === activeSuggestion;
    option.classList.toggle("active", active);
    option.setAttribute("aria-selected", String(active));
  });
  $("trade-symbol").setAttribute("aria-activedescendant", options[activeSuggestion].id);
  options[activeSuggestion].scrollIntoView({ block: "nearest" });
  return true;
}

async function lookupQuote(rawSymbol, displayName = "") {
  const symbol = rawSymbol.trim().toUpperCase();
  const requestId = ++quoteRequestId;
  if (!symbol) {
    clearQuote();
    return;
  }

  quotePrice = null;
  quotedSymbol = "";
  const loadingName = document.createElement("span");
  loadingName.textContent = displayName || "Loading company details…";
  const loadingStatus = document.createElement("span");
  loadingStatus.textContent = "Loading quote…";
  $("demo-quote").replaceChildren(document.createTextNode(`${symbol} · `), loadingName, loadingStatus);
  updateTradeEstimate();
  try {
    const quote = await getQuote(symbol);
    if (requestId !== quoteRequestId || $("trade-symbol").value.trim().toUpperCase() !== quote.symbol) return;
    quotePrice = quote.price;
    quotedSymbol = quote.symbol;
    const name = document.createElement("span");
    name.textContent = quote.name;
    const price = document.createElement("strong");
    price.textContent = money(quote.price);
    const change = document.createElement("span");
    change.textContent = `${quote.change_percent >= 0 ? "+" : ""}${quote.change_percent.toFixed(2)}% over 30 days`;
    change.className = quote.change_percent >= 0 ? "positive" : "negative";
    $("demo-quote").replaceChildren(document.createTextNode(`${quote.symbol} · `), name, price, change);
  } catch (error) {
    if (requestId !== quoteRequestId) return;
    clearQuote(error.message);
  }
  updateTradeEstimate();
}

function updateTradeEstimate() {
  const symbol = $("trade-symbol").value.trim().toUpperCase();
  const quantity = Number($("trade-quantity").value);
  const validQuote = quotePrice !== null && symbol === quotedSymbol;
  $("trade-estimate").textContent = validQuote && quantity > 0
    ? money(quantity * quotePrice)
    : "Look up a stock and enter shares";
  $("trade-submit").disabled = !validQuote || !Number.isFinite(quantity) || quantity <= 0;
  $("trade-submit").innerHTML = `Place ${selectedSide} order <span>${selectedSide === "buy" ? "↗" : "↘"}</span>`;
}

async function loadDashboard() {
  try {
    const data = await api("/api/dashboard");
    renderDashboard(data);
  } catch (error) {
    $("account-caption").textContent = error.message;
    $("account-cash").textContent = "Unavailable";
    $("account-equity").textContent = "Unavailable";
  }
}

$("trade-symbol").addEventListener("input", () => {
  quoteRequestId += 1;
  clearQuote();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => searchSymbols($("trade-symbol").value), 180);
});
$("trade-symbol").addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown" && moveSuggestion(1)) event.preventDefault();
  else if (event.key === "ArrowUp" && moveSuggestion(-1)) event.preventDefault();
  else if (event.key === "Escape") hideSuggestions();
  else if (event.key === "Enter") {
    event.preventDefault();
    const selected = $("symbol-suggestions").querySelectorAll(".symbol-suggestion")[activeSuggestion];
    if (selected) selected.click();
    else if ($("trade-symbol").value.trim()) lookupQuote($("trade-symbol").value);
  }
});
$("trade-symbol").addEventListener("blur", () => setTimeout(hideSuggestions, 120));
$("trade-quantity").addEventListener("input", updateTradeEstimate);

document.querySelectorAll(".trade-type-button").forEach((button) => {
  button.addEventListener("click", () => {
    selectedSide = button.dataset.side;
    document.querySelectorAll(".trade-type-button").forEach((option) => {
      const active = option === button;
      option.classList.toggle("active", active);
      option.setAttribute("aria-pressed", String(active));
    });
    updateTradeEstimate();
  });
});

const now = new Date();
const today = new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
const oldest = new Date(now.getTime() - 30 * 86_400_000 - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
$("trade-date").value = today;
$("trade-date").max = today;
$("trade-date").min = oldest;

$("trade-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (quotePrice === null || $("trade-symbol").value.trim().toUpperCase() !== quotedSymbol) {
    lookupQuote($("trade-symbol").value);
    $("trade-note").textContent = "Load a valid stock quote before placing the trade.";
    return;
  }
  const payload = {
    symbol: $("trade-symbol").value.trim().toUpperCase(),
    quantity: $("trade-quantity").value,
    date: $("trade-date").value,
    side: selectedSide,
  };
  $("trade-submit").disabled = true;
  $("trade-note").textContent = "Submitting trade…";
  try {
    const result = await api("/api/trades", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("trade-note").textContent = result.message;
    $("trade-quantity").value = "";
    updateTradeEstimate();
    loadDashboard();
  } catch (error) {
    $("trade-note").textContent = error.message;
    updateTradeEstimate();
  }
});

loadDashboard();
setInterval(loadDashboard, 60_000);
