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
const emiTenureSelect = document.getElementById("emi_tenure_months");
const downPaymentInput = document.getElementById("down_payment");

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

function money(value) {
  if (value === null || value === undefined) return "-";
  return "Rs. " + Number(value).toLocaleString("en-IN", { maximumFractionDigits: 0 });
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
    `<li><strong>Best current price:</strong> ${rec.best_current_price.source} - ${money(rec.best_current_price.amount)}</li>`,
    `<li><strong>Best effective price after offers:</strong> ${rec.best_effective_price.source} - ${money(rec.best_effective_price.amount)}</li>`,
  ];
  if (rec.lowest_emi) {
    lines.push(
      `<li><strong>Lowest EMI (${rec.lowest_emi.tenure_months} mo):</strong> ${rec.lowest_emi.source} - ${money(rec.lowest_emi.monthly_emi)}/month</li>`
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
      <td>${row.source}${isBest ? '<span class="best-badge">Best</span>' : ""}</td>
      <td>
        ${row.product.brand} ${row.product.model}
        <span class="offer-text">${[row.variant.storage, row.variant.colour].filter(Boolean).join(" / ") || ""}</span>
        ${row.product_url ? `<br><a class="source-url" href="${row.product_url}" target="_blank" rel="noopener">source link</a>` : ""}
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

    setStatus(`${data.sources_succeeded}/${data.sources_attempted} source(s) responded successfully.`, data.sources_failed > 0);
    renderRows(data.results);
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
function applyLiveFilters() {
  if (!lastModelSearch) return;

  const storage = storageSelect.value;
  const colour = colourSelect.value;
  const budgetMin = budgetMinInput.value !== "" ? Number(budgetMinInput.value) : null;
  const budgetMax = budgetMaxInput.value !== "" ? Number(budgetMaxInput.value) : null;
  const tenureMonths = Number(emiTenureSelect.value) || 12;
  const downPayment = Number(downPaymentInput.value) || 0;
  const baseRate = lastModelSearch.emi_assumptions ? lastModelSearch.emi_assumptions.annual_rate_percent : 14.0;

  const filtered = lastModelSearch.results
    .filter((r) => {
      if (storage && r.variant.storage !== storage) return false;
      if (colour && r.variant.colour !== colour) return false;
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

  renderRows(filtered);
  setStatus(`Showing ${filtered.length} of ${lastModelSearch.results.length} listing(s) matching your filters.`, false);
}

[storageSelect, colourSelect, emiTenureSelect].forEach((el) => el.addEventListener("change", applyLiveFilters));
[budgetMinInput, budgetMaxInput, downPaymentInput].forEach((el) => el.addEventListener("input", applyLiveFilters));

// --- Source filter, as toggle buttons -----------------------------------

sourceTogglesEl.addEventListener("click", (event) => {
  const button = event.target.closest(".source-toggle");
  if (!button) return;
  button.classList.toggle("active");
});

function getSelectedSources() {
  return Array.from(sourceTogglesEl.querySelectorAll(".source-toggle.active")).map((b) => b.dataset.source);
}

// --- Search button (the authoritative call - includes budget/EMI/sources) -

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  const sources = getSelectedSources();

  executeSearch({
    model: formData.get("model"),
    storage: formData.get("storage") || null,
    colour: formData.get("colour") || null,
    budget_min: formData.get("budget_min") || null,
    budget_max: formData.get("budget_max") || null,
    emi_tenure_months: Number(formData.get("emi_tenure_months")) || 12,
    down_payment: Number(formData.get("down_payment")) || 0,
    sources: sources.length ? sources : null,
  });
});
