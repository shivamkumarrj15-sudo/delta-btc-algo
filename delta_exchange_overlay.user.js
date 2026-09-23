// ==UserScript==
// @name         Delta Exchange - BTC Algo Bot Visual Overlay
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  Automatically displays Bot's 1D/1H Levels, Fight Detection, and Trade Logic directly on Delta Exchange Web Chart!
// @author       Antigravity Algo
// @match        https://india.delta.exchange/*
// @match        https://*.delta.exchange/*
// @grant        GM_xmlhttpRequest
// @connect      localhost
// ==/UserScript==

(function() {
    'use strict';

    console.log("⚡ Delta BTC Algo Overlay script active on Delta Exchange!");

    // Create Floating HUD Container on Delta Exchange
    const hud = document.createElement('div');
    hud.id = 'delta-algo-hud';
    hud.style.position = 'fixed';
    hud.style.top = '70px';
    hud.style.right = '20px';
    hud.style.width = '340px';
    hud.style.background = 'rgba(22, 27, 34, 0.95)';
    hud.style.border = '1px solid #30363d';
    hud.style.borderRadius = '8px';
    hud.style.boxShadow = '0 8px 24px rgba(0,0,0,0.6)';
    hud.style.zIndex = '999999';
    hud.style.padding = '14px';
    hud.style.fontFamily = 'Inter, -apple-system, sans-serif';
    hud.style.fontSize = '12px';
    hud.style.color = '#c9d1d9';
    hud.style.backdropFilter = 'blur(6px)';

    hud.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid #30363d; padding-bottom:8px; margin-bottom:10px;">
            <span style="font-weight:700; color:#58a6ff; font-size:13px;">⚡ BOT TRADE LOGIC OVERLAY</span>
            <span id="bot-status-tag" style="background:#2ea04322; color:#2ea043; border:1px solid #2ea043; padding:2px 6px; border-radius:4px; font-size:10px; font-weight:600;">● LIVE SYNC</span>
        </div>
        <div id="bot-strategy-box" style="background:#0d1117; border:1px solid #30363d; border-radius:6px; padding:10px; margin-bottom:10px;">
            <div style="color:#8b949e; font-size:11px; margin-bottom:4px;">CURRENT STRATEGY STAGE:</div>
            <div id="bot-stage-desc" style="font-weight:600; color:#f0f6fc;">🔍 Scanning 1D & 1H Key Levels for Buyer/Seller Fight...</div>
        </div>
        <div style="margin-bottom:8px; font-weight:600; color:#8b949e; font-size:11px;">BOT'S MARKED LEVELS ON THIS CHART:</div>
        <div id="bot-levels-list" style="display:flex; flex-direction:column; gap:4px; max-height:120px; overflow-y:auto; font-family:monospace; font-size:11px;">
            <div>Loading levels from local bot...</div>
        </div>
        <div id="bot-trade-info" style="margin-top:10px; display:none;"></div>
    `;

    document.body.appendChild(hud);

    // Poll local bot server for real-time levels & trade logic
    function syncWithBot() {
        if (typeof GM_xmlhttpRequest !== 'undefined') {
            GM_xmlhttpRequest({
                method: "GET",
                url: "http://localhost:8501/api/levels",
                onload: function(response) {
                    try {
                        const data = JSON.parse(response.responseText);
                        updateHud(data);
                    } catch (e) {}
                },
                onerror: function() {
                    document.getElementById('bot-status-tag').innerText = '○ BOT OFFLINE';
                    document.getElementById('bot-status-tag').style.color = '#f85149';
                }
            });
        } else {
            fetch("http://localhost:8501/api/levels")
                .then(r => r.json())
                .then(data => updateHud(data))
                .catch(() => {
                    document.getElementById('bot-status-tag').innerText = '○ BOT OFFLINE';
                });
        }
    }

    function updateHud(data) {
        document.getElementById('bot-status-tag').innerText = '● LIVE SYNC';
        document.getElementById('bot-status-tag').style.color = '#2ea043';

        const list = document.getElementById('bot-levels-list');
        list.innerHTML = '';

        if (data.levels && data.levels.length > 0) {
            data.levels.forEach(lvl => {
                const isSupport = lvl.level_type.includes('SUPPORT') || lvl.description.includes('PDL');
                const color = isSupport ? '#2ea043' : '#f85149';
                const row = document.createElement('div');
                row.innerHTML = `<span style="color:${color}; font-weight:700;">[${lvl.timeframe.toUpperCase()}]</span> ${lvl.description.split('(')[0]}: <b>$${Number(lvl.price).toLocaleString()}</b>`;
                list.appendChild(row);
            });
        }
    }

    setInterval(syncWithBot, 2000);
    syncWithBot();
})();
