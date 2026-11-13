/* LeanVOA site. The text is the book's, converted by build.py; the chapters are loaded from book/<key>.json. */
(() => {
  "use strict";
  const D = window.LEANVOA;
  const GH = `https://github.com/${D.repo}`;
  const srcUrl = (file, line) => `${GH}/blob/${encodeURIComponent(D.ref)}/${file}${line ? `#L${line}` : ""}`;
  const treeUrl = (dir) => `${GH}/tree/${encodeURIComponent(D.ref)}/${dir}`;
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const strip = (h) => String(h).replace(/<[^>]+>/g, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&#x27;|&#39;/g, "'")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/\s+/g, " ").trim();
  const store = {
    get(k, d) { try { const v = localStorage.getItem("leanvoa-" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("leanvoa-" + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } },
  };
  const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"];

  const KATEX_MACROS = {
    "\\C": "\\mathbb{C}", "\\Z": "\\mathbb{Z}", "\\Q": "\\mathbb{Q}", "\\N": "\\mathbb{N}",
    "\\Vnat": "V^{\\natural}", "\\Leech": "\\Lambda", "\\End": "\\operatorname{End}", "\\Aut": "\\operatorname{Aut}",
    "\\Res": "\\operatorname{Res}", "\\wt": "\\operatorname{wt}", "\\tr": "\\operatorname{tr}",
  };
  function typeset(el) {
    if (!window.renderMathInElement || !el) return;
    renderMathInElement(el, {
      delimiters: [{ left: "\\[", right: "\\]", display: true }, { left: "\\(", right: "\\)", display: false }],
      macros: { ...KATEX_MACROS }, throwOnError: false, strict: "ignore", trust: false,
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
    });
  }

  // ---------------------------------------------------------------- data
  const chapters = new Map(D.chapters.map((c) => [c.key, c]));
  const readable = D.chapters.filter((c) => !c.is_index);
  const order = readable.map((c) => c.key);
  const indexChapter = D.chapters.find((c) => c.is_index);
  const chLabel = (c) => c.matter === "app" ? `Appendix ${c.num}` : c.num ? `Chapter ${c.num}` : "";
  const chHref = (key, id) => key === (indexChapter && indexChapter.key) ? "#/index" : `#/c/${key}${id ? "/" + encodeURIComponent(id) : ""}`;
  const stmts = D.statements.map(([ch, num, kind, title, id, text]) => ({ ch, num, kind, title, id, text, titleText: strip(title) }));
  for (const s of stmts) s.hay = `${s.kind} ${s.num} ${s.titleText} ${s.text}`.toLowerCase();
  const stmtById = new Map(stmts.map((s) => [s.ch + "/" + s.id, s]));
  // the book's index: name -> places
  const idxByName = new Map();
  const idxByFull = new Map();
  for (const [name, ch, id, label, full, file, line] of D.index) {
    const e = { name, ch, id, label, full, file, line };
    if (!idxByName.has(name)) idxByName.set(name, []);
    idxByName.get(name).push(e);
    if (full) { if (!idxByFull.has(full)) idxByFull.set(full, []); idxByFull.get(full).push(e); }
  }
  const allNames = [...idxByName.keys()].sort((a, b) => a.localeCompare(b));

  // ---------------------------------------------------------------- loading chapters
  const cache = new Map();
  function loadChapter(key) {
    if (!cache.has(key)) {
      cache.set(key, fetch(`book/${encodeURIComponent(key)}.json`).then((r) => {
        if (!r.ok) throw new Error(r.status);
        return r.json();
      }).catch((e) => { cache.delete(key); throw e; }));
    }
    return cache.get(key);
  }
  let searchText = null;
  function loadSearch() {
    if (!searchText) searchText = fetch("search.json").then((r) => r.json()).then((rows) => rows.map(([ch, sec, title, text]) => ({ ch, sec, title, text, low: text.toLowerCase() })));
    return searchText;
  }

  // ---------------------------------------------------------------- toast & copy
  let toastTimer;
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 1600);
  }
  async function copy(text, what) {
    try { await navigator.clipboard.writeText(text); toast(`Copied ${what}`); }
    catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); toast(`Copied ${what}`); } catch (e2) { toast("Copy failed"); }
      ta.remove();
    }
  }

  // ---------------------------------------------------------------- sidebar
  const chev = '<svg class="chev" viewBox="0 0 24 24" width="14" height="14"><path d="m6 9 6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
  function sbLink(c) {
    return `<li><a class="sb-link" data-route="c-${esc(c.key)}" href="${chHref(c.key)}"><span class="sb-num">${esc(c.num || "")}</span><span class="sb-title">${c.shortTitle}</span></a></li>`;
  }
  function renderSidebar() {
    const closed = store.get("closedParts", []);
    const front = D.chapters.filter((c) => c.matter === "front");
    let h = `<div class="sb-top"><a class="sb-link" data-route="home" href="#/">Overview</a>
      ${front.map((c) => `<a class="sb-link" data-route="c-${esc(c.key)}" href="${chHref(c.key)}">${c.shortTitle}</a>`).join("")}
      <a class="sb-link" data-route="index" href="#/index">Index of Lean declarations</a></div>`;
    D.parts.forEach((p, i) => {
      const app = p.title === "Appendices";
      h += `<div class="sb-part ${closed.includes(i) ? "closed" : ""}" data-part="${i}">
        <button type="button" aria-expanded="${!closed.includes(i)}"><span>${app ? "" : ROMAN[i] + ". "}${esc(p.title)}</span>${chev}</button><ul>`;
      for (const k of p.chapters) h += sbLink(chapters.get(k));
      h += "</ul></div>";
    });
    const sb = $("#sidebar");
    sb.innerHTML = h;
    typeset(sb);
    $$(".sb-part > button", sb).forEach((b) => b.addEventListener("click", () => {
      const part = b.parentElement, i = +part.dataset.part;
      part.classList.toggle("closed");
      b.setAttribute("aria-expanded", !part.classList.contains("closed"));
      const cl = new Set(store.get("closedParts", []));
      part.classList.contains("closed") ? cl.add(i) : cl.delete(i);
      store.set("closedParts", [...cl]);
    }));
  }
  function markSidebar(route) {
    $$(".sb-link").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
    const a = $(`.sb-link[data-route="${route}"]`);
    if (a) {
      const part = a.closest(".sb-part");
      if (part && part.classList.contains("closed")) part.classList.remove("closed");
      const sb = $("#sidebar"), r = a.getBoundingClientRect(), sr = sb.getBoundingClientRect();
      if (r.top < sr.top || r.bottom > sr.bottom) a.scrollIntoView({ block: "center" });
    }
  }

  const footer = () => `<footer class="foot">
      <span>The text of <em>Vertex Operator Algebras in Lean</em>, ${esc(D.release)} (${esc(D.date)}). Lean source links point to <a href="${GH}/tree/${encodeURIComponent(D.ref)}" target="_blank" rel="noopener"><code>${esc(D.ref)}</code></a> (commit <code>${esc(D.commit.slice(0, 7))}</code>).</span>
      <span>Lean ${esc(D.toolchain.lean)} · Mathlib ${esc(D.toolchain.mathlib)}</span>
      <span>Apache-2.0</span>
    </footer>`;

  // ---------------------------------------------------------------- home
  const BOXES = [
    ["thm", "Statement", "The definition or theorem in ordinary mathematical language, numbered as in the book."],
    ["lean", "Lean, verbatim", "The declaration copied from the source, without its proof. The file and line link to GitHub."],
    ["dictionary", "From the mathematics to the Lean statement", "A fidelity check: it decodes the Lean statement and compares it with the mathematics."],
    ["physics", "Physical meaning", "What the statement means for a physicist."],
    ["proof", "Proof on paper", "The argument, explained for a human reader."],
    ["status", "What the machine verified", "The axioms reported by Lean and every hypothesis the theorem carries."],
    ["warning", "Trap / dead end", "Where a definition or a route does not mean what one would expect."],
  ];
  function viewHome() {
    const s = D.stats;
    let hl = "";
    for (const g of D.headlines) {
      hl += `<div class="hl-group"><h3>${g.title}</h3><div class="hl-grid">`;
      for (const r of g.rows) {
        const links = r.links.map((l) => {
          const book = l.ch ? `<a class="go" href="${chHref(l.ch, l.id)}" title="Read it in the book">${esc(l.label || "In the book")}</a>` : "";
          const src = l.file ? `<a href="${srcUrl(l.file, l.line)}" target="_blank" rel="noopener" title="${esc(l.file)}:${l.line}">source ↗</a>` : "";
          return `<span class="chip"><button type="button" class="nm" data-copy="${esc(l.full || l.name)}" title="Copy the Lean name">${esc(l.name)}</button>${book}${src}</span>`;
        }).join("");
        hl += `<div class="hl"><h4>${r.head}</h4><p>${r.body}</p><div class="chips">${links}</div></div>`;
      }
      hl += "</div></div>";
    }
    let toc = "";
    D.parts.forEach((p, i) => {
      const app = p.title === "Appendices";
      toc += `<div class="toc-part"><h4>${app ? "" : ROMAN[i] + ". "}${esc(p.title)}</h4><ol>`;
      for (const k of p.chapters) { const c = chapters.get(k); toc += `<li><a href="${chHref(k)}"><span class="sb-num">${esc(c.num)}</span><span>${c.title}</span></a></li>`; }
      toc += "</ol></div>";
    });
    const pre = D.chapters.find((c) => c.matter === "front");
    const cmds = ["lake exe cache get", "lake build VOA", "python3 scripts/check_repository.py", "python3 scripts/audit/run_axiom_audits.py"];
    return `<div class="wrap">
      <section class="hero">
        <div class="eyebrow">${esc(D.release)} · ${esc(D.date)}</div>
        <h1>Vertex Operator Algebras in Lean</h1>
        <p class="lede">The LeanVOA library and the construction of the Moonshine module</p>
        <p class="authors">Fedor Popov and Leonardo Rastelli, with Claude (Anthropic)</p>
        <div class="btns">
          <a class="btn primary" href="${pre ? chHref(pre.key) : chHref(order[0])}">Start reading →</a>
          <a class="btn" href="${chHref(order.find((k) => chapters.get(k).matter === "main"))}">Chapter 1</a>
          <a class="btn" href="${GH}" target="_blank" rel="noopener">Repository</a>
          <a class="btn" href="${srcUrl("Notes/book.pdf")}" target="_blank" rel="noopener">PDF</a>
        </div>
      </section>
      <div class="stats">
        <div class="stat"><b>${s.chapters}</b><span>chapters</span></div>
        <div class="stat"><b>${s.statements.toLocaleString("en")}</b><span>numbered definitions, theorems and remarks</span></div>
        <div class="stat"><b>${s.quoted.toLocaleString("en")}</b><span>Lean declarations quoted verbatim, each linked to its source line</span></div>
        <div class="stat"><b>${s.leanFiles.toLocaleString("en")}</b><span>Lean files in <code>VOA/</code></span></div>
      </div>

      <section class="block">
        <h2>How a statement is presented</h2>
        <p class="sub">Every definition and theorem is followed by the pieces below. The toolbar of a chapter shows or hides each kind.</p>
        <div class="anatomy">${BOXES.map(([k, t, d]) => `<div class="an an-${k}"><h4>${esc(t)}</h4><p>${esc(d)}</p></div>`).join("")}</div>
      </section>

      <section class="block">
        <h2>Main results</h2>
        <p class="sub">Each card names the Lean declarations: the label opens the statement in the book, <i>source</i> the line on GitHub.</p>
        ${hl}
      </section>

      <section class="block">
        <h2>Contents</h2>
        <div class="toc-grid">${toc}</div>
      </section>

      <section class="block">
        <h2>Build and check</h2>
        <p class="sub">With <a href="https://github.com/leanprover/elan" target="_blank" rel="noopener">elan</a> installed, from a clone of the repository:</p>
        <div class="code plain"><div class="code-h"><span>shell</span><button type="button" class="mini-btn" data-copytext="${esc(cmds.join("\n"))}">Copy</button></div>
          <pre><code>${cmds.map(esc).join("\n")}</code></pre></div>
      </section>
      ${footer()}
    </div>`;
  }

  // ---------------------------------------------------------------- chapter
  const TOGGLES = [["lean", "Lean code"], ["dictionary", "Lean dictionary"], ["physics", "Physics"], ["proof", "Proofs"], ["status", "Machine status"], ["warning", "Traps"]];
  function applyToggles() {
    const hidden = store.get("hidden", []);
    for (const [k] of TOGGLES) document.body.classList.toggle("hide-" + k, hidden.includes(k));
    $$("[data-toggle]").forEach((b) => b.setAttribute("aria-pressed", !hidden.includes(b.dataset.toggle)));
  }
  function viewChapterShell(c) {
    const i = order.indexOf(c.key);
    const prev = chapters.get(order[i - 1]), next = chapters.get(order[i + 1]);
    const part = c.part != null ? D.parts[c.part] : null;
    const crumb = part ? (part.title === "Appendices" ? "Appendices" : `Part ${ROMAN[c.part]} · ${esc(part.title)}`) : "Front matter";
    const toc = (c.toc || []).filter((t) => t[0] <= 2);
    return `<div class="wrap"><div class="ch-grid"><div class="ch-main">
      <div class="ch-head">
        <div class="crumb">${crumb}</div>
        ${chLabel(c) ? `<div class="ch-label">${chLabel(c)}</div>` : ""}
        <h1>${c.title}</h1>
      </div>
      <div class="toolbar" role="group" aria-label="Show or hide">
        <span class="tb-label">Show</span>
        ${TOGGLES.map(([k, l]) => `<button type="button" class="tg tg-${k}" data-toggle="${k}" aria-pressed="true">${l}</button>`).join("")}
      </div>
      <article class="book" id="book"><div class="loading">Loading the chapter…</div></article>
      <nav class="pager">
        ${prev ? `<a class="prev" href="${chHref(prev.key)}"><span class="lbl">← ${chLabel(prev) || "Previous"}</span>${prev.shortTitle}</a>` : "<span></span>"}
        ${next ? `<a class="next" href="${chHref(next.key)}"><span class="lbl">${chLabel(next) || "Next"} →</span>${next.shortTitle}</a>` : ""}
      </nav>
      ${footer()}
      </div>
      <nav class="otp" aria-label="Sections of this chapter"><h5>On this page</h5>
        ${toc.map((t) => `<a href="${chHref(c.key, t[3])}" data-otp="${esc(t[3])}" class="lv${t[0]}"><span class="num">${esc(t[1])}</span><span>${t[2]}</span></a>`).join("")}
      </nav></div></div>`;
  }

  let mathObs = null, spy = null;
  function typesetSection(sec) {
    if (!sec || sec.dataset.done) return;
    sec.dataset.done = "1";
    if (mathObs) mathObs.unobserve(sec);
    const above = sec.getBoundingClientRect().bottom < 0;
    const h0 = sec.offsetHeight;
    typeset(sec);
    if (above) window.scrollBy(0, sec.offsetHeight - h0); // keep the reader's place when a section above grows
  }
  function setupLazyMath(root) {
    const secs = $$("section.sec", root);
    if (!("IntersectionObserver" in window)) { secs.forEach(typesetSection); return; }
    mathObs = new IntersectionObserver((entries) => entries.forEach((e) => e.isIntersecting && typesetSection(e.target)),
      { rootMargin: "1500px 0px 1500px 0px" });
    secs.forEach((s) => mathObs.observe(s));
  }
  function decorate(root) {
    $$("a.src[data-f]", root).forEach((a) => { a.href = srcUrl(a.dataset.f, a.dataset.l); a.target = "_blank"; a.rel = "noopener"; });
    $$("code.path[data-f], code.path[data-d]", root).forEach((c) => {
      const a = document.createElement("a");
      a.className = "pathlink";
      a.href = c.dataset.f ? srcUrl(c.dataset.f) : treeUrl(c.dataset.d);
      a.target = "_blank"; a.rel = "noopener"; a.title = "Open on GitHub";
      c.replaceWith(a); a.appendChild(c);
    });
    $$("code.ln[data-n]", root).forEach((c) => { c.tabIndex = 0; c.setAttribute("role", "button"); c.title = c.dataset.n; });
  }
  function setupSpy(c) {
    const links = new Map($$(".otp a").map((a) => [a.dataset.otp, a]));
    if (!links.size || !("IntersectionObserver" in window)) return;
    const heads = $$("#book h2[id], #book h3[id]").filter((h) => links.has(h.id));
    spy = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        links.forEach((a) => a.classList.remove("on"));
        const a = links.get(e.target.id);
        if (a) {
          a.classList.add("on");
          const o = $(".otp");
          if (o && (a.offsetTop < o.scrollTop || a.offsetTop > o.scrollTop + o.clientHeight - 30)) o.scrollTop = a.offsetTop - 80;
        }
      }
    }, { rootMargin: "-80px 0px -75% 0px" });
    heads.forEach((h) => spy.observe(h));
  }
  function goTo(id, flash = true) {
    const el = id && document.getElementById(id);
    if (!el) return false;
    const sec = el.closest("section.sec");
    if (sec) { typesetSection(sec.previousElementSibling); typesetSection(sec); }
    el.scrollIntoView({ block: "start" });
    if (flash) { el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1800); }
    // web fonts and formulas above may still change the layout: settle once more unless the reader has moved
    userMoved = false;
    const again = () => { if (!userMoved) el.scrollIntoView({ block: "start" }); };
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => setTimeout(again, 60));
    setTimeout(again, 700);
    return true;
  }
  let userMoved = false;
  ["wheel", "touchstart", "keydown", "mousedown"].forEach((ev) => window.addEventListener(ev, () => { userMoved = true; }, { passive: true }));
  let routeSeq = 0;
  async function showChapter(c, target) {
    const seq = ++routeSeq;
    const main = $("#main");
    main.innerHTML = viewChapterShell(c);
    typeset($(".ch-head", main)); typeset($(".otp", main)); typeset($(".pager", main));
    applyToggles();
    window.scrollTo(0, 0);
    let data;
    try { data = await loadChapter(c.key); }
    catch (e) {
      if (seq === routeSeq) $("#book").innerHTML = `<div class="empty">The chapter could not be loaded. Serve the site over HTTP (see <code>site/README.md</code>), or read <a href="${srcUrl("Notes/book.pdf")}">the PDF</a>.</div>`;
      return;
    }
    if (seq !== routeSeq) return;
    const book = $("#book");
    book.innerHTML = data.html;
    decorate(book);
    setupLazyMath(book);
    setupSpy(c);
    currentLabels = data.labels || {};
    if (target) goTo(targetId(target));
  }
  let currentLabels = {};
  // a target is a label of the book (l06:thm:virYA), an element id (s-7.12) or a statement number (7.12)
  const targetId = (t) => currentLabels[t] || (document.getElementById(t) ? t : "s-" + t);

  // ---------------------------------------------------------------- popovers: names and cross-references
  const pop = () => $("#pop");
  function hidePop() { const p = pop(); p.hidden = true; p.dataset.for = ""; }
  function placePop(anchor) {
    const p = pop();
    p.hidden = false;
    const r = anchor.getBoundingClientRect();
    const w = Math.min(p.offsetWidth, window.innerWidth - 24);
    let left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12));
    let top = r.bottom + 8;
    if (top + p.offsetHeight > window.innerHeight - 12 && r.top - p.offsetHeight - 8 > 12) top = r.top - p.offsetHeight - 8;
    p.style.left = left + "px";
    p.style.top = top + "px";
  }
  function namePop(code) {
    const full = code.dataset.n, file = code.dataset.f, line = code.dataset.l;
    const places = (idxByFull.get(full) || []).filter((e, i, a) => a.findIndex((x) => x.ch === e.ch && x.id === e.id) === i);
    const p = pop();
    p.innerHTML = `<div class="pop-name"><code>${esc(full).replace(/\./g, ".<wbr>")}</code></div>
      <div class="pop-rows">
        <a href="${srcUrl(file, line)}" target="_blank" rel="noopener">${esc(file)}<span class="ln-no">:${esc(line)}</span> ↗</a>
        ${places.slice(0, 6).map((e) => `<a href="${chHref(e.ch, e.id)}">${esc(e.label)} <span class="muted">in ${esc(chLabel(chapters.get(e.ch)) || "the book")}</span></a>`).join("")}
      </div>
      <div class="pop-act"><button type="button" class="mini-btn" data-copy="${esc(full)}">Copy name</button></div>`;
    p.dataset.for = "name";
    placePop(code);
  }
  let hoverTimer = null;
  async function xrefPop(a) {
    const m = (a.getAttribute("href") || "").match(/^#\/c\/([^/]+)\/(.+)$/);
    if (!m) return;
    const key = decodeURIComponent(m[1]), id = decodeURIComponent(m[2]);
    if (id === "top") return;
    let el;
    try {
      const data = await loadChapter(key);
      const doc = document.createElement("div");
      doc.innerHTML = data.html;
      el = doc.querySelector("#" + CSS.escape(id));
    } catch (e) { return; }
    if (!el || a.dataset.hover !== "1") return;
    let content;
    if (el.classList.contains("thm")) {
      content = el.cloneNode(true);
      content.querySelectorAll(".permalink").forEach((x) => x.remove());
    } else if (/^H[234]$/.test(el.tagName)) {
      content = document.createElement("div");
      content.appendChild(el.cloneNode(true));
      let n = el.nextElementSibling;
      while (n && n.tagName === "P" && content.childNodes.length < 2) { content.appendChild(n.cloneNode(true)); n = n.nextElementSibling; }
    } else if (el.classList.contains("eq") || el.classList.contains("anchor")) {
      const host = el.closest("p, li, .thm") || el;
      content = host.cloneNode(true);
    } else {
      content = el.cloneNode(true);
    }
    content.querySelectorAll("[id]").forEach((x) => x.removeAttribute("id"));
    if (content.id) content.removeAttribute("id");
    const p = pop();
    p.innerHTML = `<div class="pop-preview book"></div><div class="pop-act"><a class="mini-btn" href="${esc(a.getAttribute("href"))}">Go there</a>${key !== currentChapter ? `<span class="muted">${esc(chLabel(chapters.get(key)) || "")}</span>` : ""}</div>`;
    $(".pop-preview", p).appendChild(content);
    typeset(p);
    p.dataset.for = "xref";
    placePop(a);
  }

  // ---------------------------------------------------------------- search
  function searchStmts(q, limit) {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return [];
    const res = [];
    for (const s of stmts) {
      let score = 0, ok = true;
      for (const t of terms) {
        const inTitle = s.titleText.toLowerCase().includes(t), inText = s.hay.includes(t), isNum = s.num === t;
        if (!(inText || isNum)) { ok = false; break; }
        score += (isNum ? 60 : 0) + (inTitle ? 8 : 0) + 1;
      }
      if (ok) res.push([score + (s.kind === "Theorem" ? 0.5 : 0), s]);
    }
    res.sort((a, b) => b[0] - a[0]);
    return res.slice(0, limit).map((x) => x[1]).concat(res.length > limit ? [{ more: res.length }] : []);
  }
  function searchNames(q, limit) {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return [];
    const tq = terms.join("");
    const res = [];
    for (const n of allNames) {
      const l = n.toLowerCase();
      if (terms.every((t) => l.includes(t))) {
        const short = l.split(".").pop();
        res.push([(short === tq ? 30 : 0) + (short.startsWith(terms[0]) ? 10 : 0) - n.length / 100, n]);
      }
    }
    res.sort((a, b) => b[0] - a[0]);
    return res.slice(0, limit).map((x) => x[1]);
  }
  function highlight(text, q) {
    const terms = q.split(/\s+/).filter((t) => t.length > 1).map((t) => esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const re = terms.length ? new RegExp("(" + terms.join("|") + ")", "gi") : null;
    return String(text).split(/(\\\(.*?\\\)|\\\[.*?\\\])/s)
      .map((seg, i) => (i % 2 ? esc(seg) : re ? esc(seg).replace(re, "<mark>$1</mark>") : esc(seg))).join("");
  }
  function snippet(text, q, width = 260) {
    // a window around the first match that never cuts a formula
    const segs = [];
    const re = /\\\(.*?\\\)|\\\[.*?\\\]/gs;
    let m, last = 0;
    while ((m = re.exec(text))) { segs.push([last, m.index, false]); segs.push([m.index, re.lastIndex, true]); last = re.lastIndex; }
    segs.push([last, text.length, false]);
    const t = q.toLowerCase().split(/\s+/).filter(Boolean)[0] || "";
    const hit = t ? text.toLowerCase().indexOf(t) : -1;
    let start = hit > 90 ? hit - 90 : 0, end = Math.min(text.length, start + width);
    for (const [a, b, math] of segs) {
      if (!math) continue;
      if (a < start && start < b) start = a;
      if (a < end && end < b) end = b;
    }
    const piece = text.slice(start, end).replace(/\\\[([\s\S]*?)\\\]/g, (m0, t) => "\\(" + t.replace(/\\tag\{[^}]*\}/g, "") + "\\)");
    return (start ? "… " : "") + piece + (end < text.length ? " …" : "");
  }
  const stmtLabel = (s) => `${s.kind} ${s.num}`;
  function stmtRow(s, q) {
    const c = chapters.get(s.ch);
    return `<a class="res" href="${chHref(s.ch, s.id)}">
      <div class="r-h"><span class="tag k-${s.kind}">${esc(stmtLabel(s))}</span><span class="r-t">${s.titleText ? highlight(s.titleText, q) : ""}</span><span class="r-c">${esc(chLabel(c))}</span></div>
      <div class="r-s">${highlight(snippet(s.text, q), q)}</div></a>`;
  }
  function nameRow(n, q = "") {
    const es = idxByName.get(n) || [];
    const parts = n.split(".");
    const last = parts.pop();
    const e0 = es.find((e) => e.file) || es[0];
    const places = es.filter((e, i, a) => a.findIndex((x) => x.ch === e.ch && x.id === e.id) === i);
    return `<div class="idx-row"><code><span class="ns">${highlight(parts.join(".") + (parts.length ? "." : ""), q)}</span>${highlight(last, q)}</code>
      <span class="idx-places">${places.slice(0, 4).map((e) => `<a href="${chHref(e.ch, e.id)}">${esc(e.label)}</a>`).join(", ")}${places.length > 4 ? ` +${places.length - 4}` : ""}</span>
      ${e0 && e0.file ? `<a class="src" href="${srcUrl(e0.file, e0.line)}" target="_blank" rel="noopener" title="${esc(e0.full)}">source ↗</a>` : "<span></span>"}</div>`;
  }
  function viewSearch(q) {
    const st = searchStmts(q, 60);
    const more = st.length && st[st.length - 1].more;
    const list = st.filter((x) => !x.more);
    const names = searchNames(q, 40);
    return `<div class="wrap narrow">
      <div class="page-h"><div class="crumb">Search</div><h1>“${esc(q)}”</h1></div>
      <h2 class="sr-h">Statements <span class="muted">${more || list.length}</span></h2>
      ${list.map((s) => stmtRow(s, q)).join("") || '<div class="empty small">No numbered statement matches.</div>'}
      ${more ? `<div class="muted small-note">Showing the first 60 of ${more}. Add words to narrow the search.</div>` : ""}
      ${names.length ? `<h2 class="sr-h">Lean declarations in the index <span class="muted">${names.length}${names.length === 40 ? "+" : ""}</span></h2><div class="idx">${names.map((n) => nameRow(n, q)).join("")}</div>` : ""}
      <h2 class="sr-h">In the text <span class="muted" id="ftCount">searching…</span></h2>
      <div id="ftRes"></div>
      ${footer()}</div>`;
  }
  async function fillFullText(q) {
    const rows = await loadSearch();
    if (!$("#ftRes")) return;
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = [];
    for (const r of rows) {
      if (!terms.every((t) => r.low.includes(t))) continue;
      let n = 0, i = -1;
      while ((i = r.low.indexOf(terms[0], i + 1)) >= 0 && n < 50) n++;
      hits.push([n, r]);
    }
    hits.sort((a, b) => b[0] - a[0]);
    $("#ftCount").textContent = hits.length ? `${hits.length} section${hits.length === 1 ? "" : "s"}` : "none";
    $("#ftRes").innerHTML = hits.slice(0, 40).map(([n, r]) => {
      const c = chapters.get(r.ch);
      return `<a class="res" href="${chHref(r.ch, r.sec === "top" ? "" : r.sec)}">
        <div class="r-h"><span class="r-t">${esc(r.title || (c ? strip(c.title) : ""))}</span><span class="r-c">${esc(chLabel(c))} · ${n} match${n === 1 ? "" : "es"}</span></div>
        <div class="r-s">${highlight(snippet(r.text, q, 300), q)}</div></a>`;
    }).join("") || '<div class="empty small">No section contains all the words.</div>';
    typeset($("#ftRes"));
  }

  // ---------------------------------------------------------------- index
  function viewIndex() {
    return `<div class="wrap narrow">
      <div class="page-h"><div class="crumb">${indexChapter ? esc(chLabel(indexChapter)) : "Index"}</div><h1>Index of Lean declarations</h1>
      <p>Every Lean declaration quoted in the book together with a numbered statement, as in the book's index, with the statement it accompanies and its source line.</p></div>
      <input class="idx-filter" id="idxFilter" type="search" placeholder="Filter ${allNames.length.toLocaleString("en")} names, e.g. moonshine or Zhu" autocomplete="off" spellcheck="false">
      <div class="idx" id="idxList"></div><div class="idx-more" id="idxMore"></div>
      ${footer()}</div>`;
  }
  function fillIndex(f = "", limit = 300) {
    const terms = f.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = allNames.filter((n) => terms.every((t) => n.toLowerCase().includes(t)));
    $("#idxList").innerHTML = hits.slice(0, limit).map((n) => nameRow(n, f)).join("") || '<div class="idx-row">No declaration matches.</div>';
    $("#idxMore").innerHTML = hits.length > limit ? `<button type="button" class="btn" id="idxMoreBtn">Show all ${hits.length.toLocaleString("en")}</button>` : `<span class="muted">${hits.length.toLocaleString("en")} declarations</span>`;
    const b = $("#idxMoreBtn");
    if (b) b.onclick = () => fillIndex(f, Infinity);
  }
  const viewMissing = () => `<div class="wrap"><div class="empty">This page does not exist. <a href="#/">Back to the overview</a>.</div></div>`;

  // ---------------------------------------------------------------- router
  let currentChapter = null;
  function route() {
    let h = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
    // links of the earlier site: #/chapter/N/num
    const old = h.match(/^chapter\/([^/]+)(?:\/(.+))?$/);
    if (old) { location.replace(chHref(old[1], old[2] ? "s-" + old[2] : "")); return; }
    const [kind, a, ...rest] = h.split("/");
    const main = $("#main");
    document.body.classList.remove("nav-open");
    hidePop();
    if (kind === "c" && a === currentChapterKey && $("#book .sec")) {
      // same chapter: only move
      const target = rest.join("/");
      if (target) goTo(targetId(target)); else window.scrollTo(0, 0);
      return;
    }
    if (spy) { spy.disconnect(); spy = null; }
    if (mathObs) { mathObs.disconnect(); mathObs = null; }
    currentChapter = null;
    let title = "LeanVOA · Vertex Operator Algebras in Lean";
    if (!kind) { main.innerHTML = viewHome(); markSidebar("home"); typeset(main); window.scrollTo(0, 0); }
    else if (kind === "c" && chapters.has(a) && !chapters.get(a).is_index) {
      const c = chapters.get(a);
      const target = rest.join("/");
      currentChapter = a;
      showChapter(c, target);
      markSidebar("c-" + a);
      title = `${chLabel(c) ? chLabel(c) + ". " : ""}${strip(c.shortTitle)} · LeanVOA`;
    } else if (kind === "search") {
      const q = [a, ...rest].join("/");
      main.innerHTML = viewSearch(q); markSidebar(""); title = `Search: ${q} · LeanVOA`;
      if ($("#q").value !== q) $("#q").value = q;
      typeset(main); window.scrollTo(0, 0);
      fillFullText(q);
    } else if (kind === "index" || (kind === "c" && chapters.get(a) && chapters.get(a).is_index)) {
      main.innerHTML = viewIndex(); markSidebar("index"); title = "Index of Lean declarations · LeanVOA";
      fillIndex();
      $("#idxFilter").addEventListener("input", (e) => fillIndex(e.target.value));
      window.scrollTo(0, 0);
    } else { main.innerHTML = viewMissing(); markSidebar(""); }
    currentChapterKey = currentChapter;
    document.title = title;
  }
  let currentChapterKey = null;

  // ---------------------------------------------------------------- quick search
  let sgIndex = -1;
  function renderSuggest() {
    const q = $("#q").value.trim();
    const box = $("#suggest");
    if (!q) { box.hidden = true; return; }
    const st = searchStmts(q, 6).filter((x) => !x.more);
    const names = searchNames(q, 5);
    let h = "";
    if (st.length) {
      h += '<div class="sg-head">Statements</div>' + st.map((s) => `<a class="sg" href="${chHref(s.ch, s.id)}">
        <span class="sg-t"><b>${esc(stmtLabel(s))}</b>${s.titleText ? " · " + highlight(s.titleText, q) : ""}</span><span class="sg-s">${esc(chLabel(chapters.get(s.ch)))} · ${highlight(snippet(s.text, q, 110), q)}</span></a>`).join("");
    }
    if (names.length) {
      h += '<div class="sg-head">Lean declarations</div>' + names.map((n) => {
        const e = idxByName.get(n)[0];
        return `<a class="sg" href="${chHref(e.ch, e.id)}"><span class="sg-t"><code>${highlight(n, q)}</code></span><span class="sg-s">${esc(e.label)} · ${esc(chLabel(chapters.get(e.ch)))}</span></a>`;
      }).join("");
    }
    h += `<a class="sg-all" href="#/search/${encodeURIComponent(q)}">Search the whole text for “${esc(q)}” ↵</a>`;
    box.innerHTML = h;
    box.hidden = false;
    typeset(box);
    sgIndex = -1;
  }
  function moveSuggest(d) {
    const opts = $$("#suggest .sg, #suggest .sg-all");
    if (!opts.length) return;
    sgIndex = (sgIndex + d + opts.length) % opts.length;
    opts.forEach((o, i) => o.classList.toggle("active", i === sgIndex));
    opts[sgIndex].scrollIntoView({ block: "nearest" });
  }

  // ---------------------------------------------------------------- events
  function setTheme(next) {
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("leanvoa-theme", next); } catch (e) { /* ignore */ }
  }
  function init() {
    $("#repoLink").href = GH;
    renderSidebar();
    route();
    window.addEventListener("hashchange", route);
    $("#themeBtn").addEventListener("click", () => {
      const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
      setTheme(cur === "dark" ? "light" : "dark");
    });
    $("#menuBtn").addEventListener("click", () => document.body.classList.toggle("nav-open"));
    $("#scrim").addEventListener("click", () => document.body.classList.remove("nav-open"));

    const q = $("#q");
    let sgTimer;
    q.addEventListener("input", () => { clearTimeout(sgTimer); sgTimer = setTimeout(renderSuggest, 80); });
    q.addEventListener("focus", renderSuggest);
    q.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); moveSuggest(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); moveSuggest(-1); }
      else if (e.key === "Escape") { $("#suggest").hidden = true; q.blur(); }
      else if (e.key === "Enter") {
        e.preventDefault();
        const opts = $$("#suggest .sg, #suggest .sg-all");
        const v = q.value.trim();
        if (sgIndex >= 0 && opts[sgIndex]) location.hash = opts[sgIndex].getAttribute("href");
        else if (v) location.hash = "#/search/" + encodeURIComponent(v);
        $("#suggest").hidden = true; q.blur();
      }
    });
    document.addEventListener("click", (e) => {
      const t = e.target;
      if (!t.closest(".search")) $("#suggest").hidden = true;
      if (!t.closest("#pop") && !t.closest("code.ln[data-n]")) hidePop();
      const nm = t.closest("[data-copy]");
      if (nm) { copy(nm.dataset.copy, nm.dataset.copy); return; }
      const ct = t.closest("[data-copytext]");
      if (ct) { copy(ct.dataset.copytext, "commands"); return; }
      const cc = t.closest("[data-copycode]");
      if (cc) { copy(cc.closest(".decl, .code").querySelector("pre code").textContent, "code"); return; }
      const pl = t.closest("[data-perma]");
      if (pl) { copy(location.href.split("#")[0] + chHref(currentChapter, pl.dataset.perma), "link"); return; }
      const tg = t.closest("[data-toggle]");
      if (tg) {
        const hidden = new Set(store.get("hidden", []));
        hidden.has(tg.dataset.toggle) ? hidden.delete(tg.dataset.toggle) : hidden.add(tg.dataset.toggle);
        store.set("hidden", [...hidden]);
        applyToggles();
        return;
      }
      const sg = t.closest(".sg, .sg-all");
      if (sg) { $("#suggest").hidden = true; q.blur(); return; }
      const code = t.closest("code.ln[data-n]");
      if (code) { e.preventDefault(); namePop(code); }
    });
    document.addEventListener("keydown", (e) => {
      const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
      if (e.key === "Escape") hidePop();
      if (e.key === "Enter" && document.activeElement.matches && document.activeElement.matches("code.ln[data-n]")) { namePop(document.activeElement); return; }
      if ((e.key === "/" && !typing) || (e.key === "k" && (e.metaKey || e.ctrlKey))) { e.preventDefault(); q.focus(); q.select(); return; }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      if (currentChapter && (e.key === "[" || e.key === "]")) {
        const i = order.indexOf(currentChapter) + (e.key === "]" ? 1 : -1);
        if (order[i]) location.hash = chHref(order[i]);
      }
    });
    // hover previews of cross-references
    document.addEventListener("mouseover", (e) => {
      const a = e.target.closest && e.target.closest("a.xref");
      if (!a || a.dataset.hover === "1" || !matchMedia("(hover: hover)").matches) return;
      a.dataset.hover = "1";
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(() => xrefPop(a), 350);
      a.addEventListener("mouseleave", () => {
        a.dataset.hover = "";
        clearTimeout(hoverTimer);
        setTimeout(() => { const p = pop(); if (p.dataset.for === "xref" && !p.matches(":hover")) hidePop(); }, 250);
      }, { once: true });
    });
    pop().addEventListener("mouseleave", () => { if (pop().dataset.for === "xref") hidePop(); });
    window.addEventListener("scroll", () => { if (pop().dataset.for === "xref") hidePop(); }, { passive: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();
