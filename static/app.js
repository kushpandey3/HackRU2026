
const chartCanvas = document.getElementById("stats-chart");
const sampleValues = [
 100000, 100420, 100180, 100860, 101120, 100740, 101380, 101050, 101720, 101480,
 102060, 101890, 102440, 102110, 102780, 102520, 103160, 102940, 103520, 103250,
 103880, 103610, 104120, 103940, 104460, 104180, 104720, 104510, 104060, 104280,
];


const sampleLabels = sampleValues.map((_, index) => {
 const day = new Date();
 day.setDate(day.getDate() - (sampleValues.length - 1 - index));
 return day;
});


const chartContext = chartCanvas.getContext("2d");
const chartFill = chartContext.createLinearGradient(0, 0, 0, 280);
chartFill.addColorStop(0, "rgba(82, 121, 111, 0.22)");
chartFill.addColorStop(1, "rgba(82, 121, 111, 0.015)");


new Chart(chartContext, {
 type: "line",
 data: {
   labels: sampleLabels,
   datasets: [{
     label: "Account value",
     data: sampleValues,
     borderColor: "#52796f",
     backgroundColor: chartFill,
     borderWidth: 2.5,
     fill: true,
     tension: 0.35,
     pointRadius: 0,
     pointHoverRadius: 5,
     pointHoverBackgroundColor: "#52796f",
     pointHoverBorderColor: "#ffffff",
     pointHoverBorderWidth: 2,
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
         title(items) {
           return sampleLabels[items[0].dataIndex].toLocaleDateString("en-US", {
             month: "short", day: "numeric",
           });
         },
         label(item) {
           return new Intl.NumberFormat("en-US", {
             style: "currency", currency: "USD",
           }).format(item.raw);
         },
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
         callback(value, index) {
           return sampleLabels[index].toLocaleDateString("en-US", {
             month: "short", day: "numeric",
           });
         },
       },
     },
     y: {
       suggestedMin: 99000,
       suggestedMax: 106000,
       grid: { color: "rgba(47, 62, 70, 0.09)" },
       border: { display: false },
       ticks: {
         color: "#82918b",
         maxTicksLimit: 5,
         callback(value) {
           return `$${Number(value).toLocaleString("en-US", { notation: "compact" })}`;
         },
       },
     },
   },
 },
});


// Demo-only controls for the order ticket. Prices are illustrative and not live quotes.
const tradeForm = document.getElementById("trade-form");
const tradeSymbol = document.getElementById("trade-symbol");
const tradeQuantity = document.getElementById("trade-quantity");
const tradeDate = document.getElementById("trade-date");
const tradeEstimate = document.getElementById("trade-estimate");
const tradeSubmit = document.getElementById("trade-submit");
const tradeNote = document.getElementById("trade-note");
const demoQuote = document.getElementById("demo-quote");
const demoPrices = { AAPL: 189.84, MSFT: 421.12, NVDA: 118.42, TSLA: 248.50, AMZN: 187.35 };
let selectedSide = "buy";
const tradeHistoryList = document.getElementById("trade-history-list");
const tradeHistoryCount = document.getElementById("trade-history-count");
const tradeHistoryKey = "paperTradingDemoHistory";


const today = new Date();
const todayInput = new Date(today.getTime() - today.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
const oldestInput = new Date(today.getTime() - 30 * 86_400_000 - today.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
tradeDate.value = todayInput;
tradeDate.max = todayInput;
tradeDate.min = oldestInput;


function updateTradeEstimate() {
 const symbol = tradeSymbol.value.trim().toUpperCase();
 const quantity = Number(tradeQuantity.value);
 const price = demoPrices[symbol] || 150;
 const quoteSymbol = document.createTextNode(symbol || "STOCK");
 const quoteLabel = document.createElement("span");
 quoteLabel.textContent = "DEMO PRICE";
 const quotePrice = document.createElement("strong");
 quotePrice.textContent = `$${price.toFixed(2)}`;
 demoQuote.replaceChildren(quoteSymbol, quoteLabel, quotePrice);
 tradeEstimate.textContent = new Intl.NumberFormat("en-US", {
   style: "currency", currency: "USD",
 }).format(Number.isFinite(quantity) ? quantity * price : 0);
 tradeSubmit.innerHTML = `Place ${selectedSide} order <span>${selectedSide === "buy" ? "↗" : "↘"}</span>`;
}


function readDemoTrades() {
 try {
   return JSON.parse(localStorage.getItem(tradeHistoryKey) || "[]");
 } catch {
   return [];
 }
}


function renderDemoTrades() {
 if (!tradeHistoryList || !tradeHistoryCount) return;
 const trades = readDemoTrades();
 tradeHistoryCount.textContent = `${trades.length} ${trades.length === 1 ? "TRADE" : "TRADES"}`;
 tradeHistoryList.replaceChildren();


 if (trades.length === 0) {
   const empty = document.createElement("p");
   empty.className = "trade-history-empty";
   empty.textContent = "Your demo trades will appear here after you place one.";
   tradeHistoryList.append(empty);
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
   meta.textContent = `${trade.quantity} shares · ${trade.date}`;
   details.append(title, meta);


   const amount = document.createElement("strong");
   amount.className = `trade-history-amount ${trade.side}`;
   amount.textContent = `${trade.side === "buy" ? "−" : "+"}${new Intl.NumberFormat("en-US", {
     style: "currency", currency: "USD",
   }).format(trade.quantity * trade.price)}`;
   row.append(badge, details, amount);
   tradeHistoryList.append(row);
 });
}


document.querySelectorAll(".trade-type-button").forEach((button) => {
 button.addEventListener("click", () => {
   selectedSide = button.dataset.side;
   document.querySelectorAll(".trade-type-button").forEach((option) => {
     const active = option === button;
     option.classList.toggle("active", active);
     option.setAttribute("aria-pressed", String(active));
   });
   if (tradeNote) tradeNote.textContent = "Demo only · orders are not submitted or saved";
   updateTradeEstimate();
 });
});


tradeSymbol.addEventListener("input", updateTradeEstimate);
tradeQuantity.addEventListener("input", updateTradeEstimate);
tradeForm.addEventListener("submit", (event) => {
 event.preventDefault();
 const symbol = tradeSymbol.value.trim().toUpperCase() || "STOCK";
 const quantity = Number(tradeQuantity.value);
 if (!Number.isFinite(quantity) || quantity <= 0) {
   if (tradeNote) tradeNote.textContent = "Enter a share amount greater than zero.";
   return;
 }
 const price = demoPrices[symbol] || 150;
 const trades = readDemoTrades();
 trades.unshift({ symbol, side: selectedSide, quantity, price, date: tradeDate.value });
 try {
   localStorage.setItem(tradeHistoryKey, JSON.stringify(trades));
 } catch {
   if (tradeNote) tradeNote.textContent = "Could not save this demo trade in this browser.";
   return;
 }
 if (tradeNote) tradeNote.textContent = `Demo ${selectedSide} recorded: ${quantity} ${symbol} at $${price.toFixed(2)}.`;
 renderDemoTrades();
});


updateTradeEstimate();
renderDemoTrades();


