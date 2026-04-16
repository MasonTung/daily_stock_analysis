// ====================================================================
// Commodity Trading Assistant - Dashboard Frontend
// ====================================================================

const state = {
  currentCommodity: "gold",
  detailCommodity: "gold",
  detailStrategy: null,
  klineChart: null,
  wfChart: null,
  geoGauge: null,
  backtestData: null,
  pollingInterval: null,
};

// ====================================================================
// 初始化
// ====================================================================
window.addEventListener("DOMContentLoaded", () => {
  document.getElementById("analyze-btn").addEventListener("click", startAnalysis);

  // K线图 Tab 切换
  document.querySelectorAll("#commodity-tabs .tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#commodity-tabs .tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.currentCommodity = btn.dataset.commodity;
      loadKline(state.currentCommodity);
    });
  });

  // 策略详情选择器
  document.getElementById("detail-commodity-select").addEventListener("change", (e) => {
    state.detailCommodity = e.target.value;
    populateStrategySelector();
    loadDetail();
  });
  document.getElementById("detail-strategy-select").addEventListener("change", (e) => {
    state.detailStrategy = e.target.value;
    loadDetail();
  });

  // 检查是否已有数据
  checkExistingData();
});

async function checkExistingData() {
  const s = await fetch("/api/status").then(r => r.json()).catch(() => null);
  if (s && s.has_data) {
    document.getElementById("welcome-banner").classList.add("hidden");
    document.getElementById("dashboard").classList.remove("hidden");
    await loadAll();
  }
}

// ====================================================================
// 启动分析
// ====================================================================
async function startAnalysis() {
  const interval = document.getElementById("interval-select").value;
  const lookback = document.getElementById("lookback-select").value;

  setStatus("running", "分析中...");
  document.getElementById("analyze-btn").disabled = true;

  try {
    const resp = await fetch(`/api/analyze?interval=${interval}&lookback_days=${lookback}`, {
      method: "POST",
    });
    if (!resp.ok) throw new Error(await resp.text());

    // 轮询状态
    state.pollingInterval = setInterval(async () => {
      const s = await fetch("/api/status").then(r => r.json());
      if (!s.is_running) {
        clearInterval(state.pollingInterval);
        state.pollingInterval = null;
        if (s.error) {
          setStatus("error", "失败: " + s.error);
          document.getElementById("analyze-btn").disabled = false;
        } else {
          setStatus("ok", `完成 @ ${new Date(s.last_run_time).toLocaleTimeString()}`);
          document.getElementById("welcome-banner").classList.add("hidden");
          document.getElementById("dashboard").classList.remove("hidden");
          document.getElementById("analyze-btn").disabled = false;
          await loadAll();
        }
      }
    }, 1000);
  } catch (e) {
    setStatus("error", "错误: " + e.message);
    document.getElementById("analyze-btn").disabled = false;
  }
}

function setStatus(level, text) {
  const el = document.getElementById("status-indicator");
  el.className = "status " + level;
  document.getElementById("status-text").textContent = text;
}

// ====================================================================
// 加载所有数据
// ====================================================================
async function loadAll() {
  await Promise.all([
    loadGeopolitical(),
    loadSnapshot(),
    loadKline(state.currentCommodity),
    loadBacktest(),
    loadRecommendations(),
  ]);
}

// ====================================================================
// 地缘政治面板
// ====================================================================
async function loadGeopolitical() {
  try {
    const data = await fetch("/api/geopolitical").then(r => r.json());

    document.getElementById("geo-score-number").textContent = data.overall_score.toFixed(1);
    const levelEl = document.getElementById("geo-score-level");
    levelEl.textContent = data.overall_level.toUpperCase();
    levelEl.className = "score-level level-" + data.overall_level;

    renderGeoGauge(data.overall_score, data.overall_level);

    // 品种偏好
    const biasHtml = Object.entries(data.commodity_bias).map(([k, v]) => {
      const dir = v > 0.1 ? "偏多 ↑" : v < -0.1 ? "偏空 ↓" : "中性 →";
      const cls = v > 0.1 ? "bullish" : v < -0.1 ? "bearish" : "neutral";
      return `<div class="bias-row ${cls}">
        <span class="bias-name">${commodityName(k)}</span>
        <span class="bias-value">${dir} (${v >= 0 ? "+" : ""}${v.toFixed(2)})</span>
      </div>`;
    }).join("");
    document.getElementById("geo-bias").innerHTML = biasHtml;

    // 仓位缩放
    const posHtml = Object.entries(data.position_scale).map(([k, v]) => {
      const pct = Math.round(v * 100);
      return `<div class="position-row">
        <span class="bias-name">${commodityName(k)}</span>
        <div class="bar-outer"><div class="bar-inner" style="width:${pct}%"></div></div>
        <span class="bias-value">${pct}%</span>
      </div>`;
    }).join("");
    document.getElementById("geo-position").innerHTML = posHtml;

    // 活跃因子
    const factorsHtml = data.active_factors.map(f => `<li>⚠ ${f}</li>`).join("");
    document.getElementById("geo-factors").innerHTML = factorsHtml || "<li>暂无活跃风险因子</li>";
  } catch (e) {
    console.error("Load geopolitical failed:", e);
  }
}

function renderGeoGauge(score, level) {
  if (!state.geoGauge) {
    state.geoGauge = echarts.init(document.getElementById("geo-gauge"));
  }
  const color = level === "extreme" ? "#e74c3c"
              : level === "high" ? "#e67e22"
              : level === "medium" ? "#f1c40f"
              : "#27ae60";

  state.geoGauge.setOption({
    series: [{
      type: "gauge",
      min: 0, max: 100,
      progress: { show: true, width: 15, itemStyle: { color } },
      axisLine: { lineStyle: { width: 15, color: [[1, "#2c3e50"]] } },
      axisTick: { distance: -25, length: 6, lineStyle: { color: "#888" } },
      splitLine: { distance: -30, length: 10, lineStyle: { color: "#ddd" } },
      axisLabel: { distance: -45, color: "#bbb", fontSize: 10 },
      anchor: { show: false },
      pointer: { itemStyle: { color } },
      detail: { show: false },
      data: [{ value: score }],
    }],
  });
}

// ====================================================================
// 市场快照
// ====================================================================
async function loadSnapshot() {
  try {
    const data = await fetch("/api/snapshot").then(r => r.json());
    const html = Object.entries(data).map(([k, v]) => {
      const changeClass = v.change_pct > 0 ? "up" : v.change_pct < 0 ? "down" : "";
      const rsiStatus = v.rsi === null ? "-"
                      : v.rsi > 70 ? "超买" : v.rsi < 30 ? "超卖" : "中性";
      const macdStatus = v.macd_hist === null ? "-"
                       : v.macd_hist > 0 ? "看多" : "看空";
      return `
        <div class="snapshot-card ${changeClass}">
          <div class="snapshot-header">
            <span class="snapshot-name">${v.name}</span>
            <span class="snapshot-change">${v.change_pct >= 0 ? "+" : ""}${v.change_pct}%</span>
          </div>
          <div class="snapshot-price">${v.latest_price.toLocaleString()}</div>
          <div class="snapshot-indicators">
            <div><span>RSI</span><b>${v.rsi === null ? "-" : v.rsi} <small>${rsiStatus}</small></b></div>
            <div><span>MACD</span><b>${v.macd_hist === null ? "-" : v.macd_hist} <small>${macdStatus}</small></b></div>
            <div><span>BB %B</span><b>${v.bb_pct_b === null ? "-" : v.bb_pct_b}</b></div>
            <div><span>ATR%</span><b>${v.atr_pct === null ? "-" : v.atr_pct}%</b></div>
          </div>
        </div>
      `;
    }).join("");
    document.getElementById("snapshot-grid").innerHTML = html;
  } catch (e) {
    console.error("Load snapshot failed:", e);
  }
}

// ====================================================================
// K线图
// ====================================================================
async function loadKline(commodity) {
  try {
    const data = await fetch(`/api/kline/${commodity}?limit=500`).then(r => r.json());
    if (!state.klineChart) {
      state.klineChart = echarts.init(document.getElementById("kline-chart"));
    }

    const times = data.candles.map(c => c.time.substring(0, 16).replace("T", " "));
    const klineData = data.candles.map(c => [c.open, c.close, c.low, c.high]);
    const volumes = data.candles.map((c, i) => [i, c.volume, c.open > c.close ? -1 : 1]);

    const series = [
      {
        name: "K线",
        type: "candlestick",
        data: klineData,
        itemStyle: {
          color: "#26a69a",
          color0: "#ef5350",
          borderColor: "#26a69a",
          borderColor0: "#ef5350",
        },
      },
      {
        name: "成交量",
        type: "bar",
        xAxisIndex: 1, yAxisIndex: 1,
        data: volumes,
        itemStyle: {
          color: (p) => p.data[2] > 0 ? "#26a69a" : "#ef5350",
        },
      },
    ];

    // 叠加均线
    const overlays = [
      ["sma_5", "SMA5", "#f39c12"],
      ["sma_20", "SMA20", "#3498db"],
      ["sma_50", "SMA50", "#9b59b6"],
      ["bb_upper", "布林上", "#95a5a6"],
      ["bb_lower", "布林下", "#95a5a6"],
      ["vwap", "VWAP", "#e74c3c"],
    ];
    for (const [key, name, color] of overlays) {
      if (data.indicators[key]) {
        series.push({
          name, type: "line",
          data: data.indicators[key],
          smooth: true,
          lineStyle: { width: 1, color },
          showSymbol: false,
        });
      }
    }

    state.klineChart.setOption({
      backgroundColor: "transparent",
      animation: false,
      title: {
        text: `${data.name}  最新: ${data.latest_price}  (${data.change_pct >= 0 ? "+" : ""}${data.change_pct}%)`,
        textStyle: { color: "#ecf0f1", fontSize: 14 },
      },
      legend: {
        data: ["K线", "SMA5", "SMA20", "SMA50", "布林上", "布林下", "VWAP"],
        textStyle: { color: "#bdc3c7" },
      },
      tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
      axisPointer: { link: [{ xAxisIndex: "all" }] },
      grid: [
        { left: "6%", right: "3%", top: "12%", height: "58%" },
        { left: "6%", right: "3%", top: "75%", height: "18%" },
      ],
      xAxis: [
        { type: "category", data: times, scale: true, boundaryGap: false,
          axisLine: { onZero: false }, axisLabel: { color: "#bdc3c7" } },
        { type: "category", gridIndex: 1, data: times, scale: true,
          axisLabel: { show: false }, axisLine: { lineStyle: { color: "#444" } } },
      ],
      yAxis: [
        { scale: true, splitArea: { show: false },
          axisLabel: { color: "#bdc3c7" },
          splitLine: { lineStyle: { color: "#2c3e50" } } },
        { gridIndex: 1, splitNumber: 2, axisLabel: { show: false },
          axisLine: { show: false }, axisTick: { show: false },
          splitLine: { show: false } },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1], start: 70, end: 100 },
        { type: "slider", xAxisIndex: [0, 1], top: "95%", height: 15,
          start: 70, end: 100, textStyle: { color: "#bdc3c7" } },
      ],
      series,
    }, true);
  } catch (e) {
    console.error("Load kline failed:", e);
  }
}

// ====================================================================
// 策略绩效矩阵
// ====================================================================
async function loadBacktest() {
  try {
    const data = await fetch("/api/backtest").then(r => r.json());
    state.backtestData = data;

    const commodities = Object.keys(data);
    const strategies = new Set();
    Object.values(data).forEach(s => Object.keys(s).forEach(k => strategies.add(k)));
    const strategyList = Array.from(strategies).sort();

    let html = `
      <div class="matrix-container">
        <h3>总收益率 (%)</h3>
        <table class="matrix-table">
          <thead>
            <tr>
              <th>策略</th>
              ${commodities.map(c => `<th>${commodityName(c)}</th>`).join("")}
            </tr>
          </thead>
          <tbody>
            ${strategyList.map(s => `
              <tr>
                <td class="strat-name">${s}</td>
                ${commodities.map(c => {
                  const r = data[c][s];
                  if (!r) return `<td>-</td>`;
                  const val = r.total_return_pct;
                  const cls = val > 0 ? "positive" : val < 0 ? "negative" : "";
                  return `<td class="${cls}">${val >= 0 ? "+" : ""}${val.toFixed(2)}%</td>`;
                }).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>

        <h3>Sharpe Ratio</h3>
        <table class="matrix-table">
          <thead>
            <tr>
              <th>策略</th>
              ${commodities.map(c => `<th>${commodityName(c)}</th>`).join("")}
            </tr>
          </thead>
          <tbody>
            ${strategyList.map(s => `
              <tr>
                <td class="strat-name">${s}</td>
                ${commodities.map(c => {
                  const r = data[c][s];
                  if (!r) return `<td>-</td>`;
                  const val = r.sharpe_ratio;
                  const cls = val > 0.5 ? "positive" : val < -0.5 ? "negative" : "";
                  return `<td class="${cls}">${val.toFixed(2)}</td>`;
                }).join("")}
              </tr>
            `).join("")}
          </tbody>
        </table>

        <h3>综合面板 (胜率 / 回撤 / 交易数 / OOS一致性)</h3>
        <table class="matrix-table small">
          <thead>
            <tr>
              <th>品种 / 策略</th><th>胜率</th><th>回撤</th><th>交易</th><th>OOS</th><th>过拟合检测</th>
            </tr>
          </thead>
          <tbody>
            ${commodities.flatMap(c => strategyList.map(s => {
              const r = data[c][s];
              if (!r) return "";
              const pass = r.total_trades >= 10 && r.oos_consistency >= 0.5 && r.sharpe_ratio > -1 && r.sharpe_ratio < 5;
              return `
                <tr>
                  <td class="strat-name">${commodityName(c)} / ${s}</td>
                  <td>${(r.win_rate * 100).toFixed(1)}%</td>
                  <td class="negative">${r.max_drawdown_pct.toFixed(2)}%</td>
                  <td>${r.total_trades}</td>
                  <td>${(r.oos_consistency * 100).toFixed(0)}%</td>
                  <td>${pass ? '<span class="badge ok">通过</span>' : '<span class="badge warn">未通过</span>'}</td>
                </tr>`;
            })).join("")}
          </tbody>
        </table>
      </div>
    `;
    document.getElementById("backtest-matrix").innerHTML = html;

    // 填充策略详情选择器
    populateStrategySelector();
    loadDetail();
  } catch (e) {
    console.error("Load backtest failed:", e);
  }
}

function populateStrategySelector() {
  const sel = document.getElementById("detail-strategy-select");
  sel.innerHTML = "";
  if (!state.backtestData) return;
  const strats = Object.keys(state.backtestData[state.detailCommodity] || {});
  strats.forEach(s => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    sel.appendChild(opt);
  });
  state.detailStrategy = sel.value || strats[0];
}

// ====================================================================
// 策略详情 (Walk-Forward + 交易流水)
// ====================================================================
function loadDetail() {
  if (!state.backtestData) return;
  const r = state.backtestData[state.detailCommodity]?.[state.detailStrategy];
  if (!r) return;

  // Walk-Forward 分窗口柱状图
  if (!state.wfChart) {
    state.wfChart = echarts.init(document.getElementById("wf-chart"));
  }
  state.wfChart.setOption({
    backgroundColor: "transparent",
    animation: false,
    tooltip: { trigger: "axis" },
    legend: { data: ["胜率", "平均收益(%)"], textStyle: { color: "#bdc3c7" } },
    xAxis: {
      type: "category",
      data: r.wf_splits.map(s => `Split ${s.split_id + 1}\n${s.test_period}`),
      axisLabel: { color: "#bdc3c7", fontSize: 10 },
    },
    yAxis: [
      { type: "value", name: "胜率", axisLabel: { color: "#bdc3c7", formatter: "{value}%" },
        splitLine: { lineStyle: { color: "#2c3e50" } } },
      { type: "value", name: "平均收益 (%)", axisLabel: { color: "#bdc3c7" } },
    ],
    series: [
      {
        name: "胜率",
        type: "bar",
        data: r.wf_splits.map(s => (s.win_rate * 100).toFixed(1)),
        itemStyle: { color: "#3498db" },
      },
      {
        name: "平均收益(%)",
        type: "line",
        yAxisIndex: 1,
        data: r.wf_splits.map(s => s.avg_pnl_pct),
        itemStyle: { color: "#e67e22" },
        lineStyle: { width: 2 },
      },
    ],
  }, true);

  // 交易流水
  const trades = r.recent_trades || [];
  const html = `
    <div class="summary-box">
      <div><b>策略:</b> ${r.strategy_name}</div>
      <div><b>总收益:</b> <span class="${r.total_return_pct >= 0 ? "positive" : "negative"}">${r.total_return_pct >= 0 ? "+" : ""}${r.total_return_pct}%</span></div>
      <div><b>Sharpe:</b> ${r.sharpe_ratio}</div>
      <div><b>盈亏比:</b> ${r.profit_factor}</div>
      <div><b>平均持仓:</b> ${r.avg_bars_held} 根K线</div>
    </div>
    <table class="trade-table">
      <thead>
        <tr><th>时间</th><th>方向</th><th>入场</th><th>出场</th><th>盈亏</th><th>原因</th></tr>
      </thead>
      <tbody>
        ${trades.map(t => `
          <tr>
            <td>${t.entry_time.substring(5, 16)}</td>
            <td class="${t.direction === "LONG" ? "bullish" : "bearish"}">${t.direction}</td>
            <td>${t.entry_price}</td>
            <td>${t.exit_price}</td>
            <td class="${t.pnl_pct >= 0 ? "positive" : "negative"}">${t.pnl_pct >= 0 ? "+" : ""}${t.pnl_pct}%</td>
            <td><small>${t.exit_reason}</small></td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
  document.getElementById("trade-list").innerHTML = html;
}

// ====================================================================
// 最优策略推荐
// ====================================================================
async function loadRecommendations() {
  try {
    const data = await fetch("/api/recommendations").then(r => r.json());
    const html = Object.entries(data).map(([c, rec]) => {
      if (!rec) {
        return `<div class="reco-card empty">
          <h3>${commodityName(c)}</h3>
          <p>所有策略均未通过最低交易次数要求</p>
        </div>`;
      }
      const passCls = rec.passes_overfit_check ? "pass" : "warn";
      const passBadge = rec.passes_overfit_check
        ? '<span class="badge ok">✓ 通过过拟合检测</span>'
        : '<span class="badge warn">⚠ 未通过过拟合检测</span>';
      return `
        <div class="reco-card ${passCls}">
          <h3>${commodityName(c)}</h3>
          <div class="reco-strategy">${rec.strategy}</div>
          <div class="reco-score">综合得分: <b>${rec.score}</b></div>
          <div class="reco-metrics">
            <div><span>收益</span><b class="${rec.return_pct >= 0 ? "positive" : "negative"}">${rec.return_pct >= 0 ? "+" : ""}${rec.return_pct}%</b></div>
            <div><span>Sharpe</span><b>${rec.sharpe}</b></div>
            <div><span>回撤</span><b class="negative">${rec.max_dd}%</b></div>
            <div><span>OOS</span><b>${(rec.oos_consistency * 100).toFixed(0)}%</b></div>
          </div>
          ${passBadge}
        </div>
      `;
    }).join("");
    document.getElementById("recommendations").innerHTML = html;
  } catch (e) {
    console.error("Load recommendations failed:", e);
  }
}

// ====================================================================
// 工具函数
// ====================================================================
function commodityName(key) {
  return { gold: "黄金", silver: "白银", oil: "原油" }[key] || key;
}

window.addEventListener("resize", () => {
  if (state.klineChart) state.klineChart.resize();
  if (state.wfChart) state.wfChart.resize();
  if (state.geoGauge) state.geoGauge.resize();
});
