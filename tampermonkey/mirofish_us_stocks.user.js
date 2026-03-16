// ==UserScript==
// @name         薯条交易 - US Stocks Scraper (Fries Trading)
// @namespace    https://fries-trading.daily-stock-analysis
// @version      1.0.0
// @description  薯条交易 - 从主流美股网站抓取股票数据，发送至薯条交易后端进行 Graph RAG 图谱分析
// @author       Fries Trading
// @match        https://finance.yahoo.com/*
// @match        https://www.google.com/finance/*
// @match        https://finviz.com/*
// @match        https://www.nasdaq.com/*
// @match        https://www.marketwatch.com/*
// @match        https://stockanalysis.com/*
// @match        https://www.tradingview.com/*
// @match        https://www.investing.com/*
// @match        https://www.wsj.com/market-data/*
// @match        https://seekingalpha.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_notification
// @grant        GM_addStyle
// @grant        GM_registerMenuCommand
// @connect      localhost
// @connect      *
// ==/UserScript==

(function () {
  "use strict";

  // ========================================
  // 配置
  // ========================================
  const DEFAULT_API_BASE = "http://127.0.0.1:8000";

  function getApiBase() {
    return GM_getValue("fries_api_base", DEFAULT_API_BASE);
  }

  function setApiBase(url) {
    GM_setValue("fries_api_base", url);
  }

  // ========================================
  // UI 样式注入
  // ========================================
  GM_addStyle(`
    #fries-panel {
      position: fixed;
      top: 60px;
      right: 20px;
      width: 380px;
      max-height: 80vh;
      background: #1a1a2e;
      color: #e0e0e0;
      border-radius: 12px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.4);
      z-index: 99999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 13px;
      overflow: hidden;
      display: none;
      transition: all 0.3s ease;
    }
    #fries-panel.mf-visible {
      display: flex;
      flex-direction: column;
    }
    #fries-panel .mf-header {
      background: linear-gradient(135deg, #16213e 0%, #0f3460 100%);
      padding: 12px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      cursor: move;
      border-bottom: 1px solid #333;
    }
    #fries-panel .mf-header h3 {
      margin: 0;
      font-size: 15px;
      color: #53c1de;
    }
    #fries-panel .mf-close {
      background: none;
      border: none;
      color: #888;
      font-size: 18px;
      cursor: pointer;
    }
    #fries-panel .mf-body {
      padding: 12px 16px;
      overflow-y: auto;
      flex: 1;
    }
    #fries-panel .mf-section {
      margin-bottom: 12px;
    }
    #fries-panel .mf-section label {
      display: block;
      font-size: 11px;
      color: #888;
      margin-bottom: 4px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    #fries-panel .mf-stock-list {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    #fries-panel .mf-stock-tag {
      background: #16213e;
      border: 1px solid #0f3460;
      border-radius: 6px;
      padding: 4px 10px;
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 4px;
    }
    #fries-panel .mf-stock-tag .mf-remove {
      cursor: pointer;
      color: #e94560;
      font-weight: bold;
    }
    #fries-panel .mf-input-row {
      display: flex;
      gap: 6px;
      margin-top: 8px;
    }
    #fries-panel .mf-input {
      flex: 1;
      background: #16213e;
      border: 1px solid #333;
      border-radius: 6px;
      padding: 6px 10px;
      color: #e0e0e0;
      font-size: 13px;
      outline: none;
    }
    #fries-panel .mf-input:focus {
      border-color: #53c1de;
    }
    #fries-panel .mf-btn {
      background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
      color: white;
      border: none;
      border-radius: 6px;
      padding: 6px 14px;
      cursor: pointer;
      font-size: 12px;
      transition: opacity 0.2s;
    }
    #fries-panel .mf-btn:hover {
      opacity: 0.85;
    }
    #fries-panel .mf-btn.mf-danger {
      background: linear-gradient(135deg, #e94560, #c23055);
    }
    #fries-panel .mf-btn.mf-success {
      background: linear-gradient(135deg, #2ecc71, #27ae60);
    }
    #fries-panel .mf-persona-card {
      background: #16213e;
      border: 1px solid #333;
      border-radius: 8px;
      padding: 10px;
      margin-bottom: 8px;
    }
    #fries-panel .mf-persona-name {
      font-weight: bold;
      color: #53c1de;
      margin-bottom: 4px;
    }
    #fries-panel .mf-persona-desc {
      font-size: 11px;
      color: #999;
    }
    #fries-panel .mf-status {
      padding: 8px;
      border-radius: 6px;
      margin-top: 8px;
      font-size: 12px;
      text-align: center;
    }
    #fries-panel .mf-status.success {
      background: rgba(46, 204, 113, 0.15);
      color: #2ecc71;
    }
    #fries-panel .mf-status.error {
      background: rgba(233, 69, 96, 0.15);
      color: #e94560;
    }
    #fries-panel .mf-status.loading {
      background: rgba(83, 193, 222, 0.15);
      color: #53c1de;
    }
    #fries-panel .mf-tabs {
      display: flex;
      border-bottom: 1px solid #333;
    }
    #fries-panel .mf-tab {
      flex: 1;
      text-align: center;
      padding: 8px;
      cursor: pointer;
      color: #888;
      border-bottom: 2px solid transparent;
      transition: all 0.2s;
    }
    #fries-panel .mf-tab.active {
      color: #53c1de;
      border-bottom-color: #53c1de;
    }
    #fries-panel .mf-screenshot-area {
      border: 2px dashed #333;
      border-radius: 8px;
      padding: 20px;
      text-align: center;
      cursor: pointer;
      transition: border-color 0.2s;
      margin-top: 8px;
    }
    #fries-panel .mf-screenshot-area:hover,
    #fries-panel .mf-screenshot-area.dragover {
      border-color: #53c1de;
    }
    #fries-panel .mf-screenshot-area img {
      max-width: 100%;
      max-height: 200px;
      border-radius: 6px;
      margin-top: 8px;
    }
    #fries-fab {
      position: fixed;
      bottom: 30px;
      right: 30px;
      width: 56px;
      height: 56px;
      border-radius: 50%;
      background: linear-gradient(135deg, #0f3460 0%, #533483 100%);
      color: white;
      border: none;
      cursor: pointer;
      font-size: 24px;
      z-index: 99998;
      box-shadow: 0 4px 16px rgba(0,0,0,0.3);
      display: flex;
      align-items: center;
      justify-content: center;
      transition: transform 0.2s;
    }
    #fries-fab:hover {
      transform: scale(1.1);
    }
    .mf-select {
      background: #16213e;
      border: 1px solid #333;
      border-radius: 6px;
      padding: 6px 10px;
      color: #e0e0e0;
      font-size: 13px;
      width: 100%;
      outline: none;
      margin-top: 4px;
    }
    .mf-checkbox-group {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-top: 6px;
    }
    .mf-checkbox-group label {
      display: flex !important;
      align-items: center;
      gap: 6px;
      color: #ccc !important;
      font-size: 12px !important;
      text-transform: none !important;
      letter-spacing: 0 !important;
    }
  `);

  // ========================================
  // 网站适配器 - 从各网站抓取股票数据
  // ========================================
  const SiteScrapers = {
    // Yahoo Finance
    "finance.yahoo.com": {
      name: "Yahoo Finance",
      extractStocks() {
        const stocks = [];
        // 详情页
        const tickerEl = document.querySelector(
          '[data-testid="qsp-header"] fin-streamer[data-symbol]'
        );
        if (tickerEl) {
          const symbol = tickerEl.getAttribute("data-symbol");
          const nameEl = document.querySelector(
            '[data-testid="qsp-header"] h1'
          );
          const priceEl = document.querySelector(
            'fin-streamer[data-field="regularMarketPrice"]'
          );
          const changeEl = document.querySelector(
            'fin-streamer[data-field="regularMarketChangePercent"]'
          );
          stocks.push({
            symbol: symbol,
            name: nameEl ? nameEl.textContent.trim() : symbol,
            price: priceEl ? parseFloat(priceEl.textContent.replace(",", "")) : null,
            change_percent: changeEl ? parseFloat(changeEl.textContent.replace(/[()%]/g, "")) : null,
          });
        }
        // 列表页 / watchlist
        document.querySelectorAll("table tbody tr").forEach((row) => {
          const symbolEl = row.querySelector('td:first-child a[data-testid="table-col-symbol"]');
          if (!symbolEl) return;
          const sym = symbolEl.textContent.trim();
          if (sym && /^[A-Z]{1,5}(\.[A-Z])?$/.test(sym)) {
            const nameCol = row.querySelector("td:nth-child(2)");
            const priceCol = row.querySelector('fin-streamer[data-field="regularMarketPrice"]');
            const chgCol = row.querySelector('fin-streamer[data-field="regularMarketChangePercent"]');
            stocks.push({
              symbol: sym,
              name: nameCol ? nameCol.textContent.trim() : sym,
              price: priceCol ? parseFloat(priceCol.textContent.replace(",", "")) : null,
              change_percent: chgCol ? parseFloat(chgCol.textContent.replace(/[()%]/g, "")) : null,
            });
          }
        });
        return stocks;
      },
    },

    // Google Finance
    "www.google.com": {
      name: "Google Finance",
      extractStocks() {
        const stocks = [];
        // 详情页
        const headerEl = document.querySelector("[data-symbol]");
        if (headerEl) {
          stocks.push({
            symbol: headerEl.getAttribute("data-symbol"),
            name: headerEl.textContent.trim(),
            price: null,
            change_percent: null,
          });
        }
        // Watchlist items
        document.querySelectorAll("li[data-symbol]").forEach((li) => {
          const sym = li.getAttribute("data-symbol");
          if (sym && /^[A-Z]{1,5}$/.test(sym)) {
            stocks.push({
              symbol: sym,
              name: li.textContent.split("\n")[0]?.trim() || sym,
              price: null,
              change_percent: null,
            });
          }
        });
        return stocks;
      },
    },

    // Finviz
    "finviz.com": {
      name: "Finviz",
      extractStocks() {
        const stocks = [];
        // Screener table
        document.querySelectorAll("table.screener-body-table-nw td a.screener-link-primary").forEach((a) => {
          const sym = a.textContent.trim();
          if (/^[A-Z]{1,5}(\.[A-Z])?$/.test(sym)) {
            stocks.push({
              symbol: sym,
              name: sym,
              price: null,
              change_percent: null,
            });
          }
        });
        // Detail page
        const titleEl = document.querySelector("table.fullview-title td.fullview-title a");
        if (titleEl) {
          stocks.push({
            symbol: titleEl.textContent.trim(),
            name: document.querySelector("table.fullview-title td.fullview-title b")?.textContent.trim() || "",
            price: null,
            change_percent: null,
          });
        }
        return stocks;
      },
    },

    // TradingView
    "www.tradingview.com": {
      name: "TradingView",
      extractStocks() {
        const stocks = [];
        // Chart header
        const symbolEl = document.querySelector("[data-symbol-short]");
        if (symbolEl) {
          const sym = symbolEl.getAttribute("data-symbol-short");
          if (/^[A-Z]{1,5}$/.test(sym)) {
            stocks.push({
              symbol: sym,
              name: symbolEl.textContent.trim(),
              price: null,
              change_percent: null,
            });
          }
        }
        // Watchlist
        document.querySelectorAll('.widgetbar-widget-watchlist .listRow [class*="symbolNameText"]').forEach((el) => {
          const sym = el.textContent.trim();
          if (/^[A-Z]{1,5}$/.test(sym)) {
            stocks.push({ symbol: sym, name: sym, price: null, change_percent: null });
          }
        });
        return stocks;
      },
    },

    // Stock Analysis
    "stockanalysis.com": {
      name: "Stock Analysis",
      extractStocks() {
        const stocks = [];
        // Detail page
        const match = window.location.pathname.match(/\/stocks\/([A-Za-z]{1,5})\//);
        if (match) {
          const sym = match[1].toUpperCase();
          const nameEl = document.querySelector("h1");
          stocks.push({
            symbol: sym,
            name: nameEl ? nameEl.textContent.replace(/\(.*\)/, "").trim() : sym,
            price: null,
            change_percent: null,
          });
        }
        // Tables
        document.querySelectorAll("table tbody tr td:first-child a").forEach((a) => {
          const sym = a.textContent.trim().toUpperCase();
          if (/^[A-Z]{1,5}$/.test(sym)) {
            stocks.push({ symbol: sym, name: sym, price: null, change_percent: null });
          }
        });
        return stocks;
      },
    },

    // MarketWatch
    "www.marketwatch.com": {
      name: "MarketWatch",
      extractStocks() {
        const stocks = [];
        const tickerEl = document.querySelector(".company__ticker");
        if (tickerEl) {
          const nameEl = document.querySelector(".company__name");
          stocks.push({
            symbol: tickerEl.textContent.trim(),
            name: nameEl ? nameEl.textContent.trim() : "",
            price: null,
            change_percent: null,
          });
        }
        return stocks;
      },
    },

    // Seeking Alpha
    "seekingalpha.com": {
      name: "Seeking Alpha",
      extractStocks() {
        const stocks = [];
        const match = window.location.pathname.match(/\/symbol\/([A-Za-z]{1,5})/);
        if (match) {
          const sym = match[1].toUpperCase();
          stocks.push({ symbol: sym, name: sym, price: null, change_percent: null });
        }
        return stocks;
      },
    },

    // Nasdaq
    "www.nasdaq.com": {
      name: "Nasdaq",
      extractStocks() {
        const stocks = [];
        const match = window.location.pathname.match(/\/market-activity\/stocks\/([a-z]{1,5})/i);
        if (match) {
          const sym = match[1].toUpperCase();
          const nameEl = document.querySelector(".symbol-page-header__name");
          stocks.push({
            symbol: sym,
            name: nameEl ? nameEl.textContent.trim() : sym,
            price: null,
            change_percent: null,
          });
        }
        return stocks;
      },
    },
  };

  // ========================================
  // 全局状态
  // ========================================
  let scrapedStocks = [];
  let selectedPersonas = [];
  let currentTab = "scrape"; // scrape | image | persona | settings

  // ========================================
  // API 通信
  // ========================================
  function apiRequest(method, path, data) {
    return new Promise((resolve, reject) => {
      const url = getApiBase() + path;
      GM_xmlhttpRequest({
        method: method,
        url: url,
        headers: { "Content-Type": "application/json" },
        data: data ? JSON.stringify(data) : undefined,
        timeout: 30000,
        onload(resp) {
          try {
            resolve({ status: resp.status, data: JSON.parse(resp.responseText) });
          } catch {
            resolve({ status: resp.status, data: resp.responseText });
          }
        },
        onerror(err) {
          reject(new Error("Network error: " + (err.error || "unknown")));
        },
        ontimeout() {
          reject(new Error("Request timeout"));
        },
      });
    });
  }

  function apiUpload(path, file) {
    return new Promise((resolve, reject) => {
      const url = getApiBase() + path;
      const formData = new FormData();
      formData.append("file", file);
      // GM_xmlhttpRequest with FormData
      GM_xmlhttpRequest({
        method: "POST",
        url: url,
        data: formData,
        timeout: 60000,
        onload(resp) {
          try {
            resolve({ status: resp.status, data: JSON.parse(resp.responseText) });
          } catch {
            resolve({ status: resp.status, data: resp.responseText });
          }
        },
        onerror(err) {
          reject(new Error("Upload error: " + (err.error || "unknown")));
        },
        ontimeout() {
          reject(new Error("Upload timeout"));
        },
      });
    });
  }

  // ========================================
  // 获取当前网站适配器
  // ========================================
  function getCurrentScraper() {
    const hostname = window.location.hostname;
    for (const [domain, scraper] of Object.entries(SiteScrapers)) {
      if (hostname === domain || hostname.endsWith("." + domain)) {
        return scraper;
      }
    }
    return null;
  }

  // ========================================
  // 渲染函数
  // ========================================
  function renderStockTags() {
    const container = document.getElementById("mf-stock-tags");
    if (!container) return;
    container.innerHTML = scrapedStocks
      .map(
        (s, i) => `
      <span class="mf-stock-tag">
        <span>${s.symbol}</span>
        ${s.price ? `<span style="color:#53c1de">$${s.price}</span>` : ""}
        ${s.change_percent != null ? `<span style="color:${s.change_percent >= 0 ? "#2ecc71" : "#e94560"}">${s.change_percent >= 0 ? "+" : ""}${s.change_percent}%</span>` : ""}
        <span class="mf-remove" data-idx="${i}">×</span>
      </span>
    `
      )
      .join("");
    // Bind remove handlers
    container.querySelectorAll(".mf-remove").forEach((el) => {
      el.addEventListener("click", () => {
        scrapedStocks.splice(parseInt(el.dataset.idx), 1);
        renderStockTags();
      });
    });
  }

  function showStatus(msg, type = "loading") {
    const el = document.getElementById("mf-status");
    if (el) {
      el.className = "mf-status " + type;
      el.textContent = msg;
      el.style.display = "block";
    }
  }

  function hideStatus() {
    const el = document.getElementById("mf-status");
    if (el) el.style.display = "none";
  }

  function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll("#fries-panel .mf-tab").forEach((t) => {
      t.classList.toggle("active", t.dataset.tab === tab);
    });
    document.querySelectorAll("#fries-panel .mf-tab-content").forEach((c) => {
      c.style.display = c.dataset.tab === tab ? "block" : "none";
    });
  }

  // ========================================
  // 创建面板
  // ========================================
  function createPanel() {
    const scraper = getCurrentScraper();
    const siteName = scraper ? scraper.name : "Unknown Site";

    const panel = document.createElement("div");
    panel.id = "fries-panel";
    panel.innerHTML = `
      <div class="mf-header">
        <h3>薯条交易</h3>
        <button class="mf-close" id="mf-close-btn">×</button>
      </div>
      <div class="mf-tabs">
        <div class="mf-tab active" data-tab="scrape">Scrape</div>
        <div class="mf-tab" data-tab="image">Image</div>
        <div class="mf-tab" data-tab="persona">Persona</div>
        <div class="mf-tab" data-tab="settings">Settings</div>
      </div>
      <div class="mf-body">
        <!-- Scrape Tab -->
        <div class="mf-tab-content" data-tab="scrape" style="display:block">
          <div class="mf-section">
            <label>Data Source: ${siteName}</label>
            <button class="mf-btn" id="mf-scrape-btn" style="width:100%;margin-top:6px">
              Scrape Current Page
            </button>
          </div>
          <div class="mf-section">
            <label>Scraped Stocks (${scrapedStocks.length})</label>
            <div class="mf-stock-list" id="mf-stock-tags"></div>
            <div class="mf-input-row">
              <input class="mf-input" id="mf-add-input" placeholder="Add ticker (e.g. AAPL)">
              <button class="mf-btn" id="mf-add-btn">Add</button>
            </div>
          </div>
          <div class="mf-section">
            <button class="mf-btn mf-success" id="mf-analyze-btn" style="width:100%">
              Send to Analysis
            </button>
            <button class="mf-btn mf-danger" id="mf-clear-btn" style="width:100%;margin-top:6px">
              Clear All
            </button>
          </div>
        </div>

        <!-- Image Tab -->
        <div class="mf-tab-content" data-tab="image" style="display:none">
          <div class="mf-section">
            <label>Screenshot / Image Recognition</label>
            <div class="mf-screenshot-area" id="mf-drop-area">
              <p>Click or drag & drop screenshot here</p>
              <p style="font-size:11px;color:#666">Supports JPG, PNG, WebP (max 5MB)</p>
              <input type="file" id="mf-file-input" accept="image/*" style="display:none">
              <img id="mf-preview-img" style="display:none">
            </div>
            <button class="mf-btn" id="mf-extract-btn" style="width:100%;margin-top:8px">
              Extract Stocks from Image
            </button>
          </div>
          <div class="mf-section">
            <label>Clipboard Paste</label>
            <textarea class="mf-input" id="mf-paste-area" rows="3"
              placeholder="Paste stock list text (e.g. AAPL, TSLA, MSFT)"></textarea>
            <button class="mf-btn" id="mf-parse-paste-btn" style="width:100%;margin-top:6px">
              Parse Text
            </button>
          </div>
        </div>

        <!-- Persona Tab -->
        <div class="mf-tab-content" data-tab="persona" style="display:none">
          <div class="mf-section">
            <label>Analysis Personas / Strategies</label>
            <div id="mf-persona-list"></div>
            <button class="mf-btn" id="mf-load-personas-btn" style="width:100%;margin-top:8px">
              Load Personas
            </button>
          </div>
          <div class="mf-section">
            <label>Per-Stock Persona Override</label>
            <select class="mf-select" id="mf-override-stock">
              <option value="">-- Select Stock --</option>
            </select>
            <select class="mf-select" id="mf-override-persona" style="margin-top:4px">
              <option value="">-- Select Persona --</option>
            </select>
            <button class="mf-btn" id="mf-apply-override-btn" style="width:100%;margin-top:6px">
              Apply Override
            </button>
          </div>
          <div class="mf-section" id="mf-overrides-display"></div>
        </div>

        <!-- Settings Tab -->
        <div class="mf-tab-content" data-tab="settings" style="display:none">
          <div class="mf-section">
            <label>API Base URL</label>
            <input class="mf-input" id="mf-api-base-input" value="${getApiBase()}">
            <button class="mf-btn" id="mf-save-settings-btn" style="width:100%;margin-top:6px">
              Save Settings
            </button>
          </div>
          <div class="mf-section">
            <label>Connection Test</label>
            <button class="mf-btn" id="mf-test-conn-btn" style="width:100%;margin-top:4px">
              Test Connection
            </button>
          </div>
        </div>

        <div id="mf-status" class="mf-status" style="display:none"></div>
      </div>
    `;

    document.body.appendChild(panel);

    // FAB button
    const fab = document.createElement("button");
    fab.id = "fries-fab";
    fab.innerHTML = "🐟";
    fab.title = "薯条交易";
    document.body.appendChild(fab);

    // ========================================
    // 事件绑定
    // ========================================

    // Toggle panel
    fab.addEventListener("click", () => {
      panel.classList.toggle("mf-visible");
    });
    document.getElementById("mf-close-btn").addEventListener("click", () => {
      panel.classList.remove("mf-visible");
    });

    // Tab switching
    panel.querySelectorAll(".mf-tab").forEach((tab) => {
      tab.addEventListener("click", () => switchTab(tab.dataset.tab));
    });

    // Scrape button
    document.getElementById("mf-scrape-btn").addEventListener("click", () => {
      const scraper = getCurrentScraper();
      if (!scraper) {
        showStatus("Unsupported site", "error");
        return;
      }
      try {
        const newStocks = scraper.extractStocks();
        if (!newStocks.length) {
          showStatus("No stocks found on this page", "error");
          return;
        }
        // Deduplicate
        const existing = new Set(scrapedStocks.map((s) => s.symbol));
        let added = 0;
        for (const s of newStocks) {
          if (!existing.has(s.symbol)) {
            scrapedStocks.push(s);
            existing.add(s.symbol);
            added++;
          }
        }
        renderStockTags();
        showStatus(`Scraped ${added} new stocks (total: ${scrapedStocks.length})`, "success");
      } catch (e) {
        showStatus("Scrape failed: " + e.message, "error");
      }
    });

    // Add single stock
    document.getElementById("mf-add-btn").addEventListener("click", () => {
      const input = document.getElementById("mf-add-input");
      const val = input.value.trim().toUpperCase();
      if (!val || !/^[A-Z]{1,5}(\.[A-Z])?$/.test(val)) {
        showStatus("Invalid ticker format", "error");
        return;
      }
      if (scrapedStocks.some((s) => s.symbol === val)) {
        showStatus("Already added", "error");
        return;
      }
      scrapedStocks.push({ symbol: val, name: val, price: null, change_percent: null });
      input.value = "";
      renderStockTags();
      hideStatus();
    });

    // Clear all
    document.getElementById("mf-clear-btn").addEventListener("click", () => {
      scrapedStocks = [];
      renderStockTags();
      hideStatus();
    });

    // Send to analysis
    document.getElementById("mf-analyze-btn").addEventListener("click", async () => {
      if (!scrapedStocks.length) {
        showStatus("No stocks to analyze", "error");
        return;
      }
      showStatus("Sending to analysis...", "loading");
      try {
        const codes = scrapedStocks.map((s) => s.symbol);
        const resp = await apiRequest("POST", "/api/v1/fries/analyze", {
          stock_codes: codes,
          personas: selectedPersonas.length ? selectedPersonas : undefined,
          persona_overrides: getPersonaOverrides(),
        });
        if (resp.status === 200 || resp.status === 202) {
          showStatus("Analysis submitted! Task: " + (resp.data.task_id || "queued"), "success");
          GM_notification({
            title: "薯条交易",
            text: `Analysis started for ${codes.length} stocks`,
            timeout: 3000,
          });
        } else {
          showStatus("API error: " + JSON.stringify(resp.data), "error");
        }
      } catch (e) {
        showStatus("Failed: " + e.message, "error");
      }
    });

    // ========================================
    // Image tab handlers
    // ========================================
    const dropArea = document.getElementById("mf-drop-area");
    const fileInput = document.getElementById("mf-file-input");
    const previewImg = document.getElementById("mf-preview-img");
    let selectedFile = null;

    dropArea.addEventListener("click", () => fileInput.click());
    dropArea.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropArea.classList.add("dragover");
    });
    dropArea.addEventListener("dragleave", () => dropArea.classList.remove("dragover"));
    dropArea.addEventListener("drop", (e) => {
      e.preventDefault();
      dropArea.classList.remove("dragover");
      if (e.dataTransfer.files.length) {
        handleFileSelect(e.dataTransfer.files[0]);
      }
    });
    fileInput.addEventListener("change", () => {
      if (fileInput.files.length) {
        handleFileSelect(fileInput.files[0]);
      }
    });

    function handleFileSelect(file) {
      if (file.size > 5 * 1024 * 1024) {
        showStatus("File too large (max 5MB)", "error");
        return;
      }
      selectedFile = file;
      const reader = new FileReader();
      reader.onload = () => {
        previewImg.src = reader.result;
        previewImg.style.display = "block";
      };
      reader.readAsDataURL(file);
      hideStatus();
    }

    // Paste handler for clipboard images
    document.addEventListener("paste", (e) => {
      if (!panel.classList.contains("mf-visible") || currentTab !== "image") return;
      const items = e.clipboardData?.items;
      if (!items) return;
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) handleFileSelect(file);
          break;
        }
      }
    });

    document.getElementById("mf-extract-btn").addEventListener("click", async () => {
      if (!selectedFile) {
        showStatus("No image selected", "error");
        return;
      }
      showStatus("Extracting stocks from image...", "loading");
      try {
        const resp = await apiUpload("/api/v1/stocks/extract-from-image?include_raw=false", selectedFile);
        if (resp.status === 200 && resp.data.codes) {
          const existing = new Set(scrapedStocks.map((s) => s.symbol));
          let added = 0;
          for (const item of resp.data.items || []) {
            const sym = item.code;
            if (sym && !existing.has(sym)) {
              scrapedStocks.push({
                symbol: sym,
                name: item.name || sym,
                price: null,
                change_percent: null,
              });
              existing.add(sym);
              added++;
            }
          }
          renderStockTags();
          showStatus(`Extracted ${added} stocks from image`, "success");
        } else {
          showStatus("Extraction failed: " + JSON.stringify(resp.data), "error");
        }
      } catch (e) {
        showStatus("Failed: " + e.message, "error");
      }
    });

    // Parse pasted text
    document.getElementById("mf-parse-paste-btn").addEventListener("click", async () => {
      const text = document.getElementById("mf-paste-area").value.trim();
      if (!text) {
        showStatus("No text to parse", "error");
        return;
      }
      showStatus("Parsing text...", "loading");
      try {
        const resp = await apiRequest("POST", "/api/v1/stocks/parse-import", { text });
        if (resp.status === 200 && resp.data.codes) {
          const existing = new Set(scrapedStocks.map((s) => s.symbol));
          let added = 0;
          for (const item of resp.data.items || []) {
            const sym = item.code;
            if (sym && !existing.has(sym)) {
              scrapedStocks.push({ symbol: sym, name: item.name || sym, price: null, change_percent: null });
              existing.add(sym);
              added++;
            }
          }
          renderStockTags();
          showStatus(`Parsed ${added} stocks from text`, "success");
        } else {
          showStatus("Parse failed", "error");
        }
      } catch (e) {
        showStatus("Failed: " + e.message, "error");
      }
    });

    // ========================================
    // Persona tab handlers
    // ========================================
    let allPersonas = [];
    const personaOverrides = {}; // { stockSymbol: personaId }

    function getPersonaOverrides() {
      return Object.keys(personaOverrides).length ? personaOverrides : undefined;
    }

    document.getElementById("mf-load-personas-btn").addEventListener("click", async () => {
      showStatus("Loading personas...", "loading");
      try {
        const resp = await apiRequest("GET", "/api/v1/fries/personas");
        if (resp.status === 200 && resp.data.personas) {
          allPersonas = resp.data.personas;
          renderPersonas();
          updatePersonaSelects();
          showStatus(`Loaded ${allPersonas.length} personas`, "success");
        } else {
          // Fallback to strategies
          const resp2 = await apiRequest("GET", "/api/v1/agent/strategies");
          if (resp2.status === 200 && resp2.data.strategies) {
            allPersonas = resp2.data.strategies.map((s) => ({
              id: s.id,
              name: s.name,
              description: s.description,
              type: "strategy",
            }));
            renderPersonas();
            updatePersonaSelects();
            showStatus(`Loaded ${allPersonas.length} strategies as personas`, "success");
          } else {
            showStatus("Failed to load personas", "error");
          }
        }
      } catch (e) {
        showStatus("Failed: " + e.message, "error");
      }
    });

    function renderPersonas() {
      const container = document.getElementById("mf-persona-list");
      container.innerHTML = allPersonas
        .map(
          (p) => `
        <div class="mf-persona-card">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" value="${p.id}"
              ${selectedPersonas.includes(p.id) ? "checked" : ""}>
            <div>
              <div class="mf-persona-name">${p.name}</div>
              <div class="mf-persona-desc">${p.description || ""}</div>
            </div>
          </label>
        </div>
      `
        )
        .join("");
      // Bind checkbox events
      container.querySelectorAll('input[type="checkbox"]').forEach((cb) => {
        cb.addEventListener("change", () => {
          if (cb.checked) {
            if (!selectedPersonas.includes(cb.value)) {
              selectedPersonas.push(cb.value);
            }
          } else {
            selectedPersonas = selectedPersonas.filter((p) => p !== cb.value);
          }
        });
      });
    }

    function updatePersonaSelects() {
      // Update stock select
      const stockSelect = document.getElementById("mf-override-stock");
      stockSelect.innerHTML = '<option value="">-- Select Stock --</option>';
      scrapedStocks.forEach((s) => {
        stockSelect.innerHTML += `<option value="${s.symbol}">${s.symbol} ${s.name || ""}</option>`;
      });
      // Update persona select
      const personaSelect = document.getElementById("mf-override-persona");
      personaSelect.innerHTML = '<option value="">-- Select Persona --</option>';
      allPersonas.forEach((p) => {
        personaSelect.innerHTML += `<option value="${p.id}">${p.name}</option>`;
      });
    }

    document.getElementById("mf-apply-override-btn").addEventListener("click", () => {
      const stock = document.getElementById("mf-override-stock").value;
      const persona = document.getElementById("mf-override-persona").value;
      if (!stock || !persona) {
        showStatus("Select both stock and persona", "error");
        return;
      }
      personaOverrides[stock] = persona;
      renderOverrides();
      showStatus(`Override set: ${stock} -> ${persona}`, "success");
    });

    function renderOverrides() {
      const container = document.getElementById("mf-overrides-display");
      const entries = Object.entries(personaOverrides);
      if (!entries.length) {
        container.innerHTML = "";
        return;
      }
      container.innerHTML =
        '<label>Active Overrides</label>' +
        entries
          .map(
            ([stock, persona]) => `
        <div class="mf-stock-tag" style="margin-top:4px">
          <span>${stock} → ${persona}</span>
          <span class="mf-remove" data-stock="${stock}">×</span>
        </div>
      `
          )
          .join("");
      container.querySelectorAll(".mf-remove").forEach((el) => {
        el.addEventListener("click", () => {
          delete personaOverrides[el.dataset.stock];
          renderOverrides();
        });
      });
    }

    // ========================================
    // Settings tab handlers
    // ========================================
    document.getElementById("mf-save-settings-btn").addEventListener("click", () => {
      const val = document.getElementById("mf-api-base-input").value.trim();
      if (val) {
        setApiBase(val);
        showStatus("Settings saved", "success");
      }
    });

    document.getElementById("mf-test-conn-btn").addEventListener("click", async () => {
      showStatus("Testing connection...", "loading");
      try {
        const resp = await apiRequest("GET", "/api/v1/health");
        if (resp.status === 200) {
          showStatus("Connected to API", "success");
        } else {
          showStatus("API returned: " + resp.status, "error");
        }
      } catch (e) {
        showStatus("Connection failed: " + e.message, "error");
      }
    });

    // Initial render
    renderStockTags();
  }

  // ========================================
  // 注册菜单命令
  // ========================================
  GM_registerMenuCommand("Open 薯条交易 Panel", () => {
    const panel = document.getElementById("fries-panel");
    if (panel) panel.classList.add("mf-visible");
  });

  GM_registerMenuCommand("Set API URL", () => {
    const url = prompt("Enter API Base URL:", getApiBase());
    if (url) {
      setApiBase(url);
      const input = document.getElementById("mf-api-base-input");
      if (input) input.value = url;
    }
  });

  // ========================================
  // 初始化
  // ========================================
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createPanel);
  } else {
    createPanel();
  }
})();
