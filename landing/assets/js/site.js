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
     English lives in the HTML. Vietnamese comes from window.EMVOOX_VI (i18n.js), keyed by data-i18n.
     The English markup is remembered on first switch so switching back needs no second dictionary. */
  var VI = window.EMVOOX_VI || {};
  var original = new Map();

  function applyLang(lang) {
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      var key = el.getAttribute("data-i18n");
      if (!original.has(el)) original.set(el, el.innerHTML);
      el.innerHTML = lang === "vi" && VI[key] != null ? VI[key] : original.get(el);
    });
    document.querySelectorAll("[data-i18n-ph]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-ph");
      if (!el.dataset.phEn) el.dataset.phEn = el.getAttribute("placeholder") || "";
      el.setAttribute("placeholder", lang === "vi" && VI[key] ? VI[key] : el.dataset.phEn);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-aria");
      if (!el.dataset.ariaEn) el.dataset.ariaEn = el.getAttribute("aria-label") || "";
      el.setAttribute("aria-label", lang === "vi" && VI[key] ? VI[key] : el.dataset.ariaEn);
    });
    document.querySelectorAll("[data-i18n-content]").forEach(function (el) {
      var key = el.getAttribute("data-i18n-content");
      if (!el.dataset.contentEn) el.dataset.contentEn = el.getAttribute("content") || "";
      el.setAttribute("content", lang === "vi" && VI[key] ? VI[key] : el.dataset.contentEn);
    });
    doc.setAttribute("lang", lang === "vi" ? "vi" : "en");
    doc.setAttribute("data-lang", lang);
    document.querySelectorAll(".lang button").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-lang") === lang));
    });
  }

  document.querySelectorAll(".lang button").forEach(function (b) {
    b.addEventListener("click", function () {
      var lang = b.getAttribute("data-lang");
      applyLang(lang);
      store("emvoox-lang", lang);
    });
  });
  applyLang(doc.getAttribute("data-lang") === "vi" ? "vi" : "en");

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
     Posts to contact.php (DreamHost runs PHP). If that is unavailable, falls back to the visitor's mail app. */
  var form = document.getElementById("contact-form");
  var status = document.getElementById("form-status");
  var interest = document.getElementById("interest");
  function t(key, en) { return doc.getAttribute("data-lang") === "vi" && VI[key] ? VI[key] : en; }

  document.querySelectorAll("[data-interest]").forEach(function (a) {
    a.addEventListener("click", function () { if (interest) interest.value = a.getAttribute("data-interest"); });
  });

  if (form) form.addEventListener("submit", function (e) {
    e.preventDefault();
    status.className = "form-status";
    var data = new FormData(form);
    var email = String(data.get("email") || "").trim();
    if (!String(data.get("name") || "").trim() || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) || !String(data.get("message") || "").trim()) {
      status.textContent = t("ct.err.fields", "Please fill in your name, a valid email and a message.");
      status.classList.add("err");
      return;
    }
    var btn = form.querySelector('button[type="submit"]');
    btn.disabled = true;
    status.textContent = t("ct.sending", "Sending…");
    data.append("lang", doc.getAttribute("data-lang") || "en");

    fetch(form.getAttribute("action"), { method: "POST", body: data, headers: { Accept: "application/json" } })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok && j && j.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error((res.j && res.j.error) || "send failed");
        form.reset();
        status.textContent = t("ct.ok", "Thank you. Your message is on its way, and we will reply by email.");
        status.classList.add("ok");
      })
      .catch(function () {
        var to = (document.getElementById("contact-email") || {}).textContent || "dhp@emvoox.com";
        var body = "Name: " + data.get("name") + "\nCompany: " + (data.get("company") || "") + "\nPhone/Zalo: " + (data.get("phone") || "") +
          "\nInterest: " + data.get("interest") + "\n\n" + data.get("message");
        status.innerHTML = t("ct.fallback", "We could not send the form from here. Please email us instead:") +
          ' <a href="mailto:' + to + "?subject=" + encodeURIComponent("Emvoox — " + data.get("interest")) + "&body=" + encodeURIComponent(body) + '">' + to + "</a>";
        status.classList.add("err");
      })
      .then(function () { btn.disabled = false; });
  });

  var year = document.getElementById("year");
  if (year) year.textContent = String(new Date().getFullYear());
})();
