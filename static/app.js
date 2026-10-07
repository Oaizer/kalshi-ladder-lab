const $ = (id) => document.getElementById(id);
const form = $("scan-form");
const eventSelect = $("event");
const money = (value) => `$${Number(value).toFixed(2)}`;
const pct = (value) => `${Math.round(Number(value) * 100)}%`;

function setStatus(message, kind = "") {
  $("status").textContent = message;
  $("status").className = `status ${kind}`;
}

async function json(url) {
  const response = await fetch(url);
  const body = await response.json();
  if (!response.ok)
    throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

async function loadEvents() {
  const series = $("series").value.trim().toUpperCase();
  $("series").value = series;
  $("load-events").disabled = true;
  setStatus("Loading events…", "busy");
  try {
    const data = await json(`/api/events?series=${encodeURIComponent(series)}`);
    eventSelect.replaceChildren();
    for (const event of data.events) {
      const option = document.createElement("option");
      option.value = event.ticker;
      option.textContent = `${event.ticker} · ${event.count} markets`;
      eventSelect.append(option);
    }
    if (!data.events.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No open events in this series";
      eventSelect.append(option);
    }
    setStatus(`${data.events.length} events found`);
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    $("load-events").disabled = false;
  }
}

function renderChart(ladder) {
  const rows = ladder.filter(
    (m) => m.yes_bid !== null && m.yes_ask !== null && Number(m.yes_ask) > 0,
  );
  if (!rows.length) {
    $("chart").textContent =
      "No quoted YES prices are available for this event.";
    return;
  }
  const w = 670,
    h = 285,
    left = 50,
    right = 16,
    top = 16,
    bottom = 43;
  const strikes = rows.map((m) => Number(m.strike));
  const min = Math.min(...strikes),
    max = Math.max(...strikes);
  const x = (strike) =>
    left + ((strike - min) / (max - min || 1)) * (w - left - right);
  const y = (price) => h - bottom - Number(price) * (h - top - bottom);
  const line = (key) =>
    rows
      .map(
        (m, i) =>
          `${i ? "L" : "M"}${x(Number(m.strike)).toFixed(1)},${y(m[key]).toFixed(1)}`,
      )
      .join(" ");
  let svg = `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="YES bid and ask price by strike">`;
  for (const value of [0, 0.25, 0.5, 0.75, 1]) {
    svg += `<line class="grid-line" x1="${left}" x2="${w - right}" y1="${y(value)}" y2="${y(value)}"/><text class="axis" x="7" y="${y(value) + 4}">${Math.round(value * 100)}%</text>`;
  }
  svg += `<path class="bid-line" d="${line("yes_bid")}"/><path class="ask-line" d="${line("yes_ask")}"/>`;
  rows.forEach((m) => {
    const px = x(Number(m.strike));
    svg += `<circle class="bid-point" cx="${px}" cy="${y(m.yes_bid)}" r="4"><title>${m.strike}: bid ${pct(m.yes_bid)}</title></circle>`;
    svg += `<circle class="ask-point" cx="${px}" cy="${y(m.yes_ask)}" r="4"><title>${m.strike}: ask ${pct(m.yes_ask)}</title></circle>`;
    svg += `<text class="axis" x="${px}" y="${h - 12}" text-anchor="middle">${m.strike}</text>`;
  });
  $("chart").innerHTML = svg + "</svg>";
}

function renderConstraints(ladder) {
  const parent = $("constraints");
  parent.replaceChildren();
  const rows = ladder.filter(
    (m) => m.yes_bid !== null && m.yes_ask !== null && Number(m.yes_ask) > 0,
  );
  if (rows.length < 2) {
    parent.innerHTML =
      '<div class="empty">At least two quoted thresholds are needed for comparison.</div>';
    return;
  }
  for (let i = 0; i < rows.length - 1; i++) {
    const low = rows[i],
      high = rows[i + 1];
    const lowMid = (Number(low.yes_bid) + Number(low.yes_ask)) / 2;
    const highMid = (Number(high.yes_bid) + Number(high.yes_ask)) / 2;
    const bad = highMid > lowMid + 0.00001;
    const item = document.createElement("div");
    item.className = "constraint";
    const label = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent = `>${low.strike} → >${high.strike}`;
    const small = document.createElement("small");
    small.textContent = `Midpoints ${pct(lowMid)} → ${pct(highMid)} · diagnostic only`;
    label.append(strong, small);
    const state = document.createElement("span");
    state.className = bad ? "violation" : "ok";
    state.textContent = bad ? "INVERTED" : "ORDERED";
    item.append(label, state);
    parent.append(item);
  }
}

function renderOpportunities(rows) {
  const parent = $("opportunities");
  parent.replaceChildren();
  if (!rows.length) {
    parent.innerHTML =
      '<div class="empty">No positive worst-case payout certificates at the sampled prices, displayed depth, and selected fee coefficient. Try another event or scan again after the book changes.</div>';
    return;
  }
  for (const row of rows) {
    const item = document.createElement("div");
    item.className = "opportunity";
    const title = document.createElement("div");
    title.className = "opp-title";
    title.textContent = `YES >${row.low_strike} + NO >${row.high_strike}`;
    const sub = document.createElement("div");
    sub.className = "opp-sub";
    sub.textContent = `${row.low_ticker} · ${row.high_ticker}`;
    title.append(sub);
    item.append(title);
    for (const [label, value, cls] of [
      ["PAIRS", row.count, ""],
      ["COST + FEES", money(Number(row.cost) + Number(row.fees)), ""],
      ["WORST-CASE PROFIT", money(row.worst_profit), "profit"],
    ]) {
      const box = document.createElement("div");
      box.className = `opp-num ${cls}`;
      const caption = document.createElement("span");
      caption.textContent = label;
      const number = document.createElement("strong");
      number.textContent = value;
      box.append(caption, number);
      item.append(box);
    }
    const details = document.createElement("div");
    details.className = "details";
    const lots = (values) =>
      values.map((lot) => `${lot.count} @ ${money(lot.price)}`).join(", ");
    details.textContent = `Buy YES: ${lots(row.yes_lots)} · Buy NO: ${lots(row.no_lots)} · Modeled fees: ${money(row.fees)}. Settlement: X ≤ ${row.low_strike} pays ${money(row.worst_payout)}; ${row.low_strike} < X ≤ ${row.high_strike} pays ${money(row.count * 2)}; X > ${row.high_strike} pays ${money(row.worst_payout)}.`;
    item.append(details);
    parent.append(item);
  }
}

function renderResult(data) {
  $("results").hidden = false;
  $("event-title").textContent = data.event;
  $("timestamp").textContent = data.synthetic
    ? "Illustrative data · not a live market"
    : `Snapshot ${new Date(data.sampled_at).toLocaleString()}`;
  $("metric-markets").textContent = data.ladder.length;
  $("metric-pairs").textContent = data.pairs_checked;
  $("metric-books").textContent = `${data.books_loaded}/${data.ladder.length}`;
  $("metric-opportunities").textContent = data.opportunities.length;
  renderChart(data.ladder);
  renderConstraints(data.ladder);
  renderOpportunities(data.opportunities);
  $("warning").hidden = !data.book_errors.length && !data.synthetic;
  $("warning").textContent = data.synthetic
    ? "Worked example with invented prices. It demonstrates the payoff calculation and is not a current Kalshi opportunity."
    : data.book_errors.length
      ? `${data.book_errors.length} order books failed to load. Results may be incomplete; scan again.`
      : "";
  setStatus(data.synthetic ? "Worked example" : "Analysis complete");
  $("results").scrollIntoView({ behavior: "smooth", block: "start" });
}

async function analyze(event) {
  setStatus("Reading order books…", "busy");
  form.querySelector('button[type="submit"]').disabled = true;
  try {
    const params = new URLSearchParams({
      event,
      fee_rate: $("fee-rate").value,
      cap: $("cap").value,
    });
    renderResult(await json(`/api/analyze?${params}`));
  } catch (error) {
    setStatus(error.message, "error");
  } finally {
    form.querySelector('button[type="submit"]').disabled = false;
  }
}

$("load-events").addEventListener("click", loadEvents);
$("example").addEventListener("click", async () => {
  setStatus("Loading example…", "busy");
  try {
    renderResult(await json("/api/example"));
  } catch (error) {
    setStatus(error.message, "error");
  }
});
form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (eventSelect.value) analyze(eventSelect.value);
});
loadEvents();
