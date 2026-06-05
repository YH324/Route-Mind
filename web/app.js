const goalInput = document.getElementById("goalInput");
const sessionInput = document.getElementById("sessionInput");
const userInput = document.getElementById("userInput");
const modeSelect = document.getElementById("modeSelect");
const centerSelect = document.getElementById("centerSelect");
const radiusSelect = document.getElementById("radiusSelect");
const locateButton = document.getElementById("locateButton");
const clearSessionButton = document.getElementById("clearSessionButton");
const clearProfileButton = document.getElementById("clearProfileButton");
const locationText = document.getElementById("locationText");
const runButton = document.getElementById("runButton");
const statusText = document.getElementById("statusText");
const resultSection = document.getElementById("resultSection");
const resultMeta = document.getElementById("resultMeta");
const variantTabs = document.getElementById("variantTabs");
const variantPanels = document.getElementById("variantPanels");
const loadMs = document.getElementById("loadMs");
const planMs = document.getElementById("planMs");
const totalMs = document.getElementById("totalMs");

const CENTER_MAP = {
  chunxi:  { lat: 30.657, lng: 104.082, name: "春熙路" },
  chengdu: { lat: 30.674447, lng: 104.047296, name: "天府广场" },
};

const VARIANT_COLORS = {
  efficient: "#2563eb",
  relaxed: "#059669",
  food_first: "#dc2626",
  single_poi: "#2563eb",
};

const MODE_LABELS = {
  tourist: "游客",
  business: "出差",
  resident: "居民",
};

const TYPE_MARKER_COLORS = {
  餐饮: "#dc2626",
  景点: "#2563eb",
  购物: "#f59e0b",
  休闲: "#8b5cf6",
  其他: "#6b7280",
};

let currentLocation = null;
let currentResult = null;
let map = null;
let activeLayers = [];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function setStatus(text) {
  statusText.textContent = text;
}

function updateLocationText(text) {
  locationText.textContent = text;
}

centerSelect.addEventListener("change", () => {
  const c = CENTER_MAP[centerSelect.value];
  updateLocationText(`已选择：${c.name} (${c.lng}, ${c.lat})`);
  currentLocation = null;
});

function useMyLocation() {
  if (!navigator.geolocation) {
    updateLocationText("浏览器不支持定位，使用默认位置");
    return;
  }
  locateButton.disabled = true;
  updateLocationText("正在定位...");
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      currentLocation = {
        lat: Number(pos.coords.latitude.toFixed(6)),
        lng: Number(pos.coords.longitude.toFixed(6))
      };
      updateLocationText(`当前位置：${currentLocation.lng}, ${currentLocation.lat}`);
      locateButton.disabled = false;
    },
    (err) => {
      updateLocationText(`定位失败：${err.message}`);
      locateButton.disabled = false;
    },
    { enableHighAccuracy: true, timeout: 10000 }
  );
}

function formatTime(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (h > 0) return `${h}小时${m}分钟`;
  return `${m}分钟`;
}

function clearMap() {
  if (!map) return;
  activeLayers.forEach(layer => map.removeLayer(layer));
  activeLayers = [];
}

function getCategory(typeName) {
  const cats = {
    景点: ["景点", "公园", "游乐园"],
    餐饮: ["火锅", "烧烤", "中餐", "小吃", "外国菜", "甜品", "饮品"],
    购物: ["商场", "超市", "便利店", "数码", "服饰", "美妆", "家居", "购物"],
    休闲: ["茶馆", "KTV", "酒吧", "电影院", "健身", "按摩SPA", "休闲", "农家乐"],
  };
  for (const [cat, types] of Object.entries(cats)) {
    if (types.includes(typeName)) return cat;
  }
  return "其他";
}

function renderMap(variant) {
  if (!map) return;
  clearMap();

  const color = VARIANT_COLORS[variant.variant_id] || "#2563eb";
  const route = variant.route || [];
  const recommendations = variant.recommendations || [];
  if (route.length === 0 && recommendations.length === 0) return;

  // 收集所有坐标用于 fitBounds
  const allCoords = [];

  // 起点标记
  const startLoc = variant.start_location;
  if (startLoc) {
    const startMarker = L.circleMarker([startLoc.lat, startLoc.lng], {
      radius: 8,
      fillColor: "#10b981",
      color: "#fff",
      weight: 2,
      opacity: 1,
      fillOpacity: 1,
    }).addTo(map);
    startMarker.bindPopup("起点");
    activeLayers.push(startMarker);
    allCoords.push([startLoc.lat, startLoc.lng]);
  }

  // POI 标记和路线
  route.forEach((step, i) => {
    const loc = step.location;
    if (!loc) return;
    allCoords.push([loc.lat, loc.lng]);

    const cat = getCategory(step.type);
    const markerColor = TYPE_MARKER_COLORS[cat] || TYPE_MARKER_COLORS["其他"];

    const marker = L.circleMarker([loc.lat, loc.lng], {
      radius: 10,
      fillColor: markerColor,
      color: "#fff",
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9,
    }).addTo(map);
    marker.bindPopup(`<b>${escapeHtml(step.name)}</b><br>[${escapeHtml(step.type)}]<br>到达: ${escapeHtml(step.arrival_time)} | 停留: ${escapeHtml(step.stay_minutes)}min`);
    activeLayers.push(marker);

    // 路线段
    let polylineCoords = [];
    if (i === 0 && step.move_from_start) {
      const from = step.move_from_start.from_location;
      const to = step.move_from_start.to_location;
      polylineCoords = [[from.lat, from.lng], [to.lat, to.lng]];
    } else if (i > 0 && step.move_from_prev) {
      if (step.move_from_prev.polyline && step.move_from_prev.polyline.length > 0) {
        polylineCoords = step.move_from_prev.polyline;
      } else {
        const prev = route[i - 1].location;
        if (prev) {
          polylineCoords = [[prev.lat, prev.lng], [loc.lat, loc.lng]];
        }
      }
    }

    if (polylineCoords.length >= 2) {
      const line = L.polyline(polylineCoords, {
        color: color,
        weight: 4,
        opacity: 0.7,
        dashArray: i === 0 ? "8, 6" : null, // 起点到第一站用虚线
      }).addTo(map);
      activeLayers.push(line);
    }
  });

  recommendations.forEach((rec, i) => {
    const loc = rec.location;
    if (!loc) return;
    allCoords.push([loc.lat, loc.lng]);

    const cat = rec.category || getCategory(rec.type);
    const markerColor = TYPE_MARKER_COLORS[cat] || TYPE_MARKER_COLORS["其他"];

    const marker = L.circleMarker([loc.lat, loc.lng], {
      radius: 10,
      fillColor: markerColor,
      color: "#fff",
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9,
    }).addTo(map);
    marker.bindPopup(`<b>${i + 1}. ${escapeHtml(rec.name)}</b><br>[${escapeHtml(rec.type)}]<br>评分: ${escapeHtml(rec.score)}`);
    activeLayers.push(marker);
  });

  // 适应视野
  if (allCoords.length > 0) {
    map.fitBounds(L.latLngBounds(allCoords), { padding: [40, 40], maxZoom: 16 });
  }
}

function renderVariant(variant, index) {
  const route = variant.route || [];
  const recommendations = variant.recommendations || [];
  const routeSteps = route.map((step, i) => {
    const move = step.move_from_prev;
    const moveHtml = move
      ? `<div class="move-line">
           <span class="move-arrow">&#8595;</span>
           <span class="move-info">${Math.round(move.distance_m)}m / ${Math.round(move.time_min)}min</span>
         </div>`
      : "";

    const startMove = step.move_from_start;
    const startMoveHtml = startMove && i === 0
      ? `<div class="move-line start-move">
           <span class="move-arrow">&#8595;</span>
           <span class="move-info">起点 → ${Math.round(startMove.distance_m)}m / ${Math.round(startMove.time_min)}min</span>
         </div>`
      : "";

    const gt = step.ground_truth || {};
    const gtStr = gt.overall ? `GT:${escapeHtml(gt.overall)}` : "";

    return `
      ${startMoveHtml}
      <div class="step">
        <div class="step-num">${step.order}</div>
        <div class="step-body">
          <div class="step-title">
            <span class="step-name">${escapeHtml(step.name)}</span>
            <span class="step-type">[${escapeHtml(step.type)}]</span>
            ${gtStr ? `<span class="step-gt">${gtStr}</span>` : ""}
          </div>
          <div class="step-time">
            <span class="time-badge">${escapeHtml(step.arrival_time)} - ${escapeHtml(step.departure_time)}</span>
            <span class="stay-badge">停留 ${escapeHtml(step.stay_minutes)}min</span>
          </div>
        </div>
      </div>
      ${moveHtml}
    `;
  }).join("");

  const recSteps = recommendations.map((rec, i) => {
    const gt = rec.ground_truth || {};
    const hours = rec.business_hours || {};
    const gtStr = gt.overall ? `GT:${escapeHtml(gt.overall)}` : "";
    const hoursStr = hours.open_time && hours.close_time ? `${escapeHtml(hours.open_time)}-${escapeHtml(hours.close_time)}` : "";
    return `
      <div class="step">
        <div class="step-num">${i + 1}</div>
        <div class="step-body">
          <div class="step-title">
            <span class="step-name">${escapeHtml(rec.name)}</span>
            <span class="step-type">[${escapeHtml(rec.type)}]</span>
            ${gtStr ? `<span class="step-gt">${gtStr}</span>` : ""}
          </div>
          <div class="step-time">
            ${hoursStr ? `<span class="time-badge">${hoursStr}</span>` : ""}
            <span class="stay-badge">评分 ${escapeHtml(rec.score)}</span>
          </div>
        </div>
      </div>
    `;
  }).join("");

  const steps = routeSteps || recSteps || `<div class="empty-state">当前条件下没有可展示的地点</div>`;

  const stats = [
    `POI: ${variant.poi_count}个`,
    route.length ? `总时间: ${formatTime(variant.total_time_minutes)}` : "类型: 单点推荐",
    route.length ? `移动: ${Math.round(variant.total_move_distance)}m / ${Math.round(variant.total_move_time)}min` : "",
    route.length ? `利用率: ${Math.round(variant.time_utilization * 100)}%` : ""
  ].filter(Boolean).join(" | ");

  return `
    <div class="variant-panel ${index === 0 ? "active" : ""}" data-index="${index}">
      <div class="variant-header">
        <h3>${escapeHtml(variant.name)}</h3>
        <p class="variant-desc">${escapeHtml(variant.description)}</p>
        <div class="variant-stats">${stats}</div>
      </div>
      <div class="timeline">${steps}</div>
    </div>
  `;
}

function renderTabs(variants) {
  variantTabs.innerHTML = variants.map((variant, i) => `
    <button class="tab-btn ${i === 0 ? "active" : ""}" data-variant="${i}">${escapeHtml(variant.name || `方案${i + 1}`)}</button>
  `).join("");
}

function showMapFallback() {
  const mapEl = document.getElementById("map");
  if (!mapEl) return;
  mapEl.classList.add("map-fallback");
  mapEl.textContent = "地图资源未加载，路线列表仍可查看";
}

function renderResult(data) {
  const result = data.result || {};
  const perf = data.performance || {};
  currentResult = result;

  const constraints = result.constraints || {};
  const c = constraints;
  const interaction = data.interaction || c.interaction || {};
  const needs = interaction.user_needs || c.user_needs || {};
  resultMeta.innerHTML = `
    <span class="meta-pill">目标: ${escapeHtml(c.raw_goal || "")}</span>
    <span class="meta-pill">模式: ${escapeHtml(c.user_mode_label || MODE_LABELS[c.user_mode] || "游客")}</span>
    <span class="meta-pill">预算: ${escapeHtml(c.time_budget_hours || 4)}h</span>
    <span class="meta-pill">方式: ${escapeHtml(c.mode || "walk")}</span>
    <span class="meta-pill">偏好: ${escapeHtml((c.preferred_tags || []).join(","))}</span>
    <span class="meta-pill">起始: ${escapeHtml(c.start_time || "09:00")}</span>
    <span class="meta-pill">半径: ${escapeHtml(c.radius || 3000)}m</span>
    <span class="meta-pill">单段≤${escapeHtml(c.max_travel_min || 30)}min</span>
    ${interaction.intent_hint ? `<span class="meta-pill">交互意图: ${escapeHtml(interaction.intent_hint)}</span>` : ""}
    ${(interaction.memory_applied || []).length ? `<span class="meta-pill">记忆: ${escapeHtml(interaction.memory_applied.join(","))}</span>` : ""}
    ${(needs.labels || []).length ? `<span class="meta-pill">需求: ${escapeHtml(needs.labels.join(","))}</span>` : ""}
    ${(interaction.conflicts || []).length ? `<span class="meta-pill warn">冲突: ${escapeHtml(interaction.conflicts.length)}</span>` : ""}
    ${data.notice ? `<span class="meta-pill warn">提示: ${escapeHtml(data.notice)}</span>` : ""}
  `;

  const variants = result.variants || [];
  renderTabs(variants);
  variantPanels.innerHTML = variants.map((v, i) => renderVariant(v, i)).join("");

  loadMs.textContent = perf.load_ms || "-";
  planMs.textContent = perf.plan_ms || "-";
  totalMs.textContent = perf.total_ms || "-";

  resultSection.hidden = false;

  // 初始化地图（延迟确保 DOM 已渲染）
  if (!map) {
    setTimeout(() => {
      if (typeof L === "undefined") {
        showMapFallback();
        return;
      }
      const startLoc = variants[0]?.start_location || { lat: 30.657, lng: 104.082 };
      map = L.map('map').setView([startLoc.lat, startLoc.lng], 14);
      // 使用高德瓦片，国内访问更稳定
      L.tileLayer('https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}', {
        subdomains: '1234',
        attribution: '&copy; 高德地图'
      }).addTo(map);
      if (variants.length > 0) {
        renderMap(variants[0]);
      }
    }, 100);
  } else {
    setTimeout(() => {
      map.invalidateSize();
      if (variants.length > 0) {
        renderMap(variants[0]);
      }
    }, 100);
  }

  resultSection.scrollIntoView({ behavior: "smooth" });

  // 绑定标签页切换
  document.querySelectorAll(".tab-btn").forEach((btn, i) => {
    btn.classList.toggle("active", i === 0);
    btn.onclick = () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".variant-panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      const panel = document.querySelector(`.variant-panel[data-index="${i}"]`);
      if (panel) panel.classList.add("active");
      if (map) map.invalidateSize();
      if (variants[i]) renderMap(variants[i]);
    };
  });
}

function parseDialogue(text) {
  const lines = text.split(/\n+/).map(line => line.trim()).filter(Boolean);
  const messages = [];
  lines.forEach(line => {
    const match = line.match(/^([^:：]{1,16})[:：]\s*(.+)$/);
    if (match) {
      messages.push({ speaker_id: match[1].trim(), text: match[2].trim() });
    }
  });
  return messages.length >= 2 ? messages : null;
}

async function runPlanner() {
  const goal = goalInput.value.trim();
  if (!goal) {
    setStatus("请输入目标");
    return;
  }

  const payload = {
    goal,
    radius: Number(radiusSelect.value),
    user_mode: modeSelect.value,
    session_id: sessionInput.value.trim() || "demo-session",
    user_id: userInput.value.trim() || undefined,
  };
  const dialogue = parseDialogue(goal);
  if (dialogue) {
    payload.dialogue = dialogue;
  }

  if (currentLocation) {
    payload.center_lat = currentLocation.lat;
    payload.center_lng = currentLocation.lng;
  } else {
    const c = CENTER_MAP[centerSelect.value];
    payload.center_lat = c.lat;
    payload.center_lng = c.lng;
    payload.city = centerSelect.value;
  }

  runButton.disabled = true;
  setStatus("规划中...");
  resultSection.hidden = true;

  try {
    const response = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "请求失败");
    }
    renderResult(data);
    setStatus("规划完成");
  } catch (error) {
    setStatus(`错误: ${error.message}`);
    console.error(error);
  } finally {
    runButton.disabled = false;
  }
}

runButton.addEventListener("click", runPlanner);
locateButton.addEventListener("click", useMyLocation);
clearSessionButton.addEventListener("click", async () => {
  const sessionId = sessionInput.value.trim() || "demo-session";
  try {
    await fetch("/api/session/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId })
    });
    setStatus("会话记忆已清除");
  } catch (error) {
    setStatus(`清除失败: ${error.message}`);
  }
});

clearProfileButton.addEventListener("click", async () => {
  const userId = userInput.value.trim();
  if (!userId) {
    setStatus("请输入用户ID");
    return;
  }
  try {
    const response = await fetch("/api/profile/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId })
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "清除失败");
    }
    setStatus(data.cleared ? "长期画像已清除" : "没有可清除的长期画像");
  } catch (error) {
    setStatus(`清除失败: ${error.message}`);
  }
});
