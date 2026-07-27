import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

function ModelDropdown({ models, value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const selected = models.find((m) => m.name === value) || null;

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div className="model-select-wrap" ref={ref}>
      <button className="model-select-btn" onClick={() => setOpen((v) => !v)} type="button">
        {selected ? (
          <>

            <span className="model-real-name">{selected.name}</span>
            {selected.recommended && <span className="model-rec" title="Recommended">★</span>}
          </>
        ) : (
          <span className="model-kind">Select model</span>
        )}
        <span className="model-chevron">{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <ul className="model-dropdown">
          {models.map((m) => (
            <li
              key={m.name}
              className={"model-opt" + (m.name === value ? " selected" : "")}
              onClick={() => { onChange(m.name); setOpen(false); }}
            >

              <span className="model-real-name">{m.name}</span>
              {m.recommended && <span className="model-rec" title="Recommended">★</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const AMOUNT_COLS = new Set(["Premium", "Premium (Without GST)"]);
const DATE_COLS = new Set(["Date Start", "End Date"]);
const CAMEL_COLS = new Set(["Party Name", "Type of Insurance"]);

const MONTH_MAP = { jan:0, feb:1, mar:2, apr:3, may:4, jun:5, jul:6, aug:7, sep:8, oct:9, nov:10, dec:11 };

function formatAmount(val) {
  if (val == null || val === "") return "";
  const clean = String(val).replace(/[₹,\s]/g, "").replace(/\.0+$/, "");
  const num = parseFloat(clean);
  if (isNaN(num)) return String(val);
  return "₹" + Math.round(num).toLocaleString("en-IN");
}

function formatPolicyNo(val) {
  if (val == null || val === "") return "";
  return String(val).replace(/\s+/g, " ").trim();
}

function toTitleCase(val) {
  if (!val) return val;
  return String(val).toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatDate(val) {
  if (val == null || val === "") return "";
  const s = String(val).trim();
  let d = null;
  let m;

  m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2})$/);
  if (m) { const yr = +m[3] < 50 ? 2000 + +m[3] : 1900 + +m[3]; d = new Date(yr, +m[2]-1, +m[1]); }

  if (!d) { m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/); if (m) d = new Date(+m[3], +m[2]-1, +m[1]); }

  if (!d) { m = s.match(/^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/i); if (m) d = new Date(+m[3], MONTH_MAP[m[2].toLowerCase()], +m[1]); }

  if (!d) { m = s.match(/^(\d{1,2})\s+([A-Za-z]{3}),?\s+(\d{4})$/i); if (m) d = new Date(+m[3], MONTH_MAP[m[2].toLowerCase()], +m[1]); }

  if (!d) { m = s.match(/^([A-Za-z]{3})\s+(\d{1,2}),?\s+(\d{4})$/i); if (m) d = new Date(+m[3], MONTH_MAP[m[1].toLowerCase()], +m[2]); }

  if (!d) { m = s.match(/^(\d{1,2})\s+([A-Za-z]{3})\s+'(\d{2})$/i); if (m) d = new Date(2000 + +m[3], MONTH_MAP[m[2].toLowerCase()], +m[1]); }

  if (!d || isNaN(d.getTime())) return s;
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth()+1).padStart(2, "0");
  const yy = String(d.getFullYear()).slice(-2);
  return `${dd}/${mm}/${yy}`;
}

const COLUMNS = [
  "Party Name",
  "Insurance Company",
  "Policy No.",
  "Reg Number",
  "Type of Insurance",
  "Premium (Without GST)",
  "Premium",
  "Date Start",
  "End Date",
  "NCB (applied this yr)",
  "Source File",
];

const COLUMN_HELP = {
  "NCB (applied this yr)":
    "Read directly off the policy document (not calculated) — the model looks for the no-claim bonus % printed on the page and copies it as-is. Hover the 🔍 on a row to see where in the PDF it was found.",
};

const STATUS = {
  pending: { label: "Pending", cls: "badge pending" },
  reading: { label: "Reading…", cls: "badge reading" },
  done: { label: "Done", cls: "badge done" },
  error: { label: "Error", cls: "badge error" },
};

let _id = 0;
const uid = () => ++_id;

// Default model pick when none is selected yet: recommended one, else first.
const pickDefaultModel = (models) =>
  models?.find((m) => m.recommended)?.name || models?.[0]?.name || "";

const THEME_ORDER = ["system", "light", "dark"];
const THEME_META = {
  system: { icon: "🖥", label: "System" },
  light: { icon: "☀", label: "Light" },
  dark: { icon: "🌙", label: "Dark" },
};

const autoGrowCell = (el) => {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = el.scrollHeight + "px";
};

export default function App() {
  const [queue, setQueue] = useState([]);
  const [rows, setRows] = useState([]);
  const tableWrapRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("theme") || "system"
  );
  const [concurrency, setConcurrency] = useState(() => {
    const n = parseInt(localStorage.getItem("concurrency"), 10);
    return Number.isFinite(n) && n >= 1 && n <= 100 ? n : 5;
  });
  const [engine, setEngine] = useState("gemini");
  const [geminiModels, setGeminiModels] = useState([]);
  const [geminiModel, setGeminiModel] = useState("");
  const [geminiStatus, setGeminiStatus] = useState(null); // null | "checking" | "ok" | "no-key" | "error"
  const [geminiError, setGeminiError] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [geminiKeyInfo, setGeminiKeyInfo] = useState(null); // {key_set, masked, source}
  const [geminiKeyInput, setGeminiKeyInput] = useState("");
  const [geminiSavingKey, setGeminiSavingKey] = useState(false);
  const [geminiKeyError, setGeminiKeyError] = useState("");
  const [logs, setLogs] = useState([]);
  const [logsOpen, setLogsOpen] = useState(false);
  const [preview, setPreview] = useState(null); // {url, x, y, col, loading}
  const [errorHover, setErrorHover] = useState(null); // { text, x, y }
  const [docModal, setDocModal] = useState(null); // {rowIdx, page, pages, edits}
  const fileInput = useRef(null);
  const folderInput = useRef(null);
  const logsEndRef = useRef(null);
  const hoverTimer = useRef(null);

  useEffect(() => {
    localStorage.setItem("concurrency", String(concurrency));
  }, [concurrency]);

  useEffect(() => {
    localStorage.setItem("theme", theme);
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const resolved =
        theme === "system" ? (mql.matches ? "dark" : "light") : theme;
      document.documentElement.setAttribute("data-theme", resolved);
    };
    apply();
    if (theme === "system") {
      mql.addEventListener("change", apply);
      return () => mql.removeEventListener("change", apply);
    }
  }, [theme]);

  const cycleTheme = () =>
    setTheme((t) => THEME_ORDER[(THEME_ORDER.indexOf(t) + 1) % THEME_ORDER.length]);

  // On mount: probe Gemini, so its engine button only appears
  // once we know a valid key is configured.
  useEffect(() => { checkGemini(); }, []);

  // fetch + JSON parse with useful failures: a network error keeps the classic
  // "could not reach" message, while a non-JSON body (e.g. the HTML 404/405 an
  // outdated backend returns for routes it doesn't know) says to restart the
  // app instead of pretending the server is down.
  const fetchJson = async (url, opts) => {
    let res;
    try {
      res = await fetch(url, opts);
    } catch {
      throw new Error("Could not reach the server — is the app still running?");
    }
    try {
      return { res, data: await res.json() };
    } catch {
      throw new Error(
        `Unexpected server response (HTTP ${res.status}) — the backend looks ` +
        "outdated; restart the app to load the latest code."
      );
    }
  };

  const applyGeminiStatus = (data) => {
    if (data.ok) {
      setGeminiModels(data.models || []);
      setGeminiModel((m) => m || pickDefaultModel(data.models));
      setGeminiStatus("ok");
      return;
    }
    setGeminiError(data.error || "Gemini not reachable");
    setGeminiStatus(data.key_set ? "error" : "no-key");
  };

  const checkGemini = async () => {
    setGeminiStatus("checking");
    setGeminiError("");
    try {
      const { data } = await fetchJson("/api/gemini/status");
      applyGeminiStatus(data);
    } catch (err) {
      setGeminiError(err.message);
      setGeminiStatus("error");
    }
  };

  const openSettings = async () => {
    setSettingsOpen(true);
    setGeminiKeyError("");
    setGeminiKeyInput("");
    try {
      const { data } = await fetchJson("/api/gemini/key");
      setGeminiKeyInfo(data);
    } catch (err) {
      setGeminiKeyInfo(null);
      setGeminiKeyError(err.message);
    }
  };

  const saveGeminiKey = async () => {
    const key = geminiKeyInput.trim();
    if (!key) return;
    setGeminiSavingKey(true);
    setGeminiKeyError("");
    try {
      const { data } = await fetchJson("/api/gemini/key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key }),
      });
      if (data.ok) {
        setGeminiKeyInput("");
        setGeminiKeyInfo({ key_set: data.key_set, masked: data.masked, source: data.source });
        applyGeminiStatus(data);
        flash("Gemini API key saved.", "info");
      } else {
        setGeminiKeyError(data.error || "Key was rejected");
      }
    } catch (err) {
      setGeminiKeyError(err.message);
    } finally {
      setGeminiSavingKey(false);
    }
  };

  const removeGeminiKey = async () => {
    setGeminiKeyError("");
    try {
      const { data } = await fetchJson("/api/gemini/key", { method: "DELETE" });
      if (!data.ok) {
        setGeminiKeyError(data.error || "Could not remove key");
        return;
      }
      setGeminiKeyInfo({ key_set: data.key_set, masked: data.masked, source: data.source });
      // Env-var keys survive removal of the saved one, so re-probe instead of
      // assuming Gemini is now unconfigured.
      setGeminiModel("");
      setGeminiModels([]);
      checkGemini();
      flash("Saved Gemini API key removed.", "info");
    } catch (err) {
      setGeminiKeyError(err.message);
    }
  };


  // SSE log stream
  useEffect(() => {
    const es = new EventSource("/api/logs");
    es.onmessage = (e) => {
      setLogs((l) => [...l.slice(-499), e.data]);
    };
    return () => es.close();
  }, []);

  // Auto-scroll log panel when open
  useEffect(() => {
    if (logsOpen) logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, logsOpen]);

  // Re-probe Gemini only after a transient error — "no-key" means the user
  // hasn't configured one yet, so retrying would just hammer the server.
  useEffect(() => {
    if (geminiStatus === "error") {
      checkGemini();
    }
  }, [geminiStatus]);

  // If user changes the model, retry any failed items
  useEffect(() => {
    if (geminiModel) {
      setQueue((q) => {
        let changed = false;
        const nextQ = q.map((it) => {
          if (it.status === "error") {
            changed = true;
            return { ...it, status: "pending", error: null };
          }
          return it;
        });
        return changed ? nextQ : q;
      });
    }
  }, [geminiModel]);

  useEffect(() => {
    if (folderInput.current) {
      folderInput.current.setAttribute("webkitdirectory", "");
      folderInput.current.setAttribute("directory", "");
      folderInput.current.setAttribute("mozdirectory", "");
    }
  }, []);

  const flash = (msg, kind = "info") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 4000);
  };

  const addFiles = useCallback((fileList) => {
    if (geminiStatus !== "ok") {
      flash("Waiting for Gemini models to load — try again in a moment.", "error");
      return;
    }
    const pdfs = Array.from(fileList).filter((f) =>
      f.name.toLowerCase().endsWith(".pdf")
    );
    if (!pdfs.length) {
      flash("No PDF files in that drop.", "error");
      return;
    }
    setQueue((q) => [
      ...q,
      ...pdfs.map((f) => ({
        id: uid(),
        name: f.name,
        file: f,
        status: "pending",
      })),
    ]);
  }, [geminiStatus]);

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  const setItemStatus = (id, status, error, usedModel) =>
    setQueue((q) =>
      q.map((it) => (it.id === id ? { ...it, status, error, usedModel: usedModel !== undefined ? usedModel : it.usedModel } : it))
    );

  const extractOne = async (item, orderIdx) => {
    setItemStatus(item.id, "reading");

    const modelsToTry = [geminiModel];
    if (geminiModels) {
      for (const m of geminiModels) {
        if (m.name !== geminiModel) {
          modelsToTry.push(m.name);
        }
      }
    }

    let lastErr = null;
    let workedModel = null;

    for (let i = 0; i < modelsToTry.length; i++) {
      const model = modelsToTry[i];
      try {
        let res;
        if (item.file) {
          const fd = new FormData();
          fd.append("file", item.file, item.name);
          if (model) fd.append("model", model);
          res = await fetch("/api/extract", { method: "POST", body: fd });
        } else {
          res = await fetch("/api/extract", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: item.path, model }),
          });
        }
        let data;
        try {
          data = await res.json();
        } catch {
          throw new Error(`Server error (HTTP ${res.status})`);
        }
        if (!res.ok) {
          const errMsg = data.error || "Extraction failed";
          const lower = errMsg.toLowerCase();
          const shouldRetryNext = lower.includes("quota") || lower.includes("429") || lower.includes("exhausted") || lower.includes("rate limit") || res.status === 429 || (lower.includes("unknown") && lower.includes("model"));
          if (shouldRetryNext && i < modelsToTry.length - 1) {
            lastErr = new Error(errMsg);
            continue;
          }
          throw new Error(errMsg);
        }

        const row = { ...data.row, _qidx: orderIdx, _qid: item.id };
        setRows((r) =>
          [...r.filter((x) => x._qid !== item.id), row].sort(
            (a, b) => (a._qidx ?? 0) - (b._qidx ?? 0)
          )
        );
        workedModel = model;
        break; // Succeeded!
      } catch (err) {
        const lower = err.message.toLowerCase();
        const shouldRetryNext = lower.includes("quota") || lower.includes("429") || lower.includes("exhausted") || lower.includes("rate limit") || (lower.includes("unknown") && lower.includes("model"));
        if (shouldRetryNext && i < modelsToTry.length - 1) {
          lastErr = err;
          continue;
        }
        lastErr = err;
        break; // Failed and not retryable
      }
    }

    if (workedModel) {
      setItemStatus(item.id, "done", null, workedModel);
    } else {
      setItemStatus(item.id, "error", lastErr?.message || "Failed");
    }
  };

  const runAll = async () => {
    // Only process files still pending. Failed files stay in "error" until the
    // user hits Retry on their card, which flips them back to pending.
    const targets = queue.filter((it) => it.status === "pending");
    if (!targets.length) return;
    setBusy(true);
    // Row order follows each file's position in the queue.
    const order = new Map(queue.map((it, i) => [it.id, i]));
    // Gemini is cloud API — concurrency is user-configurable (Settings), capped at 100.
    const limit = Math.min(100, Math.max(1, concurrency || 1));
    let next = 0;
    const worker = async () => {
      while (next < targets.length) {
        const item = targets[next++];
        await extractOne(item, order.get(item.id) ?? 0);
      }
    };
    await Promise.all(
      Array.from({ length: Math.min(limit, targets.length) }, worker)
    );
    setBusy(false);
    flash("Done processing.", "info");
  };

  // Extraction starts automatically as soon as files land in the queue —
  // no Extract button. The busy guard keeps a second run from starting while
  // one is in flight; when it finishes, this re-fires and drains any files
  // added in the meantime.
  useEffect(() => {
    if (!busy && queue.some((it) => it.status === "pending")) runAll();
  }, [queue, busy]);

  useEffect(() => {
    if (!tableWrapRef.current) return;
    tableWrapRef.current.querySelectorAll("textarea.cell").forEach(autoGrowCell);
  }, [rows]);

  const removeItem = (id) => {
    setQueue((q) => q.filter((it) => it.id !== id));
  };

  const clearAll = () => {
    setQueue([]);
    setRows([]);
  };

  const editCell = (rowIdx, col, value) =>
    setRows((r) =>
      r.map((row, i) => (i === rowIdx ? { ...row, [col]: value } : row))
    );

  const deleteRow = (rowIdx) => {
    // Drop the file's card too — leaving it "pending" would make the
    // auto-extract effect immediately redo it and resurrect the row.
    const qid = rows[rowIdx]?._qid;
    if (qid) setQueue((q) => q.filter((it) => it.id !== qid));
    setRows((r) => r.filter((_, i) => i !== rowIdx));
  };

  const csvField = (value) => {
    const s = String(value ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };

  const copyAllData = async () => {
    if (!rows.length) return flash("No results to copy.", "error");
    const copyCols = COLUMNS.filter((c) => c !== "Source File");
    const csv =
      rows.map((row) => copyCols.map((c) => csvField(row[c])).join(",")).join("\n") + "\n";
    try {
      await navigator.clipboard.writeText(csv);
      flash(`Copied ${rows.length} rows to clipboard.`, "info");
    } catch {
      flash("Could not copy to clipboard.", "error");
    }
  };

  const copyError = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      flash("Error copied to clipboard.", "info");
    } catch {
      flash("Could not copy to clipboard.", "error");
    }
  };

  // ── PDF hover preview ──────────────────────────────────────────────────
  // A located field carries {page, bbox}. On hover we show a zoomed, highlighted
  // crop of the source PDF so the user can verify the extracted value at a glance.
  const previewUrl = (row, loc) => {
    const [x0, top, x1, bottom] = loc.bbox;
    const q = new URLSearchParams({ doc_id: row._doc_id, page: loc.page, x0, top, x1, bottom });
    return `/api/preview?${q.toString()}`;
  };

  const clampPoint = (x, y) => ({
    // popover is ~380×260; nudge it back inside the viewport near the edges
    x: Math.min(x + 18, window.innerWidth - 396),
    y: Math.min(y + 18, window.innerHeight - 272),
  });

  const showPreview = (e, row, col) => {
    const loc = row._locations?.[col];
    if (!row._doc_id || !loc) return;
    const url = previewUrl(row, loc);
    const { x, y } = clampPoint(e.clientX, e.clientY);
    clearTimeout(hoverTimer.current);
    hoverTimer.current = setTimeout(
      () => setPreview({ url, x, y, col, loading: true }),
      220
    );
  };

  const movePreview = (e) => {
    setPreview((p) => (p ? { ...p, ...clampPoint(e.clientX, e.clientY) } : p));
  };

  const hidePreview = () => {
    clearTimeout(hoverTimer.current);
    setPreview(null);
  };

  const showErrorHover = (e, text) => {
    setErrorHover({ text, x: e.clientX, y: e.clientY });
  };
  const moveErrorHover = (e) => {
    setErrorHover((p) => (p ? { ...p, x: e.clientX, y: e.clientY } : p));
  };
  const hideErrorHover = () => {
    setErrorHover(null);
  };

  // ── Full-screen PDF verify modal ────────────────────────────────────────
  const docModalPageRefs = useRef({});
  const docModalDrag = useRef(null);

  const openDocModal = (rowIdx) => {
    const row = rows[rowIdx];
    if (!row?._doc_id) return;
    const pages = [...new Set(Object.values(row._locations || {}).map((l) => l.page))].sort((a, b) => a - b);
    const edits = {};
    COLUMNS.forEach((c) => { edits[c] = c === "Policy No." ? formatPolicyNo(row[c]) : row[c] ?? ""; });
    docModalPageRefs.current = {};
    setDocModal({ rowIdx, pages, edits, zoom: 1, selectedField: null });
  };

  const closeDocModal = () => setDocModal(null);

  const renderPageUrl = (row, page, selectedField) => {
    const q = new URLSearchParams({
      doc_id: row._doc_id,
      page,
      locations: JSON.stringify(row._locations || {}),
    });
    if (selectedField) q.set("selected", selectedField);
    return `/api/render-page?${q.toString()}`;
  };

  // Selecting a field scrolls its page into view and highlights it.
  const selectDocModalField = (col) => {
    setDocModal((m) => (m ? { ...m, selectedField: col } : m));
    const row = rows[docModal?.rowIdx];
    const loc = row?._locations?.[col];
    const el = loc ? docModalPageRefs.current[loc.page] : null;
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const ZOOM_MIN = 1;
  const ZOOM_MAX = 3;
  const ZOOM_STEP = 0.25;
  const zoomDocModal = (delta) => {
    setDocModal((m) =>
      m ? { ...m, zoom: Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, +(m.zoom + delta).toFixed(2))) } : m
    );
  };
  const resetZoomDocModal = () => setDocModal((m) => (m ? { ...m, zoom: 1 } : m));

  // Drag-to-pan the PDF view (useful once zoomed in, or to scroll sideways).
  const onDocModalMouseDown = (e) => {
    if (e.button !== 0) return;
    const wrap = e.currentTarget;
    docModalDrag.current = {
      startX: e.clientX,
      startY: e.clientY,
      scrollLeft: wrap.scrollLeft,
      scrollTop: wrap.scrollTop,
    };
  };
  const onDocModalMouseMove = (e) => {
    if (!docModalDrag.current) return;
    e.preventDefault();
    const wrap = e.currentTarget;
    const d = docModalDrag.current;
    wrap.scrollLeft = d.scrollLeft - (e.clientX - d.startX);
    wrap.scrollTop = d.scrollTop - (e.clientY - d.startY);
  };
  const endDocModalDrag = () => {
    docModalDrag.current = null;
  };

  const submitDocModal = () => {
    if (!docModal) return;
    setRows((r) =>
      r.map((row, i) => (i === docModal.rowIdx ? { ...row, ...docModal.edits } : row))
    );
    flash("Row updated.", "info");
    setDocModal(null);
  };

  const cellHoverProps = (row, col) =>
    row._doc_id && row._locations?.[col]
      ? {
          onMouseEnter: (e) => showPreview(e, row, col),
          onMouseMove: movePreview,
          onMouseLeave: hidePreview,
        }
      : {};

  const counts = useMemo(() => {
    const c = { pending: 0, reading: 0, done: 0, error: 0 };
    queue.forEach((it) => (c[it.status] = (c[it.status] || 0) + 1));
    return c;
  }, [queue]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <img src="/app-icon.png" className="logo-img" alt="App icon" />
          <div>
            <h1>Insurance Policy Extractor</h1>
            <p className="sub">Offline PDF → Excel. Nothing leaves your machine.</p>
          </div>
        </div>
        <div className="topbar-right">
          <button
            className="theme-toggle"
            onClick={cycleTheme}
            title={`Theme: ${THEME_META[theme].label} (click to change)`}
          >
            <span className="t-icon">{THEME_META[theme].icon}</span>
            {THEME_META[theme].label}
          </button>
          <button className="theme-toggle" onClick={openSettings} title="Settings">
            <span className="t-icon">⚙</span>
            Settings
          </button>
          <span className="offline-pill">● Local only</span>
        </div>
      </header>

      {/* Add PDFs section — full width */}
      <section className="card add-section">
        <div className="section-head">
          <h2>1 · Add policy PDFs</h2>
          <div className="engine-bar">
            <span className="engine-label">Engine: Gemini (Google AI)</span>
            <div className="ollama-config" style={{ marginLeft: "12px" }}>
              {geminiStatus === "checking" && <span className="muted">Checking…</span>}
              {geminiStatus === "no-key" && (
                <span className="gemini-key-row">
                  <span className="ollama-err">✕ No API key</span>
                  <button className="key-save-btn" onClick={openSettings}>
                    ⚙ Add key in Settings
                  </button>
                </span>
              )}
              {geminiStatus === "error" && (
                <span className="ollama-err" title={geminiError}>
                  ✕ {geminiError || "Not reachable"}
                  <button className="retry-btn" onClick={checkGemini}>Retry</button>
                </span>
              )}
              {geminiStatus === "ok" && (
                <>
                  <ModelDropdown
                    models={geminiModels}
                    value={geminiModel}
                    onChange={setGeminiModel}
                  />
                  <span className="muted engine-cloud-note" title="The Gemini engine sends document contents to Google's API.">
                    ☁ sends PDFs to Google
                  </span>
                </>
              )}
            </div>
          </div>
        </div>

        <div
          className={"dropzone" + (dragging ? " active" : "") + (geminiStatus !== "ok" ? " locked" : "")}
          onDragOver={(e) => { e.preventDefault(); if (geminiStatus === "ok") setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={(e) => { if (!e.defaultPrevented && geminiStatus === "ok") fileInput.current?.click(); }}
        >
          <div className="dz-icon">⬆</div>
          <div className="dz-text">
            {geminiStatus === "ok" ? (
              <>
                <strong>Drag &amp; drop PDFs here</strong>
                <div className="muted">or click to pick files</div>
                <button
                  className="dz-folder-btn"
                  onClick={(e) => { e.preventDefault(); e.stopPropagation(); folderInput.current?.click(); }}
                >
                  📁 Pick a folder
                </button>
              </>
            ) : (
              <div className="muted">Waiting for Gemini models to load…</div>
            )}
          </div>
        </div>

        {/* hidden native pickers */}
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          disabled={geminiStatus !== "ok"}
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
        />
        <input
          ref={folderInput}
          type="file"
          hidden
          disabled={geminiStatus !== "ok"}
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
        />

        {/* File grid */}
        {queue.length > 0 && (
          <div className="queue-row">
            <div className="file-grid">
              {queue.map((it) => (
                <div key={it.id} className={`file-box status-${it.status}`}>
                  <button className="file-box-x" onClick={() => removeItem(it.id)} title="Remove">×</button>
                  <div className="file-box-icon">📄</div>
                  <div className="file-box-body">
                    <div className="file-box-name" title={it.name}>{it.name}</div>
                    {it.usedModel && <div className="muted" style={{fontSize: "10px", marginTop: "2px"}}>Model: {it.usedModel}</div>}
                    {it.error && (
                      <div className="file-box-error-wrap">
                        <div
                          className="file-box-error"
                          onMouseEnter={(e) => showErrorHover(e, it.error)}
                          onMouseMove={moveErrorHover}
                          onMouseLeave={hideErrorHover}
                        >
                          {it.error}
                        </div>
                      </div>
                    )}
                    {it.status === "error" && (
                      <div className="error-actions">
                        <button className="retry-btn" onClick={() => setItemStatus(it.id, "pending")}>
                          Retry
                        </button>
                        <button
                          className="copy-error-btn"
                          title="Copy error"
                          onClick={() => copyError(it.error)}
                        >
                          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                          </svg>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <button className="btn ghost queue-clear" onClick={clearAll} disabled={busy || !queue.length}>
              Clear
            </button>
          </div>
        )}
      </section>

      {/* Results */}
      <section className="card results">
        <div className="card-head">
          <h2>2 · Results {rows.length > 0 && <span className="count">({rows.length})</span>}</h2>
          <div className="row output-row">
            <button className="btn primary" onClick={copyAllData} disabled={busy || !rows.length}>
              📋 Copy
            </button>
          </div>
        </div>

        {rows.length === 0 ? (
          <div className="empty">Extracted rows will appear here — fully editable before export.</div>
        ) : (
          <div className="table-wrap" ref={tableWrapRef}>
            <table>
              <thead>
                <tr>
                  <th className="rownum">#</th>
                  {COLUMNS.map((c) => (
                    <th key={c} title={COLUMN_HELP[c]}>{c}</th>
                  ))}
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    <td className="rownum">{i + 1}</td>
                    {COLUMNS.map((c) => {
                      const raw = row[c] ?? "";
                      const hasLoc = !!(row._doc_id && row._locations?.[c]);
                      const verifyBadge = hasLoc ? (
                        <span className="verify-badge" title="Hover to preview from PDF">🔍</span>
                      ) : null;
                      const tdClass = (base) =>
                        (base ? base + " " : "") + (hasLoc ? "has-loc" : "");
                      if (AMOUNT_COLS.has(c)) {
                        return (
                          <td key={c} className={tdClass("col-amount")} {...cellHoverProps(row, c)}>
                            <input className="cell cell-amount" value={formatAmount(raw)} onChange={(e) => editCell(i, c, e.target.value)} />
                            {verifyBadge}
                          </td>
                        );
                      }
                      if (DATE_COLS.has(c)) {
                        return (
                          <td key={c} className={tdClass("col-date")} {...cellHoverProps(row, c)}>
                            <input className="cell cell-date" value={formatDate(raw)} onChange={(e) => editCell(i, c, e.target.value)} />
                            {verifyBadge}
                          </td>
                        );
                      }
                      return (
                        <td key={c} className={tdClass("")} {...cellHoverProps(row, c)}>
                          <textarea
                            className="cell"
                            ref={autoGrowCell}
                            value={CAMEL_COLS.has(c) ? toTitleCase(raw) : c === "Policy No." ? formatPolicyNo(raw) : raw}
                            onChange={(e) => editCell(i, c, e.target.value)}
                            onInput={(e) => autoGrowCell(e.target)}
                            rows={1}
                          />
                          {verifyBadge}
                        </td>
                      );
                    })}
                    <td className="row-actions">
                      <div className="row-actions-stack">
                        <button className="x" onClick={() => deleteRow(i)} title="Delete row">×</button>
                        {row._doc_id && (
                          <button
                            className="row-preview-btn"
                            onClick={() => openDocModal(i)}
                            title="Preview PDF with all extracted fields"
                          >
                            🔍
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Log panel */}
      <section className={"card log-panel" + (logsOpen ? " open" : "")}>
        <button className="log-panel-header" onClick={() => setLogsOpen((v) => !v)}>
          <span>Logs</span>
          <span className="log-count">{logs.length}</span>
          <span className="log-chevron">{logsOpen ? "▲" : "▼"}</span>
        </button>
        {logsOpen && (
          <div className="log-body">
            {logs.length === 0
              ? <span className="muted">No logs yet.</span>
              : logs.map((line, i) => <div key={i} className="log-line">{line}</div>)
            }
            <div ref={logsEndRef} />
          </div>
        )}
      </section>

      {preview && (
        <div className="pdf-preview-pop" style={{ left: preview.x, top: preview.y }}>
          <div className="pdf-preview-cap">
            <span className="pdf-preview-zoom">🔍</span>
            <span>{preview.col} — from PDF</span>
          </div>
          <div className="pdf-preview-frame">
            {preview.loading && <div className="pdf-preview-spinner">Loading…</div>}
            <img
              src={preview.url}
              alt={`PDF source for ${preview.col}`}
              className="pdf-preview-img"
              onLoad={() => setPreview((p) => (p ? { ...p, loading: false } : p))}
              onError={() => setPreview((p) => (p ? { ...p, loading: false, failed: true } : p))}
            />
            {preview.failed && <div className="pdf-preview-spinner">Preview unavailable</div>}
          </div>
        </div>
      )}

      {docModal && rows[docModal.rowIdx] && (
        <div className="modal-overlay doc-modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) closeDocModal(); }}>
          <div className="doc-modal-card">
            <div className="modal-head">
              <h2>Verify — {rows[docModal.rowIdx]["Source File"]}</h2>
              <button className="x" onClick={closeDocModal} title="Close">×</button>
            </div>
            <div className="doc-modal-body">
              <div className="doc-modal-pdf">
                <div className="doc-modal-toolbar">
                  <div className="doc-modal-zoom">
                    <button
                      className="btn ghost zoom-btn"
                      onClick={() => zoomDocModal(-ZOOM_STEP)}
                      disabled={docModal.zoom <= ZOOM_MIN}
                      title="Zoom out"
                    >
                      −
                    </button>
                    <span className="zoom-level" onClick={resetZoomDocModal} title="Reset zoom">
                      {Math.round(docModal.zoom * 100)}%
                    </span>
                    <button
                      className="btn ghost zoom-btn"
                      onClick={() => zoomDocModal(ZOOM_STEP)}
                      disabled={docModal.zoom >= ZOOM_MAX}
                      title="Zoom in"
                    >
                      +
                    </button>
                  </div>
                </div>
                <div
                  className="doc-modal-img-wrap"
                  onMouseDown={onDocModalMouseDown}
                  onMouseMove={onDocModalMouseMove}
                  onMouseUp={endDocModalDrag}
                  onMouseLeave={endDocModalDrag}
                >
                  {docModal.pages.map((p) => (
                    <div
                      key={p}
                      ref={(el) => { if (el) docModalPageRefs.current[p] = el; }}
                      className="doc-modal-page"
                    >
                      <img
                        src={renderPageUrl(rows[docModal.rowIdx], p, docModal.selectedField)}
                        alt={`PDF page ${p + 1} with extracted fields highlighted`}
                        className="doc-modal-img"
                        draggable={false}
                        style={{ width: `${docModal.zoom * 100}%`, maxWidth: docModal.zoom > 1 ? "none" : "100%" }}
                      />
                    </div>
                  ))}
                </div>
                <div className="muted doc-modal-hint">
                  Drag to pan · click a field to jump to it on the page
                </div>
              </div>
              <div className="doc-modal-fields">
                {COLUMNS.filter((c) => c !== "Source File").map((c) => (
                  <label
                    key={c}
                    className={"doc-modal-field" + (docModal.selectedField === c ? " selected" : "")}
                  >
                    <span className="doc-modal-field-label">{c}</span>
                    <input
                      className="doc-modal-field-input"
                      value={c === "Policy No." ? formatPolicyNo(docModal.edits[c]) : docModal.edits[c] ?? ""}
                      onFocus={() => selectDocModalField(c)}
                      onClick={() => selectDocModalField(c)}
                      onChange={(e) =>
                        setDocModal((m) => ({ ...m, edits: { ...m.edits, [c]: e.target.value } }))
                      }
                    />
                  </label>
                ))}
                <div className="doc-modal-submit-row">
                  <button className="btn primary" onClick={submitDocModal}>Submit</button>
                  <button className="btn ghost" onClick={closeDocModal}>Cancel</button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {errorHover && (
        <div
          className="file-box-error-tooltip"
          style={{
            display: "block",
            position: "fixed",
            left: Math.min(errorHover.x + 15, window.innerWidth - 300),
            top: Math.min(errorHover.y + 15, window.innerHeight - 80),
            bottom: "auto",
            zIndex: 9999,
          }}
        >
          {errorHover.text}
        </div>
      )}

      {settingsOpen && (
        <div className="modal-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) setSettingsOpen(false); }}>
          <div className="modal-card">
            <div className="modal-head">
              <h2>Settings</h2>
              <button className="x" onClick={() => setSettingsOpen(false)} title="Close">×</button>
            </div>

            <div className="settings-section">
              <div className="settings-section-head">
                <h3>Gemini API key</h3>
              </div>
              <p className="muted settings-hint">
                Used by the <strong>Gemini</strong> engine. Stored locally in{" "}
                <code>~/.pdfxl_config.json</code> — it never leaves this machine
                except to call Google's API. Get a key from{" "}
                <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer">
                  Google AI Studio
                </a>.
              </p>

              {geminiKeyInfo?.key_set ? (
                <div className="settings-key-current">
                  <span className="settings-key-masked">{geminiKeyInfo.masked}</span>
                  {geminiKeyInfo.source === "env" ? (
                    <span className="muted">from environment variable (remove it from your shell to change)</span>
                  ) : (
                    <button className="retry-btn" onClick={removeGeminiKey}>Remove</button>
                  )}
                </div>
              ) : (
                <div className="muted settings-key-current">No key configured.</div>
              )}

              {geminiKeyInfo?.source !== "env" && (
                <div className="gemini-key-row">
                  <input
                    className="gemini-key-input settings-key-input"
                    type="password"
                    placeholder={geminiKeyInfo?.key_set ? "Paste a new key to replace it" : "Paste Gemini API key"}
                    value={geminiKeyInput}
                    onChange={(e) => setGeminiKeyInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") saveGeminiKey(); }}
                    disabled={geminiSavingKey}
                  />
                  <button
                    className="key-save-btn"
                    onClick={saveGeminiKey}
                    disabled={geminiSavingKey || !geminiKeyInput.trim()}
                  >
                    {geminiSavingKey ? "Validating…" : "Save"}
                  </button>
                </div>
              )}
              {geminiKeyError && <div className="ollama-err">✕ {geminiKeyError}</div>}
            </div>

            <div className="settings-section">
              <div className="settings-section-head">
                <h3>Parallel requests</h3>
              </div>
              <p className="muted settings-hint">
                How many PDFs to send to Gemini at the same time. Higher values
                finish faster but are more likely to hit Gemini's rate limits.
              </p>
              <div className="gemini-key-row">
                <input
                  className="gemini-key-input settings-key-input"
                  type="number"
                  min={1}
                  max={100}
                  value={concurrency}
                  onChange={(e) => {
                    const n = parseInt(e.target.value, 10);
                    if (Number.isFinite(n)) {
                      setConcurrency(Math.min(100, Math.max(1, n)));
                    } else if (e.target.value === "") {
                      setConcurrency(1);
                    }
                  }}
                />
              </div>
            </div>

          </div>
        </div>
      )}

      {toast && <div className={"toast " + toast.kind}>{toast.msg}</div>}
    </div>
  );
}
