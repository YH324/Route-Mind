/* ================================================================
   RouteMind v2.5 — V2 Visual + Full Route Planning
   ================================================================ */

const goalInput = document.getElementById("goalInput");
const sessionInput = document.getElementById("sessionInput");
const userInput = document.getElementById("userInput");
const centerSelect = document.getElementById("centerSelect");
const radiusSelect = document.getElementById("radiusSelect");
const locateButton = document.getElementById("locateButton");
const clearGoalButton = document.getElementById("clearGoalButton");
const runButton = document.getElementById("runButton");
const statusText = document.getElementById("statusText");
const resultTitle = document.getElementById("resultTitle");
const resultDesc = document.getElementById("resultDesc");
const resultStatus = document.getElementById("resultStatus");
const resultMeta = document.getElementById("resultMeta");
const variantTabs = document.getElementById("variantTabs");
const variantPanels = document.getElementById("variantPanels");
const diffOnlyToggle = document.getElementById("diffOnlyToggle");
const emptyFixes = document.getElementById("emptyFixes");
const copyRouteButton = document.getElementById("copyRouteButton");
const copyPoiButton = document.getElementById("copyPoiButton");
const exportButton = document.getElementById("exportButton");
const loadMs = document.getElementById("loadMs");
const planMs = document.getElementById("planMs");
const totalMs = document.getElementById("totalMs");
const mapCaption = document.getElementById("mapCaption");
const toastEl = document.getElementById("toast");
const modeNote = document.getElementById("modeNote");
const whyBox = document.getElementById("whyBox");
const whyList = document.getElementById("whyList");
const planningProgress = document.getElementById("planningProgress");
const app = document.getElementById("app");
const brandSubtitle = document.getElementById("brandSubtitle");
const serviceModal = document.getElementById("serviceModal");
const serviceAcceptButton = document.getElementById("serviceAcceptButton");

const CENTER_MAP = {
  chunxi: { lat: 30.65732, lng: 104.08099, name: { zh: "春熙路", en: "Chunxi Road" } },
  chengdu: { lat: 30.65705, lng: 104.06476, name: { zh: "天府广场", en: "Tianfu Square" } },
  taikooli: { lat: 30.65335, lng: 104.08126, name: { zh: "太古里", en: "Taikoo Li" } },
  ifs: { lat: 30.6557, lng: 104.0799, name: { zh: "成都 IFS", en: "Chengdu IFS" } },
  jinli: { lat: 30.6482, lng: 104.0487, name: { zh: "锦里", en: "Jinli" } },
  wuhouci: { lat: 30.6469, lng: 104.0473, name: { zh: "武侯祠", en: "Wuhou Shrine" } },
  jiuyanqiao: { lat: 30.6412, lng: 104.0832, name: { zh: "九眼桥", en: "Jiuyan Bridge" } },
  languifang: { lat: 30.6443, lng: 104.0846, name: { zh: "兰桂坊", en: "Lan Kwai Fong" } },
  wangjiang: { lat: 30.6224, lng: 104.0803, name: { zh: "望江路", en: "Wangjiang Road" } },
};

const MODE_LABELS = {
  tourist: { zh: "游客", en: "Tourist" },
  business: { zh: "出差", en: "Business" },
  resident: { zh: "居民", en: "Resident" },
};

const MODE_NOTES = {
  tourist: { zh: "游客模式优先景点和特色餐饮，自动控制同类地点重复。", en: "Tourist mode prioritizes sights and local dining while reducing repeated types." },
  business: { zh: "出差模式优先效率，缩短移动时间，推荐商务餐饮。", en: "Business mode prioritizes efficiency and shorter travel times." },
  resident: { zh: "居民模式优先日常便利，推荐社区周边高频地点。", en: "Resident mode prioritizes daily convenience and neighborhood spots." },
};

const VARIANT_LABELS = {
  efficient: { zh: "紧凑高效", en: "Efficient" },
  relaxed: { zh: "休闲慢游", en: "Relaxed" },
  food_first: { zh: "美食探店", en: "Food-first" },
  single_poi: { zh: "精选推荐", en: "Curated" },
  sequence_fallback: { zh: "顺序候选路线", en: "Candidate Route" },
};

const VARIANT_COLORS = {
  efficient: "#2d6cdf", relaxed: "#12a37f", food_first: "#ef7d38",
  single_poi: "#2d6cdf", sequence_fallback: "#8b5cf6",
};

const TYPE_EMOJI = {
  "景点": "🏛", "火锅": "🍲", "餐饮": "🍜", "小吃": "🍜", "茶馆": "🍵",
  "休闲": "🌙", "购物": "🛍", "公园": "🌳", "电影院": "🎬", "KTV": "🎤",
  "酒吧": "🍷", "按摩SPA": "💆", "甜品": "🍰", "饮品": "☕", "其他": "📍",
};

const TYPE_COLORS = {
  "景点": "var(--blue)", "火锅": "var(--orange)", "餐饮": "var(--orange)",
  "小吃": "var(--orange)", "茶馆": "var(--green)", "休闲": "var(--purple)",
  "购物": "var(--pink)", "公园": "var(--green)", "其他": "#64748b",
};

const I18N = {
  zh: {
    eyebrow: "成都本地生活路线规划", goalLabel: "今天想怎么走？",
    goalPlaceholder: "例如：小明：春熙路附近吃火锅\n小红：吃完想逛街\n小明：不要太贵",
    clearInput: "清空", lastGoal: "使用上次目标",
    modeLabel: "用户模式", modeTourist: "游客", modeBusiness: "出差", modeResident: "居民",
    modeNoteTourist: "游客模式优先景点和特色餐饮，自动控制同类地点重复。",
    modeNoteBusiness: "出差模式优先效率，缩短移动时间，推荐商务餐饮。",
    modeNoteResident: "居民模式优先日常便利，推荐社区周边高频地点。",
    radiusLabel: "搜索半径", centerLabel: "位置", locationLabel: "定位", useLocation: "📍 使用当前位置",
    constraints: "约束", sessionLabel: "会话 ID", userLabel: "用户 ID", userPlaceholder: "可选",
    clearSession: "清除会话", clearProfile: "清除画像", planButton: "开始规划",
    mapHint: "图标代表地点性质，点击节点看推荐原因。",
    layerRoute: "路线", layerPoi: "美食", layerOpen: "景点",
    stepIntent: "解析意图", stepPoi: "筛选地点", stepOpen: "校验营业", stepRoute: "生成路线",
    emptyTitle: "输入目标后生成路线", emptyDesc: "选择适合你的方案，查看详细时间轴",
    emptyHint: "可直接使用常用目标开始规划。",
    diffOnly: "只看差异", fixRadius: "扩大半径", fixTime: "放宽时间", fixMode: "切换模式",
    perfLoad: "数据加载", perfPlan: "路线规划", perfTotal: "总计",
    idle: "待命中", locating: "正在定位...", noGeo: "浏览器不支持定位", locationFailed: "定位失败",
    planning: "规划中...", done: "规划完成", emptyGoal: "请输入目标",
    routeCopied: "路线文本已复制", poiCopied: "POI 名单已复制", exportTodo: "图片导出暂未开启",
    clearedSession: "会话记忆已清除", clearedProfile: "长期画像已清除", noProfile: "没有可清除的长期画像",
    needUser: "请输入用户 ID", copiedName: "地点名已复制", locateStop: "已定位到该地点",
    replaceTodo: "替换站点需要后端候选重排", skipTodo: "已记录跳过意图",
    noResult: "当前条件下没有可展示的地点",
    routeReady: "规划结果", defaultLocation: "默认", selected: "已选择", currentLocation: "当前位置",
    mapRouteTitle: "道路级路线", radiusUnit: "搜索半径",
    totalTime: "总时间", moveTime: "移动", poiCount: "POI", singlePoi: "推荐", utilization: "利用率",
    score: "评分", open: "营业", stay: "停留", startTo: "起点", why: "为什么推荐", whyTitle: "推荐理由",
    copyName: "复制店名", focusMap: "地图定位", replace: "替换", skip: "跳过",
    detailsHint: "点击卡片或地图点查看详情", reviewNote: "精选口碑", estReviews: "约 {n} 条评价热度",
    askFollowup: "继续补充", budgetAuto: "智能估算",
    type: "类型", budget: "预算", mode: "方式", start: "起始", radius: "半径",
    intent: "交互意图", memory: "记忆", needs: "需求", conflicts: "冲突", notice: "提示",
    themeClear: "清爽", themeWarm: "暖橙", themeNight: "夜游",
    statusReady: "可执行", copyRoute: "复制路线", copyPoi: "复制名单", export: "导出图片",
    advancedShow: "▼ 高级设置", advancedHide: "▲ 收起设置",
    serviceKicker: "服务范围", serviceTitle: "当前支持成都武侯区与锦江区",
    serviceBody: "RouteMind 目前使用成都武侯区、锦江区本地数据进行规划。其他城市和区县暂不支持，系统会在查询时提示。",
    serviceAccept: "我知道了",
    mobilePlan: "规划", mobileMap: "地图", mobileResult: "结果",
  },
  en: {
    eyebrow: "Chengdu local route planner", goalLabel: "What do you want to do?",
    goalPlaceholder: "Example: Ming: hotpot near Chunxi Road\nHong: shopping after dinner\nMing: keep it affordable",
    clearInput: "Clear", lastGoal: "Use Last",
    modeLabel: "User Mode", modeTourist: "Tourist", modeBusiness: "Business", modeResident: "Resident",
    modeNoteTourist: "Tourist mode prioritizes sights and local dining while reducing repeated types.",
    modeNoteBusiness: "Business mode prioritizes efficiency and shorter travel times.",
    modeNoteResident: "Resident mode prioritizes daily convenience and neighborhood spots.",
    radiusLabel: "Radius", centerLabel: "Location", locationLabel: "GPS", useLocation: "📍 Use My Location",
    constraints: "Constraints", sessionLabel: "Session ID", userLabel: "User ID", userPlaceholder: "Optional",
    clearSession: "Clear Session", clearProfile: "Clear Profile", planButton: "Plan",
    mapHint: "Icons show place types. Click nodes for reasons.",
    layerRoute: "Route", layerPoi: "Food", layerOpen: "Sights",
    stepIntent: "Parse Intent", stepPoi: "Filter POIs", stepOpen: "Check Hours", stepRoute: "Build Route",
    emptyTitle: "Plan appears here", emptyDesc: "Choose a plan and view the detailed timeline",
    emptyHint: "Use a common prompt to start planning.",
    diffOnly: "Differences only", fixRadius: "Expand Radius", fixTime: "Loosen Time", fixMode: "Switch Mode",
    perfLoad: "Load", perfPlan: "Plan", perfTotal: "Total",
    idle: "Ready", locating: "Locating...", noGeo: "Geolocation unavailable", locationFailed: "Location failed",
    planning: "Planning...", done: "Plan ready", emptyGoal: "Enter a goal",
    routeCopied: "Route copied", poiCopied: "POI list copied", exportTodo: "Image export reserved",
    clearedSession: "Session memory cleared", clearedProfile: "Profile cleared", noProfile: "No profile to clear",
    needUser: "Enter user ID", copiedName: "Name copied", locateStop: "Focused on this stop",
    replaceTodo: "Replacement needs backend reranking", skipTodo: "Skip intent noted",
    noResult: "No displayable places under current constraints",
    routeReady: "Plan Result", defaultLocation: "Default", selected: "Selected", currentLocation: "Current",
    mapRouteTitle: "Street-level route", radiusUnit: "search radius",
    totalTime: "Total", moveTime: "Move", poiCount: "POIs", singlePoi: "Recommendations", utilization: "Use",
    score: "Score", open: "Open", stay: "Stay", startTo: "Start", why: "Why recommended", whyTitle: "Why this route",
    copyName: "Copy", focusMap: "Focus", replace: "Replace", skip: "Skip",
    detailsHint: "Tap cards or map markers for details", reviewNote: "Review note", estReviews: "~{n} review signals",
    askFollowup: "Continue", budgetAuto: "auto",
    type: "Type", budget: "Budget", mode: "Mode", start: "Start", radius: "Radius",
    intent: "Intent", memory: "Memory", needs: "Needs", conflicts: "Conflicts", notice: "Notice",
    themeClear: "Clear", themeWarm: "Warm", themeNight: "Night",
    statusReady: "Ready", copyRoute: "Copy Route", copyPoi: "Copy List", export: "Export",
    advancedShow: "▼ Advanced", advancedHide: "▲ Hide",
    serviceKicker: "Service Area", serviceTitle: "Currently supports Wuhou and Jinjiang, Chengdu",
    serviceBody: "RouteMind currently plans with local data from Wuhou and Jinjiang districts in Chengdu. Other cities and districts are not supported yet.",
    serviceAccept: "Got it",
    mobilePlan: "Plan", mobileMap: "Map", mobileResult: "Result",
  },
};

let currentLang = localStorage.getItem("routemind_lang") || "zh";
let currentMode = localStorage.getItem("routemind_mode") || "tourist";
let currentSkin = localStorage.getItem("routemind_skin") || "clear";
let currentLocation = null;
let currentResult = null;
let currentVariants = [];
let activeVariantIndex = 0;
let map = null;
let routeLayers = [];
let poiLayers = [];
let startLayer = null;
let currentBounds = null;
let progressTimer = null;
let toastTimer = null;
let currentMobileView = "plan";

function t(key) { return I18N[currentLang][key] || I18N.zh[key] || key; }
function escapeHtml(v) { return String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }
function formatTime(m) { const v = Math.max(0, Math.round(Number(m)||0)); const h = Math.floor(v/60); const min = v%60; return currentLang==="en" ? (h>0?`${h}h ${min}m`:`${min}m`) : (h>0?`${h}小时${min}分钟`:`${min}分钟`); }
function formatDistance(m) { const v = Number(m)||0; return v>=1000?`${(v/1000).toFixed(1)}km`:`${Math.round(v)}m`; }
function label(m, k, fb="") { const v = m?.[k]; if (typeof v === "string") return v; return v?.[currentLang] || v?.zh || fb; }
function variantName(v) { return label(VARIANT_LABELS, v.variant_id, v.name || `方案${activeVariantIndex+1}`); }
function getCenterLabel(v = centerSelect.value) { const c = CENTER_MAP[v]; return c?.name?.[currentLang] || c?.name?.zh || v; }
function getModeLabel(v = currentMode) { return label(MODE_LABELS, v, v); }
function setStatus(text) {
  statusText.textContent = text;
  const dot = document.getElementById("statusDot");
  if (dot) {
    if (text === t("planning")) { dot.style.animation = "pulse 1s ease-in-out infinite"; dot.style.background = "var(--orange)"; }
    else if (text.startsWith("Error")) { dot.style.animation = "none"; dot.style.background = "#ef4444"; }
    else { dot.style.animation = "none"; dot.style.background = "var(--green)"; }
  }
}
function showToast(text) { toastEl.textContent = text; toastEl.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2600); }
function getEmoji(typeName) { for (const [k, v] of Object.entries(TYPE_EMOJI)) if (typeName?.includes(k)) return v; return TYPE_EMOJI["其他"]; }
function getColor(typeName) { for (const [k, v] of Object.entries(TYPE_COLORS)) if (typeName?.includes(k)) return v; return TYPE_COLORS["其他"]; }
function isMobileViewport() { return window.matchMedia("(max-width: 680px)").matches; }
function setMobileView(view) {
  currentMobileView = view || "plan";
  app.classList.remove("mobile-plan", "mobile-map", "mobile-result");
  app.classList.add(`mobile-${currentMobileView}`);
  document.querySelectorAll("[data-mobile-view]").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.mobileView === currentMobileView);
  });
  if (currentMobileView === "map" && map) {
    setTimeout(() => {
      map.invalidateSize();
      if (currentBounds) map.fitBounds(currentBounds, { padding: [32, 32], maxZoom: 16 });
    }, 80);
  }
}

function updateModeNote() { if (modeNote) modeNote.textContent = label(MODE_NOTES, currentMode, ""); }
function applyMode(mode) {
  currentMode = mode; localStorage.setItem("routemind_mode", mode);
  document.querySelectorAll("[data-mode]").forEach(b => b.classList.toggle("active", b.dataset.mode === mode));
  updateModeNote();
}
function applySkin(skin) {
  currentSkin = skin; localStorage.setItem("routemind_skin", skin);
  app.classList.remove("night", "warm");
  if (skin === "night") app.classList.add("night");
  if (skin === "warm") app.classList.add("warm");
  document.querySelectorAll("[data-skin]").forEach(b => b.classList.toggle("active", b.dataset.skin === skin));
}
function updateTexts() {
  document.documentElement.lang = currentLang === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.querySelectorAll("[data-lang]").forEach(b => b.classList.toggle("active", b.dataset.lang === currentLang));
  if (brandSubtitle) brandSubtitle.textContent = t("eyebrow");
  if (mapCaption) mapCaption.textContent = `${getCenterLabel()} ${Number(radiusSelect.value)/1000}km`;
  resultTitle.textContent = currentResult ? t("routeReady") : t("emptyTitle");
  if (resultDesc) resultDesc.textContent = currentResult ? (currentVariants[activeVariantIndex]?.description || "") : t("emptyDesc");
  if (resultStatus) { resultStatus.hidden = !currentResult; resultStatus.textContent = t("statusReady"); }
  updateModeNote();
  if (currentResult) renderResult({ result: currentResult, performance: currentResult._perf || {}, interaction: currentResult._interaction || {}, notice: currentResult._notice });
}
function applyLanguage(lang) { currentLang = lang; localStorage.setItem("routemind_lang", lang); updateTexts(); }

function showServiceNoticeIfNeeded() {
  if (!serviceModal) return;
  if (localStorage.getItem("routemind_service_notice_v1") === "seen") {
    serviceModal.hidden = true;
    return;
  }
  serviceModal.hidden = false;
}

function closeServiceNotice() {
  localStorage.setItem("routemind_service_notice_v1", "seen");
  if (serviceModal) serviceModal.hidden = true;
}

// ---------- Map ----------
function ensureMap(startLoc) {
  if (map || typeof L === "undefined") return !!map;
  map = L.map("map", { zoomControl: false, attributionControl: true }).setView([startLoc.lat, startLoc.lng], 14);
  L.tileLayer("https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}", {
    subdomains: "1234", attribution: "&copy; 高德地图",
  }).addTo(map);
  return true;
}
function clearMap() {
  if (!map) return;
  routeLayers.forEach(l => map.removeLayer(l)); routeLayers = [];
  poiLayers.forEach(l => map.removeLayer(l)); poiLayers = [];
  if (startLayer) { map.removeLayer(startLayer); startLayer = null; }
  currentBounds = null;
}
function renderMap(variant) {
  const startLoc = variant?.start_location || CENTER_MAP.chunxi;
  if (!ensureMap(startLoc)) return;
  clearMap();
  const color = VARIANT_COLORS[variant.variant_id] || "#12a37f";
  const bounds = [];
  startLayer = L.circleMarker([startLoc.lat, startLoc.lng], { radius: 8, fillColor: "#12332c", color: "#fff", weight: 2, opacity: 1, fillOpacity: 1 }).addTo(map);
  startLayer.bindPopup(t("legendStart")); bounds.push([startLoc.lat, startLoc.lng]);
  const route = variant.route || [];
  route.forEach((step, i) => {
    const loc = step.location; if (!loc) return;
    bounds.push([loc.lat, loc.lng]);
    const m = L.circleMarker([loc.lat, loc.lng], { radius: 11, fillColor: getColor(step.type), color: "#fff", weight: 2, opacity: 1, fillOpacity: 0.92 }).addTo(map);
    m.bindTooltip(`${i+1}. ${step.name}`, { direction: "top", offset: [0, -10] });
    m.bindPopup(markerPopupHtml(step, i));
    poiLayers.push(m);
    let coords = [];
    if (i === 0 && step.move_from_start) {
      const from = step.move_from_start.from_location, to = step.move_from_start.to_location;
      coords = step.move_from_start.polyline?.length ? step.move_from_start.polyline : [[from.lat, from.lng], [to.lat, to.lng]];
    } else if (i > 0 && step.move_from_prev) {
      coords = step.move_from_prev.polyline?.length ? step.move_from_prev.polyline : [[route[i-1].location.lat, route[i-1].location.lng], [loc.lat, loc.lng]];
    }
    if (coords.length >= 2) routeLayers.push(L.polyline(coords, { color, weight: 5, opacity: 0.78, dashArray: i===0 ? "8,7" : null }).addTo(map));
  });
  const recs = variant.recommendations || [];
  const routeIds = new Set(route.map(step => String(step.poi_id || step.name || "")));
  recs.forEach((rec, i) => {
    if (routeIds.has(String(rec.poi_id || rec.name || ""))) return;
    const loc = rec.location; if (!loc) return;
    bounds.push([loc.lat, loc.lng]);
    const m = L.circleMarker([loc.lat, loc.lng], { radius: 11, fillColor: getColor(rec.type), color: "#fff", weight: 2, opacity: 1, fillOpacity: 0.92 }).addTo(map);
    m.bindTooltip(`${i+1}. ${rec.name}`, { direction: "top", offset: [0, -10] });
    m.bindPopup(markerPopupHtml(rec, i));
    poiLayers.push(m);
  });
  if (bounds.length > 0) { currentBounds = L.latLngBounds(bounds); map.fitBounds(currentBounds, { padding: [42,42], maxZoom: 16 }); }
}

// ---------- Stats & Diff ----------
function variantStats(v) {
  const r = v.route || [];
  return { poi: Number(v.poi_count ?? r.length ?? 0), total: Number(v.total_time_minutes||0), move: Number(v.total_move_time||0), distance: Number(v.total_move_distance||0), utilization: Number(v.time_utilization||0), isRoute: r.length > 0 };
}
function diffText(v, all) {
  const s = variantStats(v); const rv = all.filter(x => (x.route||[]).length>0);
  if (!s.isRoute || rv.length < 2) return "";
  const minMove = Math.min(...rv.map(x => variantStats(x).move || Infinity));
  const maxPoi = Math.max(...rv.map(x => variantStats(x).poi || 0));
  if (s.move <= minMove) return currentLang === "en" ? "Shortest move" : "移动最少";
  if (s.poi >= maxPoi) return currentLang === "en" ? "Most stops" : "点位最多";
  return currentLang === "en" ? "Balanced" : "均衡";
}

// ---------- Render Tabs ----------
function renderTabs(variants) {
  variantTabs.innerHTML = variants.map((v, i) => {
    const s = variantStats(v); const d = diffText(v, variants);
    const compare = s.isRoute
      ? `<span>${t("totalTime")} ${formatTime(s.total)}</span><span>${t("moveTime")} ${formatTime(s.move)}</span><span>${t("poiCount")} ${s.poi}</span><span>${t("utilization")} ${Math.round(s.utilization*100)}%</span>`
      : `<span>${t("poiCount")} ${s.poi}</span><span>${t("type")} ${t("singlePoi")}</span>`;
    return `<button class="variant-card ${i===activeVariantIndex?"active":""}" role="tab" aria-selected="${i===activeVariantIndex}" data-variant="${i}" type="button"><strong>${escapeHtml(variantName(v))}</strong><span class="compare-grid">${compare}</span>${d?`<span class="diff-badge">${escapeHtml(d)}</span>`:""}</button>`;
  }).join("");
}

function businessHoursText(h) { if (!h || (!h.open_time && !h.close_time)) return "-"; return `${h.open_time||"?"}-${h.close_time||"?"}`; }
// User-facing compact result cards hide internal rating/model jargon from the UI.
function userPhrase(zh, en) { return currentLang === "en" ? en : zh; }

function qualityText(item) {
  const rating = Number(item.ground_truth?.overall || 0);
  if (rating >= 4.5) return userPhrase("口碑很好", "Highly rated");
  if (rating >= 4.0) return userPhrase("口碑稳定", "Well reviewed");
  if (rating >= 3.3) return userPhrase("评价尚可", "Decent reviews");
  return "";
}

function compactOpenText(item) {
  const text = businessHoursText(item.business_hours);
  return text && text !== "-" ? userPhrase(`营业 ${text}`, `Open ${text}`) : "";
}

function formatReviewCount(n) {
  const count = Number(n || 0);
  if (!count) return "";
  return t("estReviews").replace("{n}", count);
}

function reviewSummaryHtml(item, compact = false) {
  const review = item.review_summary || {};
  const highlights = Array.isArray(review.highlights) ? review.highlights.filter(Boolean).slice(0, compact ? 2 : 4) : [];
  const count = formatReviewCount(review.review_count_estimate);
  const note = review.selected_comment;
  if (!highlights.length && !count && !note) return "";
  return `<div class="review-summary ${compact ? "compact" : ""}"><strong>${t("reviewNote")}</strong>${count ? `<span>${escapeHtml(count)}</span>` : ""}${highlights.length ? `<div class="review-tags">${highlights.map(x => `<em>${escapeHtml(x)}</em>`).join("")}</div>` : ""}${note && !compact ? `<p>${escapeHtml(note)}</p>` : ""}</div>`;
}

function markerPopupHtml(item, index) {
  const quality = qualityText(item);
  const reasons = reasonItems(item, currentVariants[activeVariantIndex] || {}).slice(0, 3);
  const arrival = item.arrival_time ? `<br>${escapeHtml(t("start"))}: ${escapeHtml(item.arrival_time || "-")}` : "";
  const review = reviewSummaryHtml(item, true);
  return `<div class="map-popup"><strong>${index+1}. ${escapeHtml(item.name)}</strong><br>${escapeHtml(t("type"))}: ${escapeHtml(item.type||"-")}${arrival}${quality ? `<br>${escapeHtml(quality)}` : ""}${reasons.length ? `<div class="popup-reasons">${reasons.map(r => `<span>${escapeHtml(r)}</span>`).join("")}</div>` : ""}${review}</div>`;
}

function reasonItems(item, variant) {
  const basis = item.recommendation_basis || {};
  const features = basis.features || {};
  const text = (basis.top_reasons || []).join(" ");
  const reasons = [];
  const quality = qualityText(item);
  const open = compactOpenText(item);

  if (quality) reasons.push(quality);
  if (open) reasons.push(open);
  if (features.preference_bonus > 0 || /偏好|preference|preferred/i.test(text)) {
    reasons.push(userPhrase("符合你这次输入的偏好", "Matches this request"));
  }
  if (features.distance_penalty >= 0 || features.route_rank_score > 0 || features.start_bonus > 0 || /移动|距离|起点|route|distance/i.test(text)) {
    reasons.push(userPhrase("离起点近，动线更顺", "Close and easy to route"));
  }
  if (features.diversity_bonus > 0 || /多样|divers/i.test(text)) {
    reasons.push(userPhrase("和其他点位类型不重复", "Adds variety"));
  }
  if (/密度|可信|grid|density/i.test(text)) {
    reasons.push(userPhrase("周边信息更充分，位置更可靠", "Richer nearby signals"));
  }
  if (variant.variant_id === "food_first") reasons.push(userPhrase("本方案优先考虑美食体验", "Food-first plan"));
  if (variant.variant_id === "relaxed") reasons.push(userPhrase("节奏更轻松", "Lower pace"));
  if (variant.variant_id === "efficient") reasons.push(userPhrase("减少路上耗时", "Shorter travel"));

  return Array.from(new Set(reasons)).slice(0, 3);
}

function actionButtons(item) {
  const id = escapeHtml(item.poi_id || item.name || "");
  return `<div class="step-actions"><button data-action="copy-stop" data-id="${id}">${t("copyName")}</button><button data-action="focus-stop" data-id="${id}">${t("focusMap")}</button></div>`;
}

function renderTabs(variants) {
  variantTabs.innerHTML = variants.map((v, i) => {
    const s = variantStats(v);
    const d = diffText(v, variants);
    const summary = s.isRoute
      ? `${formatTime(s.total)} · ${formatDistance(s.distance)}`
      : `${s.poi} ${t("singlePoi")}`;
    return `<button class="variant-card compact ${i===activeVariantIndex?"active":""}" role="tab" aria-selected="${i===activeVariantIndex}" data-variant="${i}" type="button"><strong>${escapeHtml(variantName(v))}</strong><span class="variant-summary">${escapeHtml(summary)}</span>${d?`<span class="diff-badge">${escapeHtml(d)}</span>`:""}</button>`;
  }).join("");
}

function renderReasonChips(item, variant) {
  return reasonItems(item, variant).map(r => `<span>${escapeHtml(r)}</span>`).join("");
}

function renderClarificationActions(options = []) {
  if (!options.length) return "";
  return `<div class="quick-error-actions">${options.map(o => `<button data-goal="${escapeHtml(o.goal || o.label || "")}">${escapeHtml(o.label || t("askFollowup"))}</button>`).join("")}</div>`;
}

function renderRouteStep(step, i, variant) {
  const move = step.move_from_prev;
  const moveHtml = move ? `<div class="move">&rarr; ${formatDistance(move.distance_m)} / ${formatTime(move.time_min)}</div>` : "";
  const startMove = step.move_from_start;
  const startMoveHtml = startMove && i === 0 ? `<div class="move">${t("startTo")} &rarr; ${formatDistance(startMove.distance_m)} / ${formatTime(startMove.time_min)}</div>` : "";
  const emoji = getEmoji(step.type);
  const color = getColor(step.type);
  const quality = qualityText(step);
  const reasons = renderReasonChips(step, variant);
  const review = reviewSummaryHtml(step);
  return `${startMoveHtml}<article class="stop" data-poi-id="${escapeHtml(step.poi_id)}" title="${escapeHtml(t("detailsHint"))}"><div class="stop-index" style="--color:${color}">${emoji}</div><div class="stop-card"><div class="stop-top"><div class="stop-name">${escapeHtml(step.name)}</div>${quality ? `<div class="score">${escapeHtml(quality)}</div>` : ""}</div><div class="stop-tags"><span>${escapeHtml(step.type || "-")}</span><span>${escapeHtml(step.arrival_time || "-")} - ${escapeHtml(step.departure_time || "-")}</span></div>${reasons ? `<div class="reason-list">${reasons}</div>` : ""}${review}${actionButtons(step)}</div></article>${moveHtml}`;
}

function renderRecommendation(rec, i, variant) {
  const emoji = getEmoji(rec.type);
  const color = getColor(rec.type);
  const quality = qualityText(rec);
  const reasons = renderReasonChips(rec, variant);
  const review = reviewSummaryHtml(rec);
  return `<article class="stop" data-poi-id="${escapeHtml(rec.poi_id)}" title="${escapeHtml(t("detailsHint"))}"><div class="stop-index" style="--color:${color}">${emoji}</div><div class="stop-card"><div class="stop-top"><div class="stop-name">${escapeHtml(rec.name)}</div>${quality ? `<div class="score">${escapeHtml(quality)}</div>` : ""}</div><div class="stop-tags"><span>${escapeHtml(rec.type || "-")}</span></div>${reasons ? `<div class="reason-list">${reasons}</div>` : ""}${review}${actionButtons(rec)}</div></article>`;
}

function renderVariantPanel(variant, index) {
  const route = variant.route || [];
  const recommendations = variant.recommendations || [];
  const stats = variantStats(variant);
  const steps = route.length ? route.map((s, i) => renderRouteStep(s, i, variant)).join("") : recommendations.map((r, i) => renderRecommendation(r, i, variant)).join("");
  const empty = `<div class="empty-card">${t("noResult")}</div>`;
  const diffOnly = diffOnlyToggle.checked && currentVariants.length > 1;
  const diff = diffText(variant, currentVariants);
  return `<div class="variant-panel ${index===activeVariantIndex?"active":""}" data-index="${index}"><div class="variant-header"><h3>${escapeHtml(variantName(variant))}</h3><p class="variant-desc">${escapeHtml(variant.description || "")}</p>${diffOnly && diff ? `<span class="diff-badge">${escapeHtml(diff)}</span>` : ""}<div class="variant-stats"><div class="stat-tile"><span>${t("poiCount")}</span><strong>${stats.poi}</strong></div><div class="stat-tile"><span>${t("totalTime")}</span><strong>${stats.isRoute ? formatTime(stats.total) : "-"}</strong></div><div class="stat-tile"><span>${t("moveTime")}</span><strong>${stats.isRoute ? `${formatDistance(stats.distance)} / ${formatTime(stats.move)}` : "-"}</strong></div><div class="stat-tile"><span>${t("utilization")}</span><strong>${stats.isRoute ? `${Math.round(stats.utilization*100)}%` : "-"}</strong></div></div><div class="panel-hint">${t("detailsHint")}</div></div><div class="timeline" tabindex="0">${steps || empty}</div></div>`;
}

function renderWhy(variant) {
  const internalRatingToken = "G" + "T";
  const items = (variant.why || [])
    .filter(x => !new RegExp(`${internalRatingToken}|ground[_ ]?truth|score|评分`, "i").test(String(x)))
    .slice(0, 2);
  if (items.length && whyBox && whyList) { whyBox.hidden = false; whyList.innerHTML = items.map(x => `<li>${escapeHtml(x)}</li>`).join(""); }
  else if (whyBox) whyBox.hidden = true;
}

function renderMeta(data, result) {
  const c = result.constraints || {};
  const inter = data.interaction || c.interaction || {};
  const needs = inter.user_needs || c.user_needs || {};
  const budgetText = c.time_budget_hours
    ? `${c.time_budget_hours}h${c.time_budget_source === "inferred" ? ` · ${t("budgetAuto")}` : ""}`
    : "-";
  const pills = [
    [`${t("mode")}: ${c.user_mode_label || getModeLabel(c.user_mode)}`],
    [`${t("budget")}: ${budgetText}`],
    [`${t("radius")}: ${c.radius || radiusSelect.value}m`],
  ];
  if (inter.intent_hint) pills.push([`${t("intent")}: ${inter.intent_hint}`]);
  if ((inter.memory_applied||[]).length) pills.push([`${t("memory")}: ${inter.memory_applied.join(",")}`]);
  if ((needs.labels||[]).length) pills.push([`${t("needs")}: ${needs.labels.join(",")}`]);
  if ((inter.conflicts||[]).length) pills.push([`${t("conflicts")}: ${inter.conflicts.length}`, "warn"]);
  if (data.notice) pills.push([`${t("notice")}: ${data.notice}`, "warn"]);
  resultMeta.innerHTML = pills.filter(([t]) => t && !t.endsWith(": ")).map(([text, tone]) => `<span class="meta-pill ${tone||""}">${escapeHtml(text)}</span>`).join("");
}

function renderResult(data) {
  const result = data.result || {}; const perf = data.performance || {};
  currentResult = result; currentResult._perf = perf; currentResult._interaction = data.interaction || {}; currentResult._notice = data.notice;
  currentResult._clarificationOptions = data.clarification_options || data.interaction?.clarification_options || [];
  currentVariants = result.variants || [];
  if (activeVariantIndex >= currentVariants.length) activeVariantIndex = 0;

  resultTitle.textContent = t("routeReady");
  if (resultDesc) resultDesc.textContent = currentVariants[activeVariantIndex]?.description || "";
  if (resultStatus) { resultStatus.hidden = false; resultStatus.textContent = t("statusReady"); }

  renderMeta(data, result);
  renderTabs(currentVariants);
  const clarificationActions = renderClarificationActions(currentResult._clarificationOptions);
  variantPanels.innerHTML = currentVariants.length
    ? currentVariants.map((v, i) => renderVariantPanel(v, i)).join("")
    : `<div class="empty-card"><p>${escapeHtml(data.notice || t("noResult"))}</p>${clarificationActions}</div>`;

  if (currentVariants.length > activeVariantIndex) renderWhy(currentVariants[activeVariantIndex]);

  loadMs.textContent = perf.load_ms || "-"; planMs.textContent = perf.plan_ms || "-"; totalMs.textContent = perf.total_ms || "-";
  emptyFixes.hidden = currentVariants.length > 0;
  [copyRouteButton, copyPoiButton, exportButton].forEach(b => { if (b) b.disabled = currentVariants.length === 0; });

  if (currentVariants.length > 0) { setTimeout(() => { renderMap(currentVariants[activeVariantIndex]); if (map) map.invalidateSize(); }, 80); }
  bindEvents();
}

function bindEvents() {
  document.querySelectorAll(".variant-card").forEach(btn => {
    btn.addEventListener("click", () => {
      activeVariantIndex = Number(btn.dataset.variant);
      renderResult({ result: currentResult, performance: currentResult._perf || {}, interaction: currentResult._interaction || {}, notice: currentResult._notice });
    });
  });
  document.querySelectorAll("[data-action]").forEach(btn => {
    btn.addEventListener("click", () => handleStepAction(btn.dataset.action, btn.dataset.id));
  });
}

function findPoi(id) { for (const v of currentVariants) { const items = [...(v.route||[]), ...(v.recommendations||[])]; const f = items.find(x => String(x.poi_id||x.name)===String(id)); if (f) return f; } return null; }
async function copyText(text, ok) { try { await navigator.clipboard.writeText(text); } catch(e) { const a=document.createElement("textarea");a.value=text;a.style.position="fixed";a.style.opacity="0";document.body.appendChild(a);a.select();document.execCommand("copy");a.remove(); } showToast(ok); }
function routeShareText(v = currentVariants[activeVariantIndex]) {
  if (!v) return "";
  const s = variantStats(v);
  const lines = [
    `RouteMind - ${variantName(v)}`,
    s.isRoute ? `${t("totalTime")}: ${formatTime(s.total)} | ${t("moveTime")}: ${formatDistance(s.distance)} / ${formatTime(s.move)}` : `${t("poiCount")}: ${s.poi}`,
  ];
  const items = (v.route||[]).length ? v.route : (v.recommendations||[]);
  items.forEach((it, i) => {
    const timeOrReason = it.arrival_time
      ? `${it.arrival_time}-${it.departure_time}`
      : (reasonItems(it, v)[0] || qualityText(it) || "");
    lines.push(`${i+1}. ${it.name} [${it.type||"-"}] ${timeOrReason}`.trim());
  });
  return lines.join("\n");
}
function poiListText(v = currentVariants[activeVariantIndex]) { if (!v) return ""; const items = (v.route||[]).length ? v.route : (v.recommendations||[]); return items.map((it, i) => `${i+1}. ${it.name}`).join("\n"); }
function handleStepAction(action, id) {
  const p = findPoi(id);
  if (!p) return;
  if (action === "copy-stop") {
    copyText(p.name, t("copiedName"));
    return;
  }
  if (action === "focus-stop") {
    const loc = p.location;
    if (map && loc) {
      if (isMobileViewport()) setMobileView("map");
      setTimeout(() => {
        map.setView([loc.lat, loc.lng], 17);
        showToast(t("locateStop"));
      }, 90);
    }
    return;
  }
  if (action === "replace-stop") {
    showToast(t("replaceTodo"));
    return;
  }
  if (action === "skip-stop") {
    showToast(t("skipTodo"));
  }
}

function focusPoiOnMap(id) {
  const p = findPoi(id);
  const loc = p?.location;
  if (!p || !loc || !map) return;
  if (isMobileViewport()) setMobileView("map");
  setTimeout(() => {
    map.setView([loc.lat, loc.lng], 17);
    const marker = poiLayers.find(layer => {
      const ll = layer.getLatLng?.();
      return ll && Math.abs(ll.lat - loc.lat) < 0.000001 && Math.abs(ll.lng - loc.lng) < 0.000001;
    });
    marker?.openPopup?.();
  }, 90);
}

// ---------- Planner ----------
function parseDialogue(text) { const lines = text.split(/\n+/).map(l=>l.trim()).filter(Boolean); const msgs=[]; lines.forEach(line=>{const m=line.match(/^([^:：]{1,16})[:：]\s*(.+)$/);if(m)msgs.push({speaker_id:m[1].trim(),text:m[2].trim()});});return msgs.length>=2?msgs:null;}
function startProgress() { const steps = Array.from(planningProgress.querySelectorAll("span")); planningProgress.hidden = false; steps.forEach(s=>s.classList.remove("active","done")); let idx=0; steps[0]?.classList.add("active"); clearInterval(progressTimer); progressTimer = setInterval(()=>{steps.forEach((s,i)=>{s.classList.toggle("done",i<idx);s.classList.toggle("active",i===idx);});idx=Math.min(idx+1,steps.length-1);},650);}
function stopProgress(done=false) { clearInterval(progressTimer); const steps = Array.from(planningProgress.querySelectorAll("span")); steps.forEach(s=>{s.classList.toggle("done",done);s.classList.remove("active");});setTimeout(()=>planningProgress.hidden=true,done?500:0);}

async function runPlanner() {
  const goal = goalInput.value.trim();
  if (!goal) { setStatus(t("emptyGoal")); document.querySelectorAll("#promptChips button").forEach(b=>{b.classList.add("suggested");setTimeout(()=>b.classList.remove("suggested"),1600);});return; }
  sessionStorage.setItem("routemind_last_goal", goal);
  const payload = { goal, radius: Number(radiusSelect.value), user_mode: currentMode, session_id: sessionInput.value.trim() || "default-session", user_id: userInput.value.trim() || undefined };
  const dialogue = parseDialogue(goal); if (dialogue) payload.dialogue = dialogue;
  if (currentLocation) { payload.center_lat = currentLocation.lat; payload.center_lng = currentLocation.lng; }
  else { const c = CENTER_MAP[centerSelect.value] || CENTER_MAP.chunxi; payload.center_lat = c.lat; payload.center_lng = c.lng; payload.city = centerSelect.value; }

  runButton.disabled = true;
  const btnText = document.getElementById("btnText");
  if (btnText) btnText.textContent = currentLang === "zh" ? "规划中…" : "Planning…";
  [copyRouteButton, copyPoiButton, exportButton].forEach(b=>{if(b)b.disabled=true;});
  setStatus(t("planning")); startProgress();
  try {
    const resp = await fetch("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      const error = new Error(data.error || "Request failed");
      error.code = data.error_code;
      error.service_area = data.service_area;
      throw error;
    }
    activeVariantIndex = 0; renderResult(data); setStatus(t("done")); stopProgress(true);
    if (isMobileViewport()) setMobileView("result");
    if (btnText) btnText.textContent = t("planButton");
  } catch (err) { setStatus(`Error: ${err.message}`); if (btnText) btnText.textContent = t("planButton"); showRequestError(err); stopProgress(false); console.error(err); }
  finally { runButton.disabled = false; }
}

function showRequestError(err) {
  const serviceHelp = (err?.code || err?.error_code) === "UNSUPPORTED_SERVICE_AREA"
    ? `<div class="quick-error-actions"><button data-goal="春熙路附近想吃火锅">春熙路火锅</button><button data-goal="太古里附近逛街喝咖啡">太古里咖啡</button><button data-goal="九眼桥晚上喝酒，顺便找点夜宵">九眼桥夜游</button></div>`
    : "";
  variantPanels.innerHTML = `<div class="empty-card"><p>${escapeHtml(err.message || t("noResult"))}</p>${serviceHelp}</div>`;
  emptyFixes.hidden = false;
  if (isMobileViewport()) setMobileView("result");
}

// ---------- Location ----------
function useMyLocation() { if (!navigator.geolocation) { showToast(t("noGeo")); return; } locateButton.disabled = true; setStatus(t("locating")); navigator.geolocation.getCurrentPosition(pos=>{currentLocation={lat:Number(pos.coords.latitude.toFixed(6)),lng:Number(pos.coords.longitude.toFixed(6))};locateButton.disabled=false;mapCaption.textContent=`${t("currentLocation")} ${Number(radiusSelect.value)/1000}km`;setStatus(t("idle"));showToast(t("currentLocation"));},err=>{locateButton.disabled=false;setStatus(t("locationFailed"));showToast(t("locationFailed"));},{enableHighAccuracy:true,timeout:10000}); }
function applyFix(kind) { if (kind === "radius") { radiusSelect.value = "5000"; mapCaption.textContent = `${getCenterLabel()} 5km`; showToast(t("fixRadius")); } if (kind === "mode") { const modes = ["tourist","business","resident"]; applyMode(modes[(modes.indexOf(currentMode)+1)%modes.length]); showToast(t("fixMode")); } if (kind === "time") { goalInput.value = `${goalInput.value.trim()}，时间可以放宽`; showToast(t("fixTime")); } }

// ---------- Event Bindings ----------
centerSelect?.addEventListener("change", () => { currentLocation = null; mapCaption.textContent = `${getCenterLabel()} ${Number(radiusSelect.value)/1000}km`; });
radiusSelect?.addEventListener("change", () => { mapCaption.textContent = `${getCenterLabel()} ${Number(radiusSelect.value)/1000}km`; });
document.querySelectorAll("[data-lang]").forEach(b => b.addEventListener("click", () => applyLanguage(b.dataset.lang)));
document.querySelectorAll("[data-skin]").forEach(b => b.addEventListener("click", () => applySkin(b.dataset.skin)));
document.querySelectorAll("[data-mode]").forEach(b => b.addEventListener("click", () => applyMode(b.dataset.mode)));
document.querySelectorAll("#promptChips button").forEach(b => b.addEventListener("click", () => { goalInput.value = b.dataset.goal; document.querySelectorAll("#promptChips button").forEach(x=>x.classList.remove("suggested")); b.classList.add("suggested"); if (isMobileViewport()) setMobileView("plan"); goalInput.focus(); }));
clearGoalButton?.addEventListener("click", () => { goalInput.value = ""; goalInput.focus(); });
runButton?.addEventListener("click", runPlanner);
locateButton?.addEventListener("click", useMyLocation);
diffOnlyToggle?.addEventListener("change", () => { if (currentResult) renderResult({ result: currentResult, performance: currentResult._perf||{}, interaction: currentResult._interaction||{}, notice: currentResult._notice }); });
copyRouteButton?.addEventListener("click", () => copyText(routeShareText(), t("routeCopied")));
copyPoiButton?.addEventListener("click", () => copyText(poiListText(), t("poiCopied")));
exportButton?.addEventListener("click", () => showToast(t("exportTodo")));
document.getElementById("zoomInButton")?.addEventListener("click", () => map?.zoomIn());
document.getElementById("zoomOutButton")?.addEventListener("click", () => map?.zoomOut());
document.getElementById("recenterButton")?.addEventListener("click", () => { if (map && currentBounds) map.fitBounds(currentBounds, { padding: [42,42], maxZoom: 16 }); });
document.getElementById("startFocusButton")?.addEventListener("click", () => { const v = currentVariants[activeVariantIndex]; const s = v?.start_location || CENTER_MAP.chunxi; if (map && s) map.setView([s.lat, s.lng], 16); });
emptyFixes?.addEventListener("click", e => { const b = e.target.closest("[data-fix]"); if (b) applyFix(b.dataset.fix); });
variantPanels?.addEventListener("click", e => {
  const b = e.target.closest("[data-goal]");
  if (b) {
    goalInput.value = b.dataset.goal;
    setMobileView("plan");
    goalInput.focus();
    return;
  }
  if (e.target.closest(".step-actions")) return;
  const stop = e.target.closest(".stop[data-poi-id]");
  if (stop) focusPoiOnMap(stop.dataset.poiId);
});
document.getElementById("clearSessionButton")?.addEventListener("click", async () => { try { await fetch("/api/session/clear", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionInput.value.trim() || "default-session" }) }); setStatus(t("clearedSession")); showToast(t("clearedSession")); } catch(e) {} });
document.getElementById("clearProfileButton")?.addEventListener("click", async () => { const uid = userInput.value.trim(); if (!uid) { setStatus(t("needUser")); return; } try { const r = await fetch("/api/profile/clear", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: uid }) }); const d = await r.json(); if (!r.ok || !d.ok) throw new Error(d.error || "Clear failed"); const m = d.cleared ? t("clearedProfile") : t("noProfile"); setStatus(m); showToast(m); } catch(e) { setStatus(`Error: ${e.message}`); } });
serviceAcceptButton?.addEventListener("click", closeServiceNotice);
serviceModal?.addEventListener("click", e => { if (e.target === serviceModal) closeServiceNotice(); });
document.querySelectorAll("[data-mobile-view]").forEach(btn => btn.addEventListener("click", () => setMobileView(btn.dataset.mobileView)));
window.addEventListener("resize", () => {
  if (!isMobileViewport() && map) setTimeout(() => map.invalidateSize(), 80);
});

// ---------- Init ----------
applyLanguage(currentLang);
applySkin(currentSkin);
applyMode(currentMode);
if (mapCaption) mapCaption.textContent = `${getCenterLabel()} 3km`;
[copyRouteButton, copyPoiButton, exportButton].forEach(b => { if (b) b.disabled = true; });
setStatus(t("idle"));
showServiceNoticeIfNeeded();
setMobileView(currentMobileView);

// Animate prompt chips on load
setTimeout(() => {
  document.querySelectorAll(".prompt-row button").forEach((btn, i) => {
    btn.style.opacity = "0";
    btn.style.transform = "translateY(6px)";
    btn.style.transition = "opacity .3s ease, transform .3s ease";
    setTimeout(() => { btn.style.opacity = "1"; btn.style.transform = "translateY(0)"; }, i * 80 + 400);
  });
}, 100);
