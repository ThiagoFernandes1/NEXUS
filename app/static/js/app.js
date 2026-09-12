/* =========================================================================
   NEXUS Dashboard — cliente
   Sem dependências externas: canvas puro, SSE e Fetch API.
   ========================================================================= */

const $ = (id) => document.getElementById(id);
const fmt = (n, d = 2) =>
  n == null ? "—" : Number(n).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });

const state = {
  prices: {},          // último preço por moeda, para detectar variação
  sparks: {},          // histórico curto para os mini-gráficos
  chart: [],           // série do gráfico principal
  chartSeries: "crypto.bitcoin",
  chartLabel: "Bitcoin (USD)",
  weather: { lat: null, lon: null, city: null },
};

/* --- Notificações --------------------------------------------------------- */

function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = msg;
  $("toasts").appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .35s, transform .35s";
    el.style.opacity = "0";
    el.style.transform = "translateX(60px)";
    setTimeout(() => el.remove(), 350);
  }, 3600);
}

/* --- Campo de estrelas ---------------------------------------------------- */

function initStars() {
  const cv = $("stars");
  const ctx = cv.getContext("2d");
  let stars = [];

  function resize() {
    cv.width = innerWidth;
    cv.height = innerHeight;
    const count = Math.min(200, Math.floor((innerWidth * innerHeight) / 9000));
    stars = Array.from({ length: count }, () => ({
      x: Math.random() * cv.width,
      y: Math.random() * cv.height,
      r: Math.random() * 1.5 + 0.35,
      a: Math.random(),
      sp: Math.random() * 0.014 + 0.003,
      vy: Math.random() * 0.12 + 0.02,
    }));
  }

  function frame() {
    ctx.clearRect(0, 0, cv.width, cv.height);
    const light = document.documentElement.dataset.theme === "light";
    for (const s of stars) {
      s.a += s.sp;
      s.y += s.vy;
      if (s.y > cv.height) s.y = -2;
      const alpha = (Math.sin(s.a) * 0.5 + 0.5) * (light ? 0.28 : 0.85);
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = light ? `rgba(60,90,180,${alpha})` : `rgba(190,215,255,${alpha})`;
      ctx.fill();
    }
    requestAnimationFrame(frame);
  }

  addEventListener("resize", resize);
  resize();
  frame();
}

/* --- Relógio -------------------------------------------------------------- */

function initClock() {
  const tick = () => {
    const d = new Date();
    $("clock").innerHTML =
      d.toLocaleTimeString("pt-BR") +
      `<br><span>${d.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "short" })}</span>`;
  };
  tick();
  setInterval(tick, 1000);
}

/* --- Mini-gráficos (sparklines) ------------------------------------------- */

function sparkline(values, trend) {
  if (!values || values.length < 2) return "";
  const w = 62, h = 26, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const color = trend === "up" ? "#23d18b" : "#ff5c7a";
  return `<svg class="spark" viewBox="0 0 ${w} ${h}">
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.7"
      stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

/* --- Renderização: criptomoedas ------------------------------------------- */

function renderCrypto(payload) {
  if (!payload?.ok || !payload.data) return;
  const rows = $("crypto-rows");
  const badge = $("crypto-badge");
  badge.textContent = payload.stale ? "obsoleto" : payload.cached ? `cache ${payload.age}s` : "ao vivo";
  badge.className = "badge " + (payload.stale ? "stale" : payload.cached ? "" : "live");

  rows.innerHTML = payload.data.coins
    .map((c) => {
      const hist = (state.sparks[c.id] ||= []);
      if (hist[hist.length - 1] !== c.usd) hist.push(c.usd);
      if (hist.length > 20) hist.shift();

      const prev = state.prices[c.id];
      const flash = prev == null || prev === c.usd ? "" : c.usd > prev ? "flash-up" : "flash-down";
      state.prices[c.id] = c.usd;

      const dec = c.usd < 1 ? 5 : 2;
      return `<div class="row ${flash}" data-series="crypto.${c.id}" data-label="${c.name} (USD)" style="cursor:pointer">
        <div class="sym">${c.symbol}</div>
        <div>
          <div class="row-name">${c.name}</div>
          <div class="row-sub">R$ ${fmt(c.brl, c.brl < 1 ? 4 : 2)}</div>
        </div>
        ${sparkline(hist, c.trend)}
        <div style="text-align:right">
          <div class="row-val">$${fmt(c.usd, dec)}</div>
          <div class="change ${c.trend}">${c.change_24h >= 0 ? "▲" : "▼"} ${Math.abs(c.change_24h)}%</div>
        </div>
      </div>`;
    })
    .join("");

  rows.querySelectorAll(".row").forEach((el) =>
    el.addEventListener("click", () => {
      state.chartSeries = el.dataset.series;
      state.chartLabel = el.dataset.label;
      $("chart-label").textContent = state.chartLabel;
      loadChart();
    })
  );
}

/* --- Renderização: câmbio ------------------------------------------------- */

function renderForex(payload) {
  if (!payload?.ok || !payload.data) return;
  $("fx-badge").textContent = payload.cached ? `cache ${payload.age}s` : "ao vivo";
  $("fx-rows").innerHTML = payload.data.rates
    .map(
      (r) => `<div class="row" style="grid-template-columns:1fr auto">
        <div>
          <div class="row-name">${r.pair}</div>
          <div class="row-sub">${r.low.toFixed(r.bid > 1000 ? 0 : 3)} – ${r.high.toFixed(r.bid > 1000 ? 0 : 3)}</div>
        </div>
        <div style="text-align:right">
          <div class="row-val">${fmt(r.bid, r.bid > 1000 ? 0 : 4)}</div>
          <div class="change ${r.trend}">${r.pct_change >= 0 ? "▲" : "▼"} ${Math.abs(r.pct_change)}%</div>
        </div>
      </div>`
    )
    .join("");
}

/* --- Renderização: clima -------------------------------------------------- */

function renderWeather(payload) {
  if (!payload?.ok || !payload.data) return;
  const w = payload.data;
  state.weather = { lat: w.lat, lon: w.lon, city: w.city };

  $("wx-badge").textContent = payload.cached ? `cache ${payload.age}s` : "atualizado";
  $("wx-temp").classList.remove("skeleton");
  $("wx-temp").textContent = fmt(w.temperature, 1);
  $("wx-icon").textContent = w.icon;
  $("wx-label").textContent = w.label;
  $("wx-city").textContent = w.city;
  $("wx-feels").textContent = fmt(w.feels_like, 0) + "°";
  $("wx-hum").textContent = w.humidity + "%";
  $("wx-wind").textContent = fmt(w.wind, 0) + " km/h";
  $("wx-press").textContent = fmt(w.pressure, 0);

  $("forecast").innerHTML = w.forecast
    .map((f) => {
      const d = new Date(f.date + "T12:00:00");
      return `<div class="fc-day">
        <div class="d">${d.toLocaleDateString("pt-BR", { weekday: "short" })}</div>
        <div class="i">${f.icon}</div>
        <div class="t">${Math.round(f.max)}° <small>${Math.round(f.min)}°</small></div>
      </div>`;
    })
    .join("");
}

/* --- Renderização: notícias ----------------------------------------------- */

function renderNews(payload) {
  if (!payload?.ok || !payload.data) return;
  $("news-badge").textContent = `${payload.data.total.toLocaleString("pt-BR")} artigos`;
  $("news").innerHTML = payload.data.articles
    .map((a) => {
      const when = a.published ? new Date(a.published).toLocaleDateString("pt-BR") : "";
      const img = a.image
        ? `<img src="${a.image}" alt="" loading="lazy" onerror="this.style.display='none'">`
        : "";
      return `<a class="news-item" href="${a.url}" target="_blank" rel="noopener">
        ${img}
        <div>
          <h4>${a.title}</h4>
          <p>${a.site} · ${when}</p>
        </div>
      </a>`;
    })
    .join("");
}

/* --- Mapa da ISS ---------------------------------------------------------- */

const issTrail = [];

function renderISS(payload) {
  if (!payload?.ok || !payload.data) return;
  const { lat, lon } = payload.data;
  $("iss-lat").textContent = lat.toFixed(4) + "°";
  $("iss-lon").textContent = lon.toFixed(4) + "°";

  issTrail.push({ lat, lon });
  if (issTrail.length > 90) issTrail.shift();

  const cv = $("iss-canvas");
  const ctx = cv.getContext("2d");
  const w = (cv.width = cv.clientWidth * devicePixelRatio);
  const h = (cv.height = 210 * devicePixelRatio);
  ctx.scale(1, 1);

  const px = (lo) => ((lo + 180) / 360) * w;
  const py = (la) => ((90 - la) / 180) * h;

  // fundo
  const g = ctx.createLinearGradient(0, 0, 0, h);
  g.addColorStop(0, "#0a1430");
  g.addColorStop(1, "#060a1a");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);

  // grade de meridianos/paralelos
  ctx.strokeStyle = "rgba(90,140,230,.16)";
  ctx.lineWidth = 1;
  for (let lo = -180; lo <= 180; lo += 30) {
    ctx.beginPath(); ctx.moveTo(px(lo), 0); ctx.lineTo(px(lo), h); ctx.stroke();
  }
  for (let la = -60; la <= 60; la += 30) {
    ctx.beginPath(); ctx.moveTo(0, py(la)); ctx.lineTo(w, py(la)); ctx.stroke();
  }
  // equador
  ctx.strokeStyle = "rgba(120,170,255,.34)";
  ctx.beginPath(); ctx.moveTo(0, py(0)); ctx.lineTo(w, py(0)); ctx.stroke();

  // rastro
  if (issTrail.length > 1) {
    ctx.strokeStyle = "rgba(77,141,255,.75)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    issTrail.forEach((p, i) => {
      const x = px(p.lon), y = py(p.lat);
      // evita a linha atravessar a tela na virada de longitude
      if (i === 0 || Math.abs(px(issTrail[i - 1].lon) - x) > w / 2) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  // marcador com halo
  const x = px(lon), y = py(lat);
  const halo = ctx.createRadialGradient(x, y, 0, x, y, 22);
  halo.addColorStop(0, "rgba(77,141,255,.7)");
  halo.addColorStop(1, "rgba(77,141,255,0)");
  ctx.fillStyle = halo;
  ctx.beginPath(); ctx.arc(x, y, 22, 0, Math.PI * 2); ctx.fill();

  ctx.fillStyle = "#fff";
  ctx.beginPath(); ctx.arc(x, y, 4.5, 0, Math.PI * 2); ctx.fill();

  ctx.font = "600 12px system-ui";
  ctx.fillStyle = "rgba(230,240,255,.9)";
  ctx.fillText("🛰 ISS", x + 10, y - 8);
}

/* --- Gráfico principal ---------------------------------------------------- */

function drawChart(points) {
  const cv = $("chart");
  const ctx = cv.getContext("2d");
  // clientWidth pode ser 0 antes do layout assentar; nesse caso medimos o card.
  const avail = cv.clientWidth || (cv.parentElement.clientWidth - 40);
  const w = (cv.width = Math.max(avail, 280));
  const h = (cv.height = 230);
  cv.style.width = "100%";
  ctx.clearRect(0, 0, w, h);

  if (!points.length) {
    ctx.fillStyle = "rgba(140,160,200,.6)";
    ctx.font = "13px system-ui";
    ctx.fillText("Coletando dados… o gráfico aparece após alguns ciclos.", 16, h / 2);
    return;
  }

  const pad = { l: 58, r: 14, t: 14, b: 26 };
  const vals = points.map((p) => p.value);
  let min = Math.min(...vals), max = Math.max(...vals);
  if (min === max) { min -= 1; max += 1; }
  const range = max - min;
  min -= range * 0.1; max += range * 0.1;

  const X = (i) => pad.l + (i / Math.max(points.length - 1, 1)) * (w - pad.l - pad.r);
  const Y = (v) => pad.t + (1 - (v - min) / (max - min)) * (h - pad.t - pad.b);

  // grade + eixo Y
  ctx.strokeStyle = "rgba(120,160,255,.12)";
  ctx.fillStyle = "rgba(140,160,200,.7)";
  ctx.font = "10px ui-monospace, monospace";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const v = min + ((max - min) * i) / 4;
    const y = Y(v);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillText(v.toLocaleString("pt-BR", { maximumFractionDigits: v < 10 ? 4 : 0 }), 6, y + 3);
  }

  // área preenchida
  const grad = ctx.createLinearGradient(0, pad.t, 0, h - pad.b);
  grad.addColorStop(0, "rgba(77,141,255,.42)");
  grad.addColorStop(1, "rgba(77,141,255,0)");
  ctx.beginPath();
  ctx.moveTo(X(0), h - pad.b);
  points.forEach((p, i) => ctx.lineTo(X(i), Y(p.value)));
  ctx.lineTo(X(points.length - 1), h - pad.b);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // linha
  ctx.beginPath();
  points.forEach((p, i) => (i ? ctx.lineTo(X(i), Y(p.value)) : ctx.moveTo(X(i), Y(p.value))));
  ctx.strokeStyle = "#4d8dff";
  ctx.lineWidth = 2.2;
  ctx.lineJoin = "round";
  ctx.stroke();

  // ponto final destacado
  const last = points[points.length - 1];
  const lx = X(points.length - 1), ly = Y(last.value);
  ctx.fillStyle = "#4d8dff";
  ctx.beginPath(); ctx.arc(lx, ly, 4, 0, Math.PI * 2); ctx.fill();
  const light = document.documentElement.dataset.theme === "light";
  ctx.fillStyle = light ? "rgba(16,24,46,.95)" : "rgba(255,255,255,.92)";
  ctx.font = "600 11px ui-monospace, monospace";
  ctx.fillText(last.value.toLocaleString("pt-BR", { maximumFractionDigits: 2 }), lx - 46, ly - 10);
}

async function loadChart() {
  try {
    const r = await fetch(`/api/history/${state.chartSeries}?limit=120`);
    const j = await r.json();
    state.chart = j.points || [];
    $("chart-badge").textContent = `${state.chart.length} pontos`;
    drawChart(state.chart);
  } catch (e) {
    console.error(e);
  }
}

/* --- Log de eventos ------------------------------------------------------- */

async function loadEvents() {
  try {
    const j = await (await fetch("/api/events")).json();
    $("log").innerHTML = (j.events || [])
      .map((e) => {
        const t = new Date(e.t * 1000).toLocaleTimeString("pt-BR");
        return `<div><span class="ts">${t}</span><span class="lv ${e.level}">${e.level}</span><span>${e.message}</span></div>`;
      })
      .join("");
  } catch (e) {
    console.error(e);
  }
}

/* --- Despacho do snapshot ------------------------------------------------- */

function applySnapshot(snap) {
  const s = snap.services || {};
  if (s.crypto) renderCrypto(s.crypto);
  if (s.forex) renderForex(s.forex);
  if (s.weather && !state.weather.city) renderWeather(s.weather);
  if (s.space) renderNews(s.space);
  if (s.iss) renderISS(s.iss);

  if (snap.meta) {
    $("lat-badge").textContent = `${snap.meta.elapsed_ms} ms`;
    const ok = snap.meta.healthy === snap.meta.total;
    $("status").className = "status-pill" + (ok ? "" : " bad");
    $("status-txt").textContent = ok
      ? `${snap.meta.healthy}/${snap.meta.total} serviços`
      : `${snap.meta.healthy}/${snap.meta.total} · degradado`;
  }
}

/* --- Busca de cidade ------------------------------------------------------ */

function initCitySearch() {
  const input = $("city-input");
  const box = $("city-suggest");
  let timer;

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { box.classList.remove("open"); return; }
    timer = setTimeout(async () => {
      try {
        const j = await (await fetch(`/api/geocode?q=${encodeURIComponent(q)}`)).json();
        const list = j.data || [];
        if (!list.length) { box.classList.remove("open"); return; }
        box.innerHTML = list
          .map((c, i) => `<div data-i="${i}">${c.name} <small>${c.admin ? c.admin + ", " : ""}${c.country}</small></div>`)
          .join("");
        box.classList.add("open");
        box.querySelectorAll("div[data-i]").forEach((el) =>
          el.addEventListener("click", async () => {
            const c = list[+el.dataset.i];
            box.classList.remove("open");
            input.value = "";
            try {
              const res = await (
                await fetch(`/api/weather?lat=${c.lat}&lon=${c.lon}&city=${encodeURIComponent(c.name)}`)
              ).json();
              if (res.ok) {
                renderWeather({ ok: true, cached: false, age: 0, data: res.data });
                toast(`Clima de ${c.name} carregado`, "ok");
              } else toast("Falha ao buscar clima", "err");
            } catch { toast("Erro de rede", "err"); }
          })
        );
      } catch (e) { console.error(e); }
    }, 300);
  });

  document.addEventListener("click", (e) => {
    if (!box.contains(e.target) && e.target !== input) box.classList.remove("open");
  });
}

/* --- Tema ----------------------------------------------------------------- */

function initTheme() {
  const btn = $("theme-btn");
  const saved = localStorage.getItem("nexus-theme");
  if (saved) document.documentElement.dataset.theme = saved;
  btn.textContent = document.documentElement.dataset.theme === "light" ? "☀️" : "🌙";

  btn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    btn.textContent = next === "light" ? "☀️" : "🌙";
    try { localStorage.setItem("nexus-theme", next); } catch {}
    drawChart(state.chart);
  });
}

/* --- Streaming em tempo real ---------------------------------------------- */

function initStream() {
  const es = new EventSource("/api/stream");

  es.addEventListener("update", (ev) => {
    try {
      const snap = JSON.parse(ev.data);
      applySnapshot(snap);
      if (snap.tick % 6 === 0) { loadChart(); loadEvents(); }
    } catch (e) { console.error(e); }
  });

  es.onerror = () => {
    $("status").className = "status-pill bad";
    $("status-txt").textContent = "reconectando…";
  };

  es.onopen = () => toast("Fluxo em tempo real conectado", "ok");
}

/* --- Semeia os mini-gráficos com o histórico já gravado -------------------- */

async function primeSparklines() {
  const ids = Object.keys(state.prices);
  if (!ids.length) return;
  await Promise.all(
    ids.map(async (id) => {
      try {
        const j = await (await fetch(`/api/history/crypto.${id}?limit=20`)).json();
        const vals = (j.points || []).map((p) => p.value);
        if (vals.length > 1) state.sparks[id] = vals;
      } catch {}
    })
  );
  // redesenha as linhas com o histórico carregado
  const snap = await (await fetch("/api/snapshot?only=crypto")).json();
  if (snap.services?.crypto) renderCrypto(snap.services.crypto);
}

/* --- Inicialização -------------------------------------------------------- */

async function boot() {
  initStars();
  initClock();
  initTheme();
  initCitySearch();

  $("refresh-btn").addEventListener("click", async () => {
    $("refresh-btn").style.transform = "rotate(360deg)";
    setTimeout(() => ($("refresh-btn").style.transform = ""), 400);
    const snap = await (await fetch("/api/snapshot")).json();
    applySnapshot(snap);
    loadChart();
    toast("Painel atualizado", "ok");
  });

  addEventListener("resize", () => drawChart(state.chart));

  try {
    const snap = await (await fetch("/api/snapshot")).json();
    applySnapshot(snap);
  } catch {
    toast("Falha ao carregar dados iniciais", "err");
  }

  await primeSparklines();
  await loadChart();
  await loadEvents();
  initStream();
}

boot();
