/* Emvoox landing page: theme, language, navigation, reveal, tabs, voice auditions and the contact form.
   No dependencies. The page reads fully without this script (English, light or system theme). */
(function () {
  "use strict";
  var doc = document.documentElement;

  function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } }

  /* ── Theme ── */
  var themeBtn = document.getElementById("theme-btn");
  if (themeBtn) themeBtn.addEventListener("click", function () {
    var next = doc.getAttribute("data-theme") === "dark" ? "light" : "dark";
    doc.setAttribute("data-theme", next);
    store("emvoox-theme", next);
  });

  /* ── Language ──
     English lives in the HTML. Vietnamese and Chinese come from window.EMVOOX_VI (i18n.js) and window.EMVOOX_ZH
     (i18n-zh.js), keyed by data-i18n. The English markup is remembered on first switch, so English needs no dictionary. */
  var DICTS = { vi: window.EMVOOX_VI || {}, zh: window.EMVOOX_ZH || {} };
  var LANGS = ["en", "vi", "zh"];
  var HTML_LANG = { en: "en", vi: "vi", zh: "zh-Hans" };
  var SITE = "https://emvoox.com/";
  var original = new Map();
  var langListeners = [];

  function lang() { var l = doc.getAttribute("data-lang"); return LANGS.indexOf(l) >= 0 ? l : "en"; }
  function t(key, en) { var d = DICTS[lang()]; return d && d[key] != null ? d[key] : en; }

  /* Chinese glyphs are not in Be Vietnam Pro / Noto Serif: load the SC faces only when Chinese is chosen. */
  function loadChineseFonts() {
    if (document.getElementById("font-zh")) return;
    var link = document.createElement("link");
    link.id = "font-zh";
    link.rel = "stylesheet";
    link.href = "https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600;700&family=Noto+Serif+SC:wght@600;700&display=swap";
    document.head.appendChild(link);
  }

  function applyLang(l) {
    var dict = DICTS[l];
    function pick(key, en) { return dict && dict[key] != null ? dict[key] : en; }
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      if (!original.has(el)) original.set(el, el.innerHTML);
      el.innerHTML = pick(el.getAttribute("data-i18n"), original.get(el));
    });
    [["data-i18n-ph", "placeholder", "phEn"], ["data-i18n-aria", "aria-label", "ariaEn"], ["data-i18n-content", "content", "contentEn"]].forEach(function (spec) {
      document.querySelectorAll("[" + spec[0] + "]").forEach(function (el) {
        if (el.dataset[spec[2]] == null) el.dataset[spec[2]] = el.getAttribute(spec[1]) || "";
        el.setAttribute(spec[1], pick(el.getAttribute(spec[0]), el.dataset[spec[2]]));
      });
    });
    doc.setAttribute("lang", HTML_LANG[l]);
    doc.setAttribute("data-lang", l);
    if (l === "zh") loadChineseFonts();
    var canonical = document.querySelector('link[rel="canonical"]');
    if (canonical) canonical.setAttribute("href", l === "en" ? SITE : SITE + "?lang=" + l);
    document.querySelectorAll(".lang button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-lang") === l));
    });
    langListeners.forEach(function (fn) { fn(l); });
  }

  document.querySelectorAll(".lang button").forEach(function (b) {
    b.addEventListener("click", function () {
      var l = b.getAttribute("data-lang");
      applyLang(l);
      store("emvoox-lang", l);
    });
  });

  /* ── Navigation: shadow on scroll, mobile menu, active section ── */
  var nav = document.querySelector(".nav");
  var links = document.getElementById("nav-links");
  var menuBtn = document.getElementById("menu-btn");
  function onScroll() { if (nav) nav.classList.toggle("scrolled", window.scrollY > 8); }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  function closeMenu() {
    if (!links) return;
    links.classList.remove("open");
    if (menuBtn) menuBtn.setAttribute("aria-expanded", "false");
  }
  if (menuBtn && links) {
    menuBtn.addEventListener("click", function () {
      var open = links.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", String(open));
    });
    links.addEventListener("click", function (e) { if (e.target.closest("a")) closeMenu(); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenu(); });
  }

  var navAnchors = links ? Array.prototype.slice.call(links.querySelectorAll('a[href^="#"]')) : [];
  if ("IntersectionObserver" in window && navAnchors.length) {
    var byId = {};
    navAnchors.forEach(function (a) { byId[a.getAttribute("href").slice(1)] = a; });
    var spy = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        navAnchors.forEach(function (a) { a.classList.remove("active"); });
        var a = byId[en.target.id];
        if (a) a.classList.add("active");
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    Object.keys(byId).forEach(function (id) { var s = document.getElementById(id); if (s) spy.observe(s); });
  }

  /* ── Reveal on scroll ── */
  var revealEls = document.querySelectorAll("[data-reveal]");
  var reduce = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!("IntersectionObserver" in window) || reduce) {
    revealEls.forEach(function (el) { el.classList.add("in"); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    revealEls.forEach(function (el) { io.observe(el); });
  }

  /* ── Hero waveform (decorative, deterministic) ── */
  var wave = document.getElementById("hero-wave");
  if (wave) {
    var bars = 64, played = 41, seed = 7, html = "";
    for (var i = 0; i < bars; i++) {
      seed = (seed * 9301 + 49297) % 233280;
      var envelope = 0.35 + 0.65 * Math.abs(Math.sin(i / 6.5));
      var h = Math.round(18 + (seed / 233280) * 82 * envelope);
      html += '<i class="' + (i < played ? "on" : "") + '" style="height:' + Math.min(h, 100) + '%;animation-delay:' + (i % 8) * 0.12 + 's"></i>';
    }
    wave.innerHTML = html;
  }

  /* ── Floating pill navigation: one thumb glides to the selected item (product tabs, agent groups) ── */
  function placeThumb(nav) {
    var thumb = nav && nav.querySelector(".pillnav-thumb");
    var item = nav && nav.querySelector('.pillnav-item[aria-selected="true"], .pillnav-item[aria-pressed="true"]');
    if (!thumb || !item || !nav.offsetWidth) return;
    nav.style.setProperty("--x", item.offsetLeft + "px");
    nav.style.setProperty("--w", item.offsetWidth + "px");
    if (nav.scrollWidth > nav.clientWidth) {
      var left = item.offsetLeft - (nav.clientWidth - item.offsetWidth) / 2;
      if (nav.classList.contains("ready") && nav.scrollTo) nav.scrollTo({ left: left, behavior: "smooth" }); else nav.scrollLeft = left;
    }
    if (!nav.classList.contains("ready")) requestAnimationFrame(function () { nav.classList.add("ready"); });
  }
  function placeAllThumbs() { document.querySelectorAll(".pillnav").forEach(placeThumb); }
  window.addEventListener("resize", placeAllThumbs);
  langListeners.push(function () { requestAnimationFrame(placeAllThumbs); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(placeAllThumbs);

  /* ── Product tabs (WAI-ARIA tabs pattern) ── */
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[role="tab"]'));
  function selectTab(tab, focus) {
    tabs.forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on ? 0 : -1;
      var panel = document.getElementById(t.getAttribute("aria-controls"));
      if (panel) panel.hidden = !on;
    });
    if (focus) tab.focus();
    placeThumb(tab.parentNode);
  }
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { selectTab(t); });
    t.addEventListener("keydown", function (e) {
      var j = null;
      if (e.key === "ArrowRight") j = (i + 1) % tabs.length;
      if (e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
      if (e.key === "Home") j = 0;
      if (e.key === "End") j = tabs.length - 1;
      if (j !== null) { e.preventDefault(); selectTab(tabs[j], true); }
    });
  });
  document.querySelectorAll("[data-tab]").forEach(function (a) {
    a.addEventListener("click", function () {
      var t = document.getElementById(a.getAttribute("data-tab"));
      if (t) selectTab(t);
    });
  });

  /* ── Agent crew: the pill list opens one agent; the stage on the right shows it ──
     Below 860px the stage moves inside the open pill, so it stays next to what was tapped. */
  var crew = document.querySelector(".crew");
  if (crew) {
    var cps = Array.prototype.slice.call(crew.querySelectorAll(".cp"));
    var slides = {};
    crew.querySelectorAll(".slide").forEach(function (sl) { slides[sl.getAttribute("data-agent")] = sl; });
    var rail = crew.querySelector(".rail");
    var seg = crew.querySelector(".crew-seg");
    var stepBtns = Array.prototype.slice.call(crew.querySelectorAll(".step-btn"));
    var tabMode = window.matchMedia("(max-width: 1060px)");
    var currentAgent = null;

    var visibleAgents = function () { return cps.filter(function (li) { return !li.parentNode.hidden; }); };
    /* Below desktop the pills are a sideways row of tabs: keep the chosen one in view without moving the page. */
    var revealTab = function (li, smooth) {
      if (!tabMode.matches) return;
      var row = li.parentNode;
      var left = li.offsetLeft - (row.clientWidth - li.offsetWidth) / 2;
      if (row.scrollTo) row.scrollTo({ left: left, behavior: smooth && !reduce ? "smooth" : "auto" }); else row.scrollLeft = left;
    };
    var renderRail = function () {
      var vis = visibleAgents(), at = vis.indexOf(currentAgent);
      rail.innerHTML = "";
      vis.forEach(function (li, i) {
        var b = document.createElement("button");
        b.type = "button";
        b.tabIndex = -1;
        b.className = "rd" + (i === at ? " on" : i < at ? " done" : "");
        b.innerHTML = "<i></i>" + li.getAttribute("data-k");
        b.addEventListener("click", function () { selectAgent(li); });
        rail.appendChild(b);
      });
    };
    var selectAgent = function (li, focus) {
      currentAgent = li;
      cps.forEach(function (x) {
        var on = x === li;
        x.classList.toggle("on", on);
        x.querySelector(".cp-btn").setAttribute("aria-expanded", String(on));
      });
      var id = li.getAttribute("data-agent");
      Object.keys(slides).forEach(function (k) {
        var on = k === id;
        slides[k].classList.toggle("on", on);
        if (on) slides[k].removeAttribute("aria-hidden"); else slides[k].setAttribute("aria-hidden", "true");
      });
      var vis = visibleAgents(), i = vis.indexOf(li);
      if (stepBtns.length) { stepBtns[0].disabled = i <= 0; stepBtns[1].disabled = i >= vis.length - 1; }
      renderRail();
      revealTab(li, true);
      if (focus) li.querySelector(".cp-btn").focus({ preventScroll: true });
    };
    var stepAgent = function (by, focus) {
      var vis = visibleAgents(), i = vis.indexOf(currentAgent) + by;
      if (i >= 0 && i < vis.length) selectAgent(vis[i], focus);
    };

    cps.forEach(function (li) {
      var btn = li.querySelector(".cp-btn");
      btn.addEventListener("click", function () { if (li !== currentAgent) selectAgent(li); });
      btn.addEventListener("keydown", function (e) {
        var vis = visibleAgents();
        if (e.key === "ArrowDown" || e.key === "ArrowRight") { e.preventDefault(); stepAgent(1, true); }
        if (e.key === "ArrowUp" || e.key === "ArrowLeft") { e.preventDefault(); stepAgent(-1, true); }
        if (e.key === "Home") { e.preventDefault(); selectAgent(vis[0], true); }
        if (e.key === "End") { e.preventDefault(); selectAgent(vis[vis.length - 1], true); }
      });
    });
    stepBtns.forEach(function (b) {
      b.addEventListener("click", function () { stepAgent(Number(b.getAttribute("data-step"))); });
    });
    if (seg) seg.querySelectorAll("[data-crew]").forEach(function (b) {
      b.addEventListener("click", function () {
        var group = b.getAttribute("data-crew");
        seg.querySelectorAll("[data-crew]").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); });
        crew.querySelectorAll(".crew-list").forEach(function (ul) { ul.hidden = ul.getAttribute("data-group") !== group; });
        placeThumb(seg);
        selectAgent(visibleAgents()[0]);
      });
    });
    var onModeChange = function () { if (currentAgent) revealTab(currentAgent, false); };
    if (tabMode.addEventListener) tabMode.addEventListener("change", onModeChange); else if (tabMode.addListener) tabMode.addListener(onModeChange);
    selectAgent(crew.querySelector(".cp.on") || cps[0]);
  }

  /* ── Who it's for: orbit gallery. One continuous position drives every card, frame by frame: each card sits on the
     curve by its distance from that position, the navy face fades in as a card reaches the front, and cards wrap
     round out of sight. ‹ › and the dots glide there; a drag moves the gallery under the pointer and settles on
     release. Only the front card is reachable by keyboard and screen readers. ── */
  var ogal = document.querySelector(".ogal");
  if (ogal) {
    var ogStage = ogal.querySelector(".ogal-stage");
    var ogCards = Array.prototype.slice.call(ogal.querySelectorAll(".og-card"));
    var ogDots = ogal.querySelector(".ogal-dots");
    var ogCount = ogal.querySelector(".ogal-count");
    var ogN = ogCards.length, ogPos = 0, ogFront = -1, ogSpread = 300, ogTween = null;
    var pad2 = function (n) { return (n < 10 ? "0" : "") + n; };
    var wrapIdx = function (i) { return ((Math.round(i) % ogN) + ogN) % ogN; };
    ogCards.forEach(function (c, i) {
      var d = document.createElement("button");
      d.type = "button";
      d.className = "og-dot";
      d.tabIndex = -1;
      d.addEventListener("click", function () { ogGo(ogPos + shortest(i - wrapIdx(ogPos))); });
      ogDots.appendChild(d);
    });
    var shortest = function (d) { d = ((d % ogN) + ogN) % ogN; return d > ogN / 2 ? d - ogN : d; };
    var ogFit = function () {
      var h = 0;
      ogCards.forEach(function (c) { c.style.height = ""; h = Math.max(h, c.offsetHeight); });
      ogCards.forEach(function (c) { c.style.height = h + "px"; });
      ogStage.style.height = (h + 8) + "px";
      ogSpread = Math.min(ogStage.clientWidth * 0.32, ogCards[0].offsetWidth * 0.72);
    };
    var ogRender = function () {
      ogCards.forEach(function (c, i) {
        var o = i - ogPos;
        o = ((o % ogN) + ogN) % ogN;
        if (o > ogN / 2) o -= ogN;
        var a = Math.abs(o), sign = o < 0 ? -1 : 1;
        var x = sign * (ogSpread * Math.min(a, 1) + ogSpread * 0.55 * Math.max(a - 1, 0));
        c.style.transform = "translateX(calc(-50% + " + x.toFixed(2) + "px)) translateZ(" + (-a * 170).toFixed(1) +
          "px) rotateY(" + (-sign * Math.min(a * 24, 40)).toFixed(2) + "deg) scale(" + (1 - Math.min(a, 2) * 0.05).toFixed(4) + ")";
        c.style.opacity = String(a <= 1 ? 1 : a <= 2 ? 1 - (a - 1) * 0.5 : Math.max(0, 0.5 - (a - 2) * 1.2));
        c.style.zIndex = String(100 - Math.round(a * 10));
        c.style.setProperty("--f", Math.max(0, 1 - a).toFixed(3));
        c.style.pointerEvents = a > 2.2 ? "none" : "";
      });
      var front = wrapIdx(ogPos);
      if (front === ogFront) return;
      ogFront = front;
      ogCards.forEach(function (c, i) {
        var on = i === front;
        c.classList.toggle("on", on);
        c.setAttribute("aria-label", (i + 1) + " / " + ogN);
        if (on) c.removeAttribute("aria-hidden"); else c.setAttribute("aria-hidden", "true");
        c.querySelectorAll("a, button").forEach(function (el) { if (on) el.removeAttribute("tabindex"); else el.setAttribute("tabindex", "-1"); });
      });
      Array.prototype.forEach.call(ogDots.children, function (d, i) { d.classList.toggle("on", i === front); });
      ogCount.textContent = pad2(front + 1) + " / " + pad2(ogN);
    };
    /* Glide: ease-out-cubic from wherever the gallery is now, so quick repeated presses chain without a jolt. */
    var ogGo = function (target) {
      if (ogTween) cancelAnimationFrame(ogTween.raf);
      target = Math.round(target);
      ogTarget = target;
      if (reduce) { ogPos = target; ogRender(); return; }
      var from = ogPos, dist = target - from, t0 = performance.now(), dur = 520 + Math.min(Math.abs(dist), 3) * 120;
      ogTween = { raf: 0 };
      var step = function (now) {
        var p = Math.min((now - t0) / dur, 1);
        ogPos = from + dist * (1 - Math.pow(1 - p, 3));
        ogRender();
        if (p < 1) ogTween.raf = requestAnimationFrame(step); else ogTween = null;
      };
      ogTween.raf = requestAnimationFrame(step);
    };
    var ogTarget = 0;
    var ogStep = function (by) { ogTarget = (ogTween ? ogTarget : Math.round(ogPos)) + by; ogGo(ogTarget); };
    ogal.querySelector(".ogal-btn.prev").addEventListener("click", function () { ogStep(-1); });
    ogal.querySelector(".ogal-btn.next").addEventListener("click", function () { ogStep(1); });
    ogal.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { e.preventDefault(); ogStep(-1); }
      if (e.key === "ArrowRight") { e.preventDefault(); ogStep(1); }
    });
    /* Drag / swipe: the gallery follows the pointer; on release it settles on the nearest card, nudged one card
       along when the drag was a quick flick. A click on a side card brings it to the front. */
    var ogDrag = null, ogDragged = false;
    ogStage.addEventListener("pointerdown", function (e) {
      if (e.button !== 0) return;
      if (ogTween) { cancelAnimationFrame(ogTween.raf); ogTween = null; }
      ogDrag = { x: e.clientX, y: e.clientY, pos: ogPos, t: performance.now(), lastX: e.clientX, lastT: performance.now(), v: 0, live: false, id: e.pointerId };
      ogDragged = false;
    });
    ogStage.addEventListener("pointermove", function (e) {
      if (!ogDrag || e.pointerId !== ogDrag.id) return;
      var dx = e.clientX - ogDrag.x, dy = e.clientY - ogDrag.y;
      if (!ogDrag.live) {
        if (Math.abs(dx) < 6 || Math.abs(dx) < Math.abs(dy)) return;
        ogDrag.live = true;
        ogDragged = true;
        try { ogStage.setPointerCapture(e.pointerId); } catch (err) { /* old browsers */ }
        ogStage.classList.add("dragging");
      }
      var now = performance.now();
      ogDrag.v = (e.clientX - ogDrag.lastX) / Math.max(1, now - ogDrag.lastT);
      ogDrag.lastX = e.clientX; ogDrag.lastT = now;
      ogPos = ogDrag.pos - dx / (ogSpread * 1.15);
      ogRender();
    });
    var ogRelease = function () {
      if (!ogDrag) return;
      var d = ogDrag;
      ogDrag = null;
      ogStage.classList.remove("dragging");
      if (!d.live) return;
      var target = Math.round(ogPos);
      if (Math.abs(d.v) > 0.35 && target === Math.round(d.pos)) target += d.v < 0 ? 1 : -1;
      ogGo(target);
      setTimeout(function () { ogDragged = false; }, 0);
    };
    ogStage.addEventListener("dragstart", function (e) { e.preventDefault(); });
    ogStage.addEventListener("pointerup", ogRelease);
    ogStage.addEventListener("pointercancel", ogRelease);
    ogCards.forEach(function (c, i) {
      c.addEventListener("click", function (e) {
        if (ogDragged || !c.classList.contains("on")) { e.preventDefault(); e.stopPropagation(); }
        if (!ogDragged && !c.classList.contains("on")) ogGo(ogPos + shortest(i - wrapIdx(ogPos)));
      }, true);
    });
    var ogRefit = function () { ogFit(); ogRender(); };
    ogRefit();
    window.addEventListener("resize", ogRefit);
    langListeners.push(function () { requestAnimationFrame(ogRefit); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(ogRefit);
  }

  /* ── FAQ: smooth open and close on the native <details>. The answer's height eases with no overshoot (like the
     reference's spring 500/60) while the text fades and rises; opening one question closes the others. ── */
  var faqItems = Array.prototype.slice.call(document.querySelectorAll(".faq details"));
  var FAQ_EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
  function faqToggle(d, open) {
    var box = d.querySelector(".qa-a"), text = box.querySelector("p");
    var from = d.open ? box.offsetHeight : 0;
    if (d._anim) { d._anim.onfinish = null; d._anim.cancel(); }
    if (reduce || !box.animate) { d.open = open; return; }
    if (open) d.open = true;
    var to = open ? text.offsetHeight : 0;
    d._anim = box.animate([{ height: from + "px" }, { height: to + "px" }], { duration: open ? 460 : 340, easing: FAQ_EASE });
    text.animate(open ? [{ opacity: 0, transform: "translateY(10px)" }, { opacity: 1, transform: "none" }]
                      : [{ opacity: 1 }, { opacity: 0 }], { duration: open ? 460 : 220, easing: FAQ_EASE, delay: open ? 60 : 0, fill: "backwards" });
    d._anim.onfinish = function () { d._anim = null; if (!open) d.open = false; };
  }
  faqItems.forEach(function (d) {
    d.querySelector("summary").addEventListener("click", function (e) {
      e.preventDefault();
      var opening = !d.open || !!(d._anim && d._closing);
      d._closing = !opening;
      faqToggle(d, opening);
      if (opening) faqItems.forEach(function (o) { if (o !== d && o.open) { o._closing = true; faqToggle(o, false); } });
    });
  });

  /* ── Pointer spotlight on [data-spot] surfaces ── */
  if (window.matchMedia && matchMedia("(hover: hover)").matches) {
    document.querySelectorAll("[data-spot]").forEach(function (el) {
      el.addEventListener("pointermove", function (e) {
        var r = el.getBoundingClientRect();
        el.style.setProperty("--mx", (e.clientX - r.left) + "px");
        el.style.setProperty("--my", (e.clientY - r.top) + "px");
      });
    });
  }

  /* ── Interactive pattern field: dots and plus marks that light up and grow near the cursor, under a soft glow
     that trails it. Used behind the V1RON atom (round field) and on the agent stage card (full card).
     Touch screens get a slow drift where asked; reduced motion gets the still pattern. Draws only on screen. ── */
  var canHover = window.matchMedia && matchMedia("(hover: hover)").matches;
  function patternField(host, opts) {
    var cv = document.createElement("canvas");
    cv.className = opts.className;
    cv.setAttribute("aria-hidden", "true");
    host.insertBefore(cv, host.firstChild);
    var ctx = cv.getContext && cv.getContext("2d");
    if (!ctx) return;
    var zone = opts.zone || host;
    var fW = 0, fH = 0, rgb = "", glow = 0, onScreen = false, looping = false;
    var aim = { x: 0, y: 0, on: 0 }, cur = { x: 0, y: 0, on: 0 };
    var readColor = function () {
      var dark = opts.dark || doc.getAttribute("data-theme") === "dark";
      rgb = dark ? "163,192,240" : "40,73,121";
      glow = dark ? 0.24 : 0.16;
    };
    var sizeField = function () {
      var r = cv.getBoundingClientRect(), dpr = Math.min(window.devicePixelRatio || 1, 2);
      if (!r.width) return;
      fW = r.width; fH = r.height;
      cv.width = Math.round(fW * dpr); cv.height = Math.round(fH * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (!cur.on) { cur.x = aim.x = fW / 2; cur.y = aim.y = fH / 2; }
    };
    var draw = function () {
      if (!fW) return;
      var sp = 18, cx = fW / 2, cy = fH / 2, R = Math.max(110, Math.min(fW, fH) * 0.3), base = opts.base;
      ctx.clearRect(0, 0, fW, fH);
      if (cur.on > 0.01) {
        var g = ctx.createRadialGradient(cur.x, cur.y, 0, cur.x, cur.y, R * 1.1);
        g.addColorStop(0, "rgba(" + rgb + "," + (glow * cur.on).toFixed(3) + ")");
        g.addColorStop(1, "rgba(" + rgb + ",0)");
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, fW, fH);
      }
      for (var j = 0, y = sp / 2; y < fH; j++, y += sp) {
        for (var i = 0, x = sp / 2; x < fW; i++, x += sp) {
          var fade = 1;
          if (opts.round) {
            var dc = Math.sqrt((x - cx) * (x - cx) + (y - cy) * (y - cy)) / (fW / 2);
            if (dc > 1) continue;
            fade = 1 - dc * dc;
          }
          var d = Math.sqrt((x - cur.x) * (x - cur.x) + (y - cur.y) * (y - cur.y));
          var t = Math.max(0, 1 - d / R); t = t * t * cur.on;
          ctx.fillStyle = "rgba(" + rgb + "," + ((base + 0.8 * t) * fade).toFixed(3) + ")";
          if (i % 3 === 0 && j % 3 === 0) {
            var sz = 2.5 + 3 * t;
            ctx.fillRect(x - sz, y - 0.6, sz * 2, 1.2);
            ctx.fillRect(x - 0.6, y - sz, 1.2, sz * 2);
          } else {
            ctx.beginPath();
            ctx.arc(x, y, 0.9 + 1.5 * t, 0, 6.2832);
            ctx.fill();
          }
        }
      }
      if (opts.onDraw) opts.onDraw((cur.x - cx) / (fW / 2), (cur.y - cy) / (fH / 2), cur.on);
    };
    var tick = function (now) {
      if (!canHover && opts.drift && onScreen) {
        var a = now * 0.00035;
        aim.x = fW / 2 + Math.cos(a) * fW * 0.27; aim.y = fH / 2 + Math.sin(a * 1.3) * fH * 0.22; aim.on = 0.75;
      }
      cur.x += (aim.x - cur.x) * 0.12; cur.y += (aim.y - cur.y) * 0.12; cur.on += (aim.on - cur.on) * 0.08;
      draw();
      var settled = Math.abs(aim.x - cur.x) < 0.3 && Math.abs(aim.y - cur.y) < 0.3 && Math.abs(aim.on - cur.on) < 0.004;
      if (onScreen && (!settled || (!canHover && opts.drift))) requestAnimationFrame(tick); else looping = false;
    };
    var run = function () { if (!looping && onScreen && !reduce) { looping = true; requestAnimationFrame(tick); } };
    var refit = function () { sizeField(); draw(); };
    readColor(); refit();
    if (window.ResizeObserver) new ResizeObserver(refit).observe(cv); else window.addEventListener("resize", refit);
    if (!opts.dark && window.MutationObserver) new MutationObserver(function () { readColor(); draw(); }).observe(doc, { attributes: true, attributeFilter: ["data-theme"] });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (en) { onScreen = en[0].isIntersecting; if (onScreen) { refit(); run(); } }).observe(host);
    } else { onScreen = true; }
    if (canHover) {
      zone.addEventListener("pointermove", function (e) {
        var r = cv.getBoundingClientRect();
        aim.x = e.clientX - r.left; aim.y = e.clientY - r.top; aim.on = 1;
        run();
      });
      zone.addEventListener("pointerleave", function () { aim.on = 0; run(); });
    }
  }

  /* V1RON atom: the core brightens as the cursor nears it and its highlight turns toward the cursor. */
  var orbit = document.querySelector(".orbit");
  if (orbit) patternField(orbit, {
    className: "orbit-field", zone: document.getElementById("v1ron") || orbit, round: true, drift: true, base: 0.1,
    onDraw: function (dx, dy, on) {
      var near = on * Math.max(0, 1 - Math.sqrt(dx * dx + dy * dy) / 0.9);
      orbit.style.setProperty("--near", near.toFixed(3));
      orbit.style.setProperty("--hx", (50 + 32 * Math.max(-1, Math.min(1, dx)) * on).toFixed(1) + "%");
      orbit.style.setProperty("--hy", (50 + 32 * Math.max(-1, Math.min(1, dy)) * on).toFixed(1) + "%");
    }
  });
  /* Agent stage card: always dark, so it keeps the light pattern in both themes. */
  var stageCard = document.querySelector(".crew-stage");
  if (stageCard) patternField(stageCard, { className: "stage-field", dark: true, base: 0.05 });

  /* ── Small data visuals (decorative): dot grid, bars, the Sound Engineer's waveform ── */
  document.querySelectorAll(".dots[data-dots]").forEach(function (el) {
    var n = +el.getAttribute("data-dots"), lit = +el.getAttribute("data-lit"), out = "";
    for (var i = 0; i < n; i++) out += i >= n - lit ? '<i class="lit" style="--i:' + (i - n + lit) + '"></i>' : "<i></i>";
    el.innerHTML = out;
  });
  document.querySelectorAll(".bars[data-bars]").forEach(function (el) {
    var n = +el.getAttribute("data-bars"), lit = +el.getAttribute("data-lit"), out = "";
    for (var i = 0; i < n; i++) out += '<i class="' + (i < lit ? "lit" : "") + '" style="--i:' + i + ";--h:" + (100 - i * 5) + '%"></i>';
    el.innerHTML = out;
  });
  document.querySelectorAll(".art-wave[data-bars]").forEach(function (el) {
    var n = +el.getAttribute("data-bars"), seed = 11, out = "";
    for (var i = 0; i < n; i++) {
      seed = (seed * 9301 + 49297) % 233280;
      var h = Math.round(16 + (seed / 233280) * 84 * (0.4 + 0.6 * Math.abs(Math.sin(i / 5))));
      out += '<i style="height:' + Math.min(h, 100) + "%;--i:" + i + '"></i>';
    }
    el.innerHTML = out;
  });

  /* ── Voice auditions: one shared player ── */
  var player = new Audio();
  player.preload = "none";
  var current = null;
  function stop() {
    if (current) current.classList.remove("playing");
    current = null;
  }
  player.addEventListener("ended", stop);
  player.addEventListener("error", stop);
  document.querySelectorAll(".play[data-audio]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      if (current === btn) { player.pause(); stop(); return; }
      stop();
      player.src = btn.getAttribute("data-audio");
      var p = player.play();
      current = btn;
      btn.classList.add("playing");
      if (p && p.catch) p.catch(stop);
    });
  });

  /* ── Contact form ──
     Each field is checked where it is typed: on blur, live while an error is shown, and all at once on submit.
     contact.php repeats the same rules. If the server is unreachable, the visitor gets a pre-filled email link. */
  var form = document.getElementById("contact-form");
  var status = document.getElementById("form-status");
  var interest = document.getElementById("interest");
  var ccSelect = document.getElementById("f-cc");
  var ccCustom = document.getElementById("f-cc-custom");
  var ccShow = document.getElementById("cc-show");

  document.querySelectorAll("[data-interest]").forEach(function (a) {
    a.addEventListener("click", function () { if (interest) interest.value = a.getAttribute("data-interest"); });
  });

  /* Country calling codes. Names come from Intl.DisplayNames in the page language; Vietnam stays first. */
  var COUNTRIES = [
    ["VN", "84"], ["AU", "61"], ["US", "1"], ["CA", "1"], ["GB", "44"], ["CN", "86"], ["HK", "852"], ["MO", "853"],
    ["TW", "886"], ["SG", "65"], ["MY", "60"], ["TH", "66"], ["ID", "62"], ["PH", "63"], ["KH", "855"], ["LA", "856"],
    ["MM", "95"], ["JP", "81"], ["KR", "82"], ["IN", "91"], ["AE", "971"], ["SA", "966"], ["QA", "974"], ["DE", "49"],
    ["FR", "33"], ["IT", "39"], ["ES", "34"], ["NL", "31"], ["BE", "32"], ["CH", "41"], ["AT", "43"], ["SE", "46"],
    ["NO", "47"], ["DK", "45"], ["FI", "358"], ["IE", "353"], ["PL", "48"], ["CZ", "420"], ["RU", "7"], ["UA", "380"],
    ["TR", "90"], ["IL", "972"], ["EG", "20"], ["ZA", "27"], ["NG", "234"], ["KE", "254"], ["NZ", "64"], ["BR", "55"],
    ["MX", "52"], ["AR", "54"], ["CL", "56"], ["CO", "57"], ["PE", "51"], ["BD", "880"], ["PK", "92"], ["LK", "94"]
  ];
  function flag(iso) { return String.fromCodePoint.apply(null, iso.split("").map(function (c) { return 127397 + c.charCodeAt(0); })); }
  function countryName(iso, l) {
    try { return new Intl.DisplayNames([HTML_LANG[l]], { type: "region" }).of(iso) || iso; } catch (e) { return iso; }
  }
  function buildCountryCodes(l) {
    if (!ccSelect) return;
    var keep = ccSelect.selectedOptions[0] ? ccSelect.selectedOptions[0].getAttribute("data-iso") : "VN";
    var rows = COUNTRIES.map(function (c) { return { iso: c[0], dial: "+" + c[1], name: countryName(c[0], l) }; });
    var first = rows.shift();
    rows.sort(function (a, b) { return a.name.localeCompare(b.name, HTML_LANG[l]); });
    rows.unshift(first);
    ccSelect.innerHTML = "";
    rows.forEach(function (r) {
      var o = document.createElement("option");
      o.value = r.dial;
      o.setAttribute("data-iso", r.iso);
      o.textContent = flag(r.iso) + " " + r.name + " (" + r.dial + ")";
      if (r.iso === keep) o.selected = true;
      ccSelect.appendChild(o);
    });
    var other = document.createElement("option");
    other.value = "other";
    other.setAttribute("data-iso", "OTHER");
    other.textContent = t("ct.o.cc.other", "Other (type the code)");
    if (keep === "OTHER") other.selected = true;
    ccSelect.appendChild(other);
    syncCountryCode();
  }
  function syncCountryCode() {
    if (!ccSelect) return;
    var o = ccSelect.selectedOptions[0];
    var isOther = ccSelect.value === "other";
    ccCustom.hidden = !isOther;
    ccShow.textContent = isOther ? "🌐" : flag(o.getAttribute("data-iso")) + " " + o.value;
  }
  if (ccSelect) {
    ccSelect.addEventListener("change", function () {
      syncCountryCode();
      if (ccSelect.value === "other") ccCustom.focus();
      if (fields.phone.el.closest(".field").classList.contains("invalid")) check("phone");
    });
  }

  /* Validation rules: each returns an error key suffix, or "" when the value is fine. */
  function digits(v) { return v.replace(/[\s.\-()]/g, ""); }
  var fields = {
    name: { el: document.getElementById("f-name"), rule: function (v) { v = v.trim(); return !v ? "req" : v.length < 2 ? "min" : ""; } },
    email: { el: document.getElementById("f-email"), rule: function (v) { v = v.trim(); return !v ? "req" : /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(v) ? "" : "bad"; } },
    phone: { el: document.getElementById("f-phone"), rule: function (v) {
      if (ccSelect && ccSelect.value === "other" && !/^\+?\d{1,4}$/.test(ccCustom.value.trim())) return "cc";
      v = digits(v.trim());
      return !v ? "req" : /^\d{6,14}$/.test(v) ? "" : "bad";
    } },
    message: { el: document.getElementById("f-message"), rule: function (v) { v = v.trim(); return !v ? "req" : v.length < 10 ? "min" : ""; } }
  };
  var ERR_EN = {
    "name.req": "Please enter your name.",
    "name.min": "Your name needs at least 2 characters.",
    "email.req": "Please enter your email.",
    "email.bad": "This doesn't look like an email address. Example: name@company.com",
    "phone.req": "Please enter your phone number.",
    "phone.bad": "Enter 6 to 14 digits, without the country code.",
    "phone.cc": "Enter a country code, for example +84.",
    "message.req": "Please write a message.",
    "message.min": "Please write at least 10 characters."
  };
  function showError(name, code) {
    var f = fields[name], box = f.el.closest(".field"), msg = document.getElementById("err-" + name);
    f.code = code;
    box.classList.toggle("invalid", !!code);
    f.el.setAttribute("aria-invalid", code ? "true" : "false");
    if (name === "phone" && ccCustom) ccCustom.setAttribute("aria-invalid", code === "cc" ? "true" : "false");
    msg.textContent = code ? t("ct.e." + name + "." + code, ERR_EN[name + "." + code]) : "";
  }
  function check(name) { var code = fields[name].rule(fields[name].el.value); showError(name, code); return !code; }

  /* Pressing Send blurs the field first. If that blur showed or cleared an error, the button would move before the
     mouse is released and the click would be lost, so blur checks wait while Send is pressed (submit checks everything). */
  var pressingSend = false;
  var sendBtn = form ? form.querySelector('button[type="submit"]') : null;
  if (sendBtn) sendBtn.addEventListener("pointerdown", function () { pressingSend = true; });
  document.addEventListener("pointerup", function () { setTimeout(function () { pressingSend = false; }, 0); });

  Object.keys(fields).forEach(function (name) {
    var f = fields[name];
    if (!f.el) return;
    f.el.addEventListener("blur", function () { if (!pressingSend && (f.el.value.trim() || f.code)) check(name); });
    f.el.addEventListener("input", function () { if (f.code) check(name); });
  });
  if (ccCustom) ccCustom.addEventListener("input", function () { if (fields.phone.code) check("phone"); });

  /* Re-render options and any visible error in the new language. */
  langListeners.push(function (l) {
    buildCountryCodes(l);
    Object.keys(fields).forEach(function (name) { if (fields[name].code) showError(name, fields[name].code); });
  });

  function phoneNumber() {
    var code = ccSelect && ccSelect.value === "other" ? ccCustom.value.trim() : (ccSelect ? ccSelect.value : "");
    if (code && code.charAt(0) !== "+") code = "+" + code;
    return (code ? code + " " : "") + fields.phone.el.value.trim();
  }

  if (form) form.addEventListener("submit", function (e) {
    e.preventDefault();
    status.className = "form-status";
    status.textContent = "";
    var bad = Object.keys(fields).filter(function (name) { return !check(name); });
    if (bad.length) {
      status.textContent = t("ct.e.summary", "Please fix the highlighted fields.");
      status.classList.add("err");
      var first = fields[bad[0]];
      (bad[0] === "phone" && first.code === "cc" ? ccCustom : first.el).focus();
      return;
    }
    var btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    status.textContent = t("ct.sending", "Sending…");
    var data = new FormData(form);
    data.set("phone_cc", ccSelect && ccSelect.value === "other" ? ccCustom.value.trim() : (ccSelect ? ccSelect.value : ""));
    data.delete("phone_cc_custom");
    data.append("lang", lang());

    fetch(form.getAttribute("action"), { method: "POST", body: data, headers: { Accept: "application/json" } })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok && j && j.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) {
          var server = (res.j && res.j.fields) || {};
          var names = Object.keys(server).filter(function (n) { return fields[n]; });
          if (names.length) {
            names.forEach(function (n) { showError(n, server[n]); });
            status.textContent = t("ct.e.summary", "Please fix the highlighted fields.");
            status.classList.add("err");
            fields[names[0]].el.focus();
            return;
          }
          throw new Error((res.j && res.j.error) || "send failed");
        }
        form.reset();
        buildCountryCodes(lang());
        status.textContent = t("ct.ok", "Thank you. Your message is on its way, and we will reply by email.");
        status.classList.add("ok");
      })
      .catch(function () {
        var to = (document.getElementById("contact-email") || {}).textContent || "contact@emvoox.com";
        var body = "Name: " + data.get("name") + "\nCompany: " + (data.get("company") || "") + "\nPhone: " + phoneNumber() +
          "\nInterest: " + data.get("interest") + "\n\n" + data.get("message");
        status.innerHTML = t("ct.fallback", "We could not send the form from here. Please email us instead:") +
          ' <a href="mailto:' + to + "?subject=" + encodeURIComponent("Emvoox — " + data.get("interest")) + "&body=" + encodeURIComponent(body) + '">' + to + "</a>";
        status.classList.add("err");
      })
      .then(function () { btn.disabled = false; });
  });

  /* First render, after the form code has registered its language listener. */
  applyLang(lang());
  placeAllThumbs();

  /* ── Count-up figures (the problem section). Like Framer's StatsSection: ease-out-expo over 2 s, once, when a
     fifth of the row is on screen. Only the first number in each figure runs ("7 of 10" counts the 7), so the
     translated text around it is kept. A language switch stops the run and shows the final figures. ── */
  var counters = Array.prototype.slice.call(document.querySelectorAll(".facts .big-num"));
  var countRaf = [];
  function countParts(el) {
    var m = /\d+(?:[.,]\d+)?/.exec(el.textContent);
    if (!m) return null;
    var sep = m[0].indexOf(",") >= 0 ? "," : ".";
    return { before: el.textContent.slice(0, m.index), after: el.textContent.slice(m.index + m[0].length),
             end: parseFloat(m[0].replace(",", ".")), decimals: m[0].indexOf(sep) >= 0 ? m[0].split(sep)[1].length : 0, sep: sep };
  }
  function showCount(el, v) {
    var c = el._count;
    if (c) el.textContent = c.before + v.toFixed(c.decimals).replace(".", c.sep) + c.after;
  }
  if (counters.length && !reduce && "IntersectionObserver" in window) {
    var countState = "waiting";
    var armCounters = function () { counters.forEach(function (el) { el._count = countParts(el); showCount(el, 0); }); };
    armCounters();
    var countIo = new IntersectionObserver(function (en) {
      if (!en[0].isIntersecting) return;
      countIo.disconnect();
      countState = "running";
      var start = performance.now();
      counters.forEach(function (el) {
        var step = function (now) {
          var p = Math.min((now - start) / 2000, 1);
          showCount(el, (p === 1 ? 1 : 1 - Math.pow(2, -10 * p)) * el._count.end);
          if (p < 1) countRaf.push(requestAnimationFrame(step));
        };
        if (el._count) countRaf.push(requestAnimationFrame(step));
      });
      setTimeout(function () { countState = "done"; }, 2100);
    }, { threshold: 0.2 });
    countIo.observe(counters[0].closest(".facts"));
    langListeners.push(function () {
      countRaf.forEach(cancelAnimationFrame);
      countRaf = [];
      /* Translated figures were just rewritten by applyLang; the untranslated one gets its final value back. */
      counters.forEach(function (el) { if (!el.hasAttribute("data-i18n") && el._count) showCount(el, el._count.end); });
      if (countState === "waiting") armCounters();
      else countState = "done";
    });
  }

  var year = document.getElementById("year");
  if (year) year.textContent = String(new Date().getFullYear());
})();
