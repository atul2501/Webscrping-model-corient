const form = document.getElementById("search-form");
const statusEl = document.getElementById("status");
const table = document.getElementById("results-table");
const tbody = document.getElementById("results-body");
const emptyStateEl = document.getElementById("empty-state");
const recommendationEl = document.getElementById("recommendation");
const modelInput = document.getElementById("model");
const modelSuggestions = document.getElementById("model-suggestions");
const storageSelect = document.getElementById("storage");
const colourSelect = document.getElementById("colour");
const sourceTogglesEl = document.getElementById("source-toggles");
const budgetMinInput = document.getElementById("budget_min");
const budgetMaxInput = document.getElementById("budget_max");
const budgetSliderFill = document.getElementById("budget-slider-fill");
const budgetMinLabel = document.getElementById("budget-min-label");
const budgetMaxLabel = document.getElementById("budget-max-label");
const emiTenureSelect = document.getElementById("emi_tenure_months");
const downPaymentInput = document.getElementById("down_payment");
const healthIndicatorEl = document.getElementById("health-indicator");
const healthLabelEl = healthIndicatorEl.querySelector(".health-label");
const historyModalOverlay = document.getElementById("history-modal-overlay");
const historyModalSubtitle = document.getElementById("history-modal-subtitle");
const historyModalBody = document.getElementById("history-modal-body");
const historyModalClose = document.getElementById("history-modal-close");

// Holds the last real (live-scraped) search response, so picking a
// Storage/Colour option after a search can re-filter the table instantly
// client-side instead of re-hitting the sources.
let lastModelSearch = null;

// Bumped on every async action that touches #status (the fast model-options
// lookup, and the slow live search). Whichever one started *last* wins the
// right to update the UI when it resolves - otherwise a fast lookup that
// happens to resolve after a search was already kicked off would clobber
// the loading spinner with its own stale "options loaded" message.
let requestToken = 0;

// --- System status indicator (topbar) -----------------------------------
//
// Pings the app's own /health endpoint (checks the DB connection, not just
// that Flask is up) so the topbar reflects real backend state instead of
// being purely decorative.

async function checkHealth() {
  try {
    const response = await fetch("/health");
    const data = await response.json();
    const healthy = response.ok && data.status === "ok" && data.db === "ok";
    healthIndicatorEl.classList.toggle("online", healthy);
    healthIndicatorEl.classList.toggle("offline", !healthy);
    healthLabelEl.textContent = healthy ? "All systems live" : "Degraded";
    healthIndicatorEl.title = healthy
      ? "API and database are reachable"
      : `API reachable, database status: ${data.db || "unknown"}`;
  } catch (err) {
    healthIndicatorEl.classList.remove("online");
    healthIndicatorEl.classList.add("offline");
    healthLabelEl.textContent = "Offline";
    healthIndicatorEl.title = "Could not reach the API";
  }
}

checkHealth();
setInterval(checkHealth, 60000);

function money(value) {
  if (value === null || value === undefined) return "-";
  return "Rs. " + Number(value).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

// The API identifies retailers by their internal slug ("vijay_sales",
// "reliance_digital") - fine as a lookup key, not as something to show a
// user. Mirrors the same "replace('_', ' ').title()" the source-toggle
// buttons already get server-side in index.html.
function formatSourceName(source) {
  if (!source) return "";
  return source.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Mirrors app/pricing/emi.py's reducing-balance formula exactly, so changing
// EMI Tenure or Down Payment can recompute every row's EMI instantly
// client-side instead of re-running the whole search just for that.
function calculateEmiClientSide(financedAmount, tenureMonths, annualRatePercent, noCostEmi) {
  if (!tenureMonths || tenureMonths <= 0) return null;
  const principal = Math.max(financedAmount, 0);

  let monthlyEmi;
  let rateUsed;
  if (noCostEmi || annualRatePercent <= 0) {
    monthlyEmi = principal / tenureMonths;
    rateUsed = 0;
  } else {
    const monthlyRate = annualRatePercent / 12 / 100;
    const growth = Math.pow(1 + monthlyRate, tenureMonths);
    monthlyEmi = (principal * monthlyRate * growth) / (growth - 1);
    rateUsed = annualRatePercent;
  }

  const totalRepayment = monthlyEmi * tenureMonths;
  const totalInterest = Math.max(totalRepayment - principal, 0);

  return {
    tenure_months: tenureMonths,
    annual_rate_percent: rateUsed,
    monthly_emi: Math.round(monthlyEmi * 100) / 100,
    total_repayment: Math.round(totalRepayment * 100) / 100,
    total_interest: Math.round(totalInterest * 100) / 100,
    is_no_cost_emi: Boolean(noCostEmi || annualRatePercent <= 0),
    estimate: true,
  };
}

// --- Budget slider (Flipkart-style dual-handle range) -------------------
//
// Two native <input type="range"> elements stacked on the same track
// (CSS makes everything but each thumb click-through, so both stay
// independently draggable); this just keeps them from crossing, paints the
// coloured fill between them, and keeps the Rs. X - Rs. Y label live.

const BUDGET_MIN_GAP = 1000;

function updateBudgetSliderVisual() {
  const min = Number(budgetMinInput.value);
  const max = Number(budgetMaxInput.value);
  const range = Number(budgetMinInput.max) || 1;

  budgetSliderFill.style.left = `${(min / range) * 100}%`;
  budgetSliderFill.style.right = `${100 - (max / range) * 100}%`;

  budgetMinLabel.textContent = money(min);
  budgetMaxLabel.textContent = max >= range ? `${money(range)}+` : money(max);
}

// A slider sitting at its full range (min at 0, max at the top) means "no
// budget filter" - not literally "between Rs. 0 and Rs. 5,00,000" - so
// those edge positions are sent through as null rather than as bounds.
function getBudgetBounds() {
  const min = Number(budgetMinInput.value);
  const max = Number(budgetMaxInput.value);
  const range = Number(budgetMinInput.max) || 0;
  return {
    min: min > 0 ? min : null,
    max: max < range ? max : null,
  };
}

budgetMinInput.addEventListener("input", () => {
  if (Number(budgetMinInput.value) > Number(budgetMaxInput.value) - BUDGET_MIN_GAP) {
    budgetMinInput.value = Math.max(0, Number(budgetMaxInput.value) - BUDGET_MIN_GAP);
  }
  updateBudgetSliderVisual();
});
budgetMaxInput.addEventListener("input", () => {
  const sliderTop = Number(budgetMaxInput.max);
  if (Number(budgetMaxInput.value) < Number(budgetMinInput.value) + BUDGET_MIN_GAP) {
    budgetMaxInput.value = Math.min(sliderTop, Number(budgetMinInput.value) + BUDGET_MIN_GAP);
  }
  updateBudgetSliderVisual();
});
updateBudgetSliderVisual();

function setStatus(message, isError) {
  stopLoadingStatus();
  statusEl.hidden = !message;
  statusEl.textContent = message || "";
  statusEl.classList.toggle("error", Boolean(isError));
  statusEl.classList.remove("loading");
}

// A search hits three live sites and can take a few seconds - a rotating,
// lightly playful status (with a spinner) makes that wait feel a lot less
// dead than a static "Searching..." that never changes.
const LOADING_MESSAGES = [
  "Hunting down your best deal across Croma, Vijay Sales & Reliance Digital...",
  "Politely asking three different websites for their best price...",
  "Comparing prices so you don't have to...",
  "Crunching EMI numbers and bank offers...",
  "Sniffing out hidden discounts...",
  "Almost there - professional bargain-hunting in progress...",
];
let loadingIntervalId = null;

function startLoadingStatus() {
  statusEl.hidden = false;
  statusEl.classList.remove("error");
  statusEl.classList.add("loading");
  let i = 0;
  const render = () => {
    statusEl.innerHTML = `<span class="spinner"></span><span>${LOADING_MESSAGES[i % LOADING_MESSAGES.length]}</span>`;
    i += 1;
  };
  render();
  loadingIntervalId = setInterval(render, 1800);
}

function stopLoadingStatus() {
  if (loadingIntervalId) {
    clearInterval(loadingIntervalId);
    loadingIntervalId = null;
  }
}

function debounce(fn, delayMs) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

function renderRecommendation(rec, meta) {
  if (!rec) {
    recommendationEl.hidden = true;
    return;
  }
  recommendationEl.hidden = false;
  const lines = [
    `<li><strong>Best current price:</strong> ${formatSourceName(rec.best_current_price.source)} - ${money(rec.best_current_price.amount)}</li>`,
    `<li><strong>Best effective price after offers:</strong> ${formatSourceName(rec.best_effective_price.source)} - ${money(rec.best_effective_price.amount)}</li>`,
  ];
  if (rec.lowest_emi) {
    lines.push(
      `<li><strong>Lowest EMI (${rec.lowest_emi.tenure_months} mo):</strong> ${formatSourceName(rec.lowest_emi.source)} - ${money(rec.lowest_emi.monthly_emi)}/month</li>`
    );
  }
  lines.push(`<li>${rec.reason}</li>`);
  lines.push(
    `<li class="offer-text">Sources: ${meta.sources_succeeded}/${meta.sources_attempted} succeeded &middot; scraped at ${meta.scraped_at || "n/a"}</li>`
  );
  recommendationEl.innerHTML = `<h2>Best deal</h2><ul>${lines.join("")}</ul>`;
}

function renderRows(results) {
  tbody.innerHTML = "";

  if (!results.length) {
    table.hidden = true;
    emptyStateEl.hidden = false;
    return;
  }
  emptyStateEl.hidden = true;
  table.hidden = false;

  // Results arrive (and stay, through client-side filtering) sorted
  // ascending by effective price, so the first row is always the current
  // cheapest - worth calling out visually, not just leaving it implicit.
  results.forEach((row, index) => {
    const tr = document.createElement("tr");
    const isBest = index === 0;
    if (isBest) tr.classList.add("best-row");
    tr.style.animationDelay = `${Math.min(index, 12) * 25}ms`;

    const offersHtml = (row.offers || [])
      .map((o) => `<span class="offer-text">${o.offer_text || o.offer_type}</span>`)
      .join("");

    const emiHtml = row.emi
      ? `${money(row.emi.monthly_emi)}/mo${row.emi.is_no_cost_emi ? " (no-cost)" : ""}<span class="offer-text">estimate, ${row.emi.tenure_months} mo @ ${row.emi.annual_rate_percent}%</span>`
      : "-";

    tr.innerHTML = `
      <td>${formatSourceName(row.source)}${isBest ? '<span class="best-badge">Best</span>' : ""}</td>
      <td>
        ${row.product.brand} ${row.product.model}
        <span class="offer-text">${[row.variant.storage, row.variant.colour].filter(Boolean).join(" / ") || ""}</span>
        <div class="row-links">
          ${row.product_url ? `<a class="source-link-btn" href="${row.product_url}" target="_blank" rel="noopener">View listing<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg></a>` : ""}
          <button type="button" class="source-link-btn history-btn" data-variant-id="${row.variant_id}">History<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 3 3 15 21 15"/><polyline points="7 11 11 7 14 10 20 4"/></svg></button>
        </div>
      </td>
      <td>${money(row.selling_price)}${row.mrp && row.mrp !== row.selling_price ? `<span class="offer-text">MRP ${money(row.mrp)}</span>` : ""}</td>
      <td>${offersHtml || "-"}</td>
      <td><strong>${money(row.effective_price)}</strong></td>
      <td>${emiHtml}</td>
      <td><span class="pill ${row.availability || ""}">${row.availability || "unknown"}</span></td>
      <td>${row.deal_score ?? "-"}</td>
    `;
    tbody.appendChild(tr);
  });
}

// --- Price history modal (chart + drop detection) -----------------------
//
// A hand-rolled SVG line chart, not a charting library - this project has
// zero JS dependencies (no package.json/build step at all), and a handful
// of price points per source doesn't warrant adding one just for this.

const SOURCE_CHART_COLOURS = {
  croma: "#e0631f",
  vijay_sales: "#2b3ecb",
  reliance_digital: "#067a46",
};
const FALLBACK_CHART_COLOURS = ["#8b5cf6", "#0891b2", "#be185d", "#65a30d"];

function colourForSource(source, fallbackIndex) {
  return SOURCE_CHART_COLOURS[source] || FALLBACK_CHART_COLOURS[fallbackIndex % FALLBACK_CHART_COLOURS.length];
}

function axisPriceLabel(price) {
  return Number(price).toLocaleString("en-IN", { maximumFractionDigits: 0 });
}

function formatHistoryDate(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return (
    d.toLocaleDateString("en-IN", { day: "numeric", month: "short" }) +
    " " +
    d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })
  );
}

function buildPriceHistoryChart(history) {
  const priced = history.filter((p) => p.selling_price !== null && p.scraped_at);
  if (!priced.length) return null;

  const width = 640;
  const height = 220;
  const marginLeft = 68;
  const marginRight = 16;
  const marginTop = 12;
  const marginBottom = 28;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;

  const times = priced.map((p) => new Date(p.scraped_at).getTime());
  const prices = priced.map((p) => p.selling_price);
  let minTime = Math.min(...times);
  let maxTime = Math.max(...times);
  if (minTime === maxTime) {
    minTime -= 1;
    maxTime += 1;
  }
  let minPrice = Math.min(...prices);
  let maxPrice = Math.max(...prices);
  if (minPrice === maxPrice) {
    const pad = Math.max(minPrice * 0.05, 100);
    minPrice -= pad;
    maxPrice += pad;
  } else {
    const pad = (maxPrice - minPrice) * 0.1;
    minPrice -= pad;
    maxPrice += pad;
  }

  const x = (t) => marginLeft + ((t - minTime) / (maxTime - minTime)) * plotWidth;
  const y = (p) => marginTop + plotHeight - ((p - minPrice) / (maxPrice - minPrice)) * plotHeight;

  const bySource = {};
  priced.forEach((point) => {
    (bySource[point.source] = bySource[point.source] || []).push(point);
  });
  const sourceNames = Object.keys(bySource);

  const gridLineCount = 4;
  let gridSvg = "";
  for (let i = 0; i <= gridLineCount; i++) {
    const price = minPrice + ((maxPrice - minPrice) * i) / gridLineCount;
    const gy = y(price);
    gridSvg += `<line x1="${marginLeft}" y1="${gy}" x2="${width - marginRight}" y2="${gy}" stroke="var(--border)" stroke-width="1"/>`;
    gridSvg += `<text x="${marginLeft - 8}" y="${gy + 3}" font-size="10" fill="var(--muted)" text-anchor="end">${axisPriceLabel(price)}</text>`;
  }

  const axisSvg = `
    <text x="${marginLeft}" y="${height - 8}" font-size="10" fill="var(--muted)" text-anchor="start">${formatHistoryDate(new Date(minTime).toISOString())}</text>
    <text x="${width - marginRight}" y="${height - 8}" font-size="10" fill="var(--muted)" text-anchor="end">${formatHistoryDate(new Date(maxTime).toISOString())}</text>
  `;

  let seriesSvg = "";
  const legendItems = [];
  sourceNames.forEach((source, idx) => {
    const points = bySource[source].sort((a, b) => new Date(a.scraped_at) - new Date(b.scraped_at));
    const colour = colourForSource(source, idx);
    legendItems.push({ source, colour });

    if (points.length > 1) {
      const linePoints = points.map((p) => `${x(new Date(p.scraped_at).getTime())},${y(p.selling_price)}`).join(" ");
      seriesSvg += `<polyline points="${linePoints}" fill="none" stroke="${colour}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    }
    points.forEach((p) => {
      const cx = x(new Date(p.scraped_at).getTime());
      const cy = y(p.selling_price);
      seriesSvg += `<circle cx="${cx}" cy="${cy}" r="3.5" fill="${colour}"><title>${formatSourceName(source)}: ${money(p.selling_price)} on ${formatHistoryDate(p.scraped_at)}</title></circle>`;
    });
  });

  const svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Price history chart">${gridSvg}${seriesSvg}${axisSvg}</svg>`;

  const legendHtml = legendItems
    .map(
      (item) =>
        `<span class="price-chart-legend-item"><span class="price-chart-legend-dot" style="background:${item.colour}"></span>${formatSourceName(item.source)}</span>`
    )
    .join("");

  return `<div class="price-chart-legend">${legendHtml}</div><div class="price-chart-wrap">${svg}</div>`;
}

function renderPriceDropBanner(drops) {
  if (!drops || !drops.length) return "";
  return drops
    .map(
      (d) => `
        <div class="price-drop-banner">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>
          <span>${formatSourceName(d.source)} price dropped ${money(d.drop_amount)} (${d.drop_percent}%)<span class="offer-text">${money(d.previous_price)} &rarr; ${money(d.current_price)}, since ${formatHistoryDate(d.previous_scraped_at)}</span></span>
        </div>`
    )
    .join("");
}

function renderHistoryTable(history) {
  if (!history.length) return "";
  const rows = history
    .slice()
    .reverse() // most recent first
    .map(
      (p) => `
        <tr>
          <td>${formatHistoryDate(p.scraped_at)}</td>
          <td>${formatSourceName(p.source)}</td>
          <td>${money(p.selling_price)}</td>
          <td><span class="pill ${p.availability || ""}">${p.availability || "unknown"}</span></td>
        </tr>`
    )
    .join("");
  return `<table class="history-table"><thead><tr><th>Scraped</th><th>Source</th><th>Price</th><th>Availability</th></tr></thead><tbody>${rows}</tbody></table>`;
}

async function openPriceHistory(variantId) {
  historyModalOverlay.hidden = false;
  historyModalSubtitle.textContent = "Loading...";
  historyModalBody.innerHTML = `<div class="history-empty"><span class="spinner"></span></div>`;

  try {
    const response = await fetch(`/api/price-history/${variantId}`);
    const data = await response.json();
    if (!response.ok) {
      historyModalSubtitle.textContent = "";
      historyModalBody.innerHTML = `<div class="history-empty">${data.error || "Could not load price history."}</div>`;
      return;
    }

    historyModalSubtitle.textContent = [
      `${data.product.brand} ${data.product.model}`,
      [data.variant.storage, data.variant.colour].filter(Boolean).join(" / "),
    ]
      .filter(Boolean)
      .join(" - ");

    if (!data.history.length) {
      historyModalBody.innerHTML = `<div class="history-empty">No price history recorded for this listing yet - run a few searches over time to build one up.</div>`;
      return;
    }

    const chartHtml =
      buildPriceHistoryChart(data.history) || `<div class="history-empty">Not enough priced data points to chart yet.</div>`;
    historyModalBody.innerHTML = renderPriceDropBanner(data.price_drops) + chartHtml + renderHistoryTable(data.history);
  } catch (err) {
    historyModalSubtitle.textContent = "";
    historyModalBody.innerHTML = `<div class="history-empty">Network error: ${err.message}</div>`;
  }
}

function closePriceHistory() {
  historyModalOverlay.hidden = true;
  historyModalBody.innerHTML = "";
}

tbody.addEventListener("click", (event) => {
  const button = event.target.closest(".history-btn");
  if (!button) return;
  openPriceHistory(button.dataset.variantId);
});

historyModalClose.addEventListener("click", closePriceHistory);
historyModalOverlay.addEventListener("click", (event) => {
  if (event.target === historyModalOverlay) closePriceHistory();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !historyModalOverlay.hidden) closePriceHistory();
});

// --- Model autocomplete -----------------------------------------------

const fetchModelSuggestions = debounce(async (query) => {
  if (!query || query.length < 2) {
    modelSuggestions.innerHTML = "";
    return;
  }
  try {
    const response = await fetch(`/api/models?q=${encodeURIComponent(query)}`);
    const data = await response.json();
    modelSuggestions.innerHTML = (data.models || [])
      .map((m) => `<option value="${m}"></option>`)
      .join("");
  } catch (err) {
    // Suggestions are a convenience, not required to search - fail quietly.
  }
}, 250);

modelInput.addEventListener("input", () => fetchModelSuggestions(modelInput.value));

// Fires when the field loses focus after a change, including a datalist
// pick - this loads the Storage/Colour dropdowns instantly, then kicks off
// a real search in the background so every source's full detail for this
// model is already on screen before the user touches Storage/Colour at all.
modelInput.addEventListener("change", () => {
  const model = modelInput.value.trim();
  if (!model) return;
  loadModelOptions(model);
  executeSearch({ model });
});

// --- Storage/Colour dropdowns: instant, from a static catalog ----------
//
// This is a local lookup (GET /api/model-options), not a live scrape - it
// exists purely so the dropdowns populate the moment a model is picked,
// instead of waiting on a multi-source crawl. It's typical/likely options,
// not confirmed stock - clicking Search still runs the real cross-source
// lookup that confirms actual availability and price.

function populateOptionSelect(selectEl, values) {
  const options = ['<option value="">Any</option>'];
  for (const value of values) {
    options.push(`<option value="${value}">${value}</option>`);
  }
  selectEl.innerHTML = options.join("");
  selectEl.disabled = false;
}

async function loadModelOptions(model) {
  lastModelSearch = null; // a new model invalidates any previous live search
  const myToken = ++requestToken;
  try {
    const response = await fetch(`/api/model-options?model=${encodeURIComponent(model)}`);
    const data = await response.json();
    populateOptionSelect(storageSelect, data.storage || []);
    populateOptionSelect(colourSelect, data.colour || []);
    if (myToken === requestToken) {
      setStatus(`Storage/colour options loaded for "${model}". Hit Search to see live prices across sources.`, false);
    }
  } catch (err) {
    // Even if this fails, the user can still search with "Any"/"Any".
    populateOptionSelect(storageSelect, []);
    populateOptionSelect(colourSelect, []);
  }
}

// --- Running an actual search (live, cross-source) ----------------------
//
// Shared by: picking a model (auto-runs with just {model}, so the table is
// already full of every source's listing before Storage/Colour are ever
// touched) and the Search button (runs with every filter currently set).

async function executeSearch(payload) {
  const myToken = ++requestToken;
  startLoadingStatus();
  table.hidden = true;
  emptyStateEl.hidden = true;
  recommendationEl.hidden = true;

  try {
    const response = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (myToken !== requestToken) return; // superseded by a newer search/lookup

    if (!response.ok) {
      setStatus(data.error || "Search failed", true);
      return;
    }

    lastModelSearch = data;

    if (!data.results.length) {
      setStatus("No matching listings found. Try a different model/storage/colour.", true);
      renderRows([]);
      renderRecommendation(null, data);
      return;
    }

    const filtered = getFilteredResults();
    const sourceStatus = `${data.sources_succeeded}/${data.sources_attempted} source(s) responded successfully.`;
    const filterNote = filtered.length !== data.results.length
      ? ` Showing ${filtered.length} of ${data.results.length} matching your current filters.`
      : "";
    setStatus(sourceStatus + filterNote, data.sources_failed > 0);
    renderRows(filtered);
    renderRecommendation(data.recommendation, data);
    statusEl.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    if (myToken === requestToken) setStatus("Network error: " + err.message, true);
  }
}

// Storage/Colour/Budget narrow the row set; EMI Tenure/Down Payment don't
// remove any rows but do change the EMI figure shown for each one - all of
// it applied instantly, client-side, against the last real search response
// (no new request - the underlying prices/offers haven't changed).
//
// Pulled apart from rendering/status so executeSearch() can reuse the same
// filtering logic: a live search takes a few seconds, and a user who picks
// Colour or sets Down Payment *while it's still in flight* had those choices
// silently dropped once the response landed (lastModelSearch was still null
// when they touched the control, so applyLiveFilters() no-op'd, and the
// response handler then rendered the full, unfiltered set). Re-applying
// whatever's currently selected - here, not just on the next manual change -
// is what makes that already-chosen colour/down payment actually take effect.
function getFilteredResults() {
  const storage = storageSelect.value;
  const colour = colourSelect.value;
  const { min: budgetMin, max: budgetMax } = getBudgetBounds();
  const tenureMonths = Number(emiTenureSelect.value) || 12;
  const downPayment = Number(downPaymentInput.value) || 0;
  const baseRate = lastModelSearch.emi_assumptions ? lastModelSearch.emi_assumptions.annual_rate_percent : 14.0;

  // Only treat the source toggles as an active filter once fewer than all of
  // them are selected - every button starts "active" (see index.html), and
  // that all-selected state means "no filter", same as storage/colour "Any".
  const allSources = Array.from(sourceTogglesEl.querySelectorAll(".source-toggle")).map((b) => b.dataset.source);
  const selectedSources = getSelectedSources();
  const sourceFilterActive = selectedSources.length > 0 && selectedSources.length < allSources.length;

  return lastModelSearch.results
    .filter((r) => {
      if (storage && r.variant.storage !== storage) return false;
      if (colour && r.variant.colour !== colour) return false;
      if (sourceFilterActive && !selectedSources.includes(r.source)) return false;
      if (budgetMin !== null && (r.selling_price === null || r.selling_price < budgetMin)) return false;
      if (budgetMax !== null && (r.selling_price === null || r.selling_price > budgetMax)) return false;
      return true;
    })
    .map((r) => {
      if (r.effective_price === null) return r;
      const noCostEmi = (r.offers || []).some((o) => o.offer_type === "no_cost_emi");
      const financed = Math.max(r.effective_price - downPayment, 0);
      return { ...r, emi: calculateEmiClientSide(financed, tenureMonths, baseRate, noCostEmi) };
    });
}

function applyLiveFilters() {
  if (!lastModelSearch) return;
  const filtered = getFilteredResults();
  renderRows(filtered);
  setStatus(`Showing ${filtered.length} of ${lastModelSearch.results.length} listing(s) matching your filters.`, false);
}

[storageSelect, colourSelect, emiTenureSelect].forEach((el) => el.addEventListener("change", applyLiveFilters));
[budgetMinInput, budgetMaxInput, downPaymentInput].forEach((el) => el.addEventListener("input", applyLiveFilters));

// --- Source filter, as toggle buttons -----------------------------------
//
// Every button starts active (all sources shown - see index.html), so a
// plain toggle() on click made clicking "Croma" turn Croma *off* the first
// time (it was already on) while Vijay Sales/Reliance Digital stayed on -
// the exact opposite of "show me only Croma". A plain click now isolates
// the clicked source instead (mirrors the common chart-legend pattern);
// clicking the sole remaining active source again resets to "all sources".
// Ctrl/Cmd/Shift-click still adds or removes one source from the current
// selection, for picking e.g. "Croma + Vijay Sales" without Reliance
// Digital, and a click is never allowed to leave zero sources selected.
sourceTogglesEl.addEventListener("click", (event) => {
  const button = event.target.closest(".source-toggle");
  if (!button) return;

  const buttons = Array.from(sourceTogglesEl.querySelectorAll(".source-toggle"));
  const activeButtons = buttons.filter((b) => b.classList.contains("active"));
  const isSoleActive = activeButtons.length === 1 && activeButtons[0] === button;

  if (event.shiftKey || event.metaKey || event.ctrlKey) {
    if (button.classList.contains("active")) {
      if (activeButtons.length > 1) button.classList.remove("active");
    } else {
      button.classList.add("active");
    }
  } else if (isSoleActive) {
    buttons.forEach((b) => b.classList.add("active"));
  } else {
    buttons.forEach((b) => b.classList.toggle("active", b === button));
  }

  applyLiveFilters();
});

function getSelectedSources() {
  return Array.from(sourceTogglesEl.querySelectorAll(".source-toggle.active")).map((b) => b.dataset.source);
}

// --- Search button (the authoritative call - includes budget/EMI/sources) -

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  const sources = getSelectedSources();
  const { min: budgetMin, max: budgetMax } = getBudgetBounds();

  executeSearch({
    model: formData.get("model"),
    storage: formData.get("storage") || null,
    colour: formData.get("colour") || null,
    budget_min: budgetMin,
    budget_max: budgetMax,
    emi_tenure_months: Number(formData.get("emi_tenure_months")) || 12,
    down_payment: Number(formData.get("down_payment")) || 0,
    sources: sources.length ? sources : null,
  });
});
