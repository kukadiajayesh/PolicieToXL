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
            <span className="model-kind-icon" title={selected.vision ? "Image Based" : "Text Based"}>
              {selected.vision ? "🖼" : "📝"}
            </span>
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
              <span className="model-kind-icon" title={m.vision ? "Image Based" : "Text Based"}>
                {m.vision ? "🖼" : "📝"}
              </span>
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

export default function App() {
  const [queue, setQueue] = useState([]);
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("theme") || "system"
  );
  const [engine, setEngine] = useState("regex");
  const [ollamaModels, setOllamaModels] = useState([]);
  const [ollamaModel, setOllamaModel] = useState("");
  const [ollamaStatus, setOllamaStatus] = useState(null); // null | "checking" | "ok" | "error"
  const [ollamaError, setOllamaError] = useState("");
  const [geminiModels, setGeminiModels] = useState([]);
  const [geminiModel, setGeminiModel] = useState("");
  const [geminiStatus, setGeminiStatus] = useState(null); // null | "checking" | "ok" | "no-key" | "error"
  const [geminiError, setGeminiError] = useState("");
  const [geminiEnabled, setGeminiEnabled] = useState(true);
  const [geminiEnabledSaving, setGeminiEnabledSaving] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [geminiKeyInfo, setGeminiKeyInfo] = useState(null); // {key_set, masked, source}
  const [geminiKeyInput, setGeminiKeyInput] = useState("");
  const [geminiSavingKey, setGeminiSavingKey] = useState(false);
  const [geminiKeyError, setGeminiKeyError] = useState("");
  const [claudeModels, setClaudeModels] = useState([]);
  const [claudeModel, setClaudeModel] = useState("");
  const [claudeStatus, setClaudeStatus] = useState(null); // null | "checking" | "ok" | "no-key" | "error"
  const [claudeError, setClaudeError] = useState("");
  const [claudeEnabled, setClaudeEnabled] = useState(false);
  const [claudeEnabledSaving, setClaudeEnabledSaving] = useState(false);
  const [claudeKeyInfo, setClaudeKeyInfo] = useState(null); // {key_set, masked, source}
  const [claudeKeyInput, setClaudeKeyInput] = useState("");
  const [claudeSavingKey, setClaudeSavingKey] = useState(false);
  const [claudeKeyError, setClaudeKeyError] = useState("");
  const [logs, setLogs] = useState([]);
  const [logsOpen, setLogsOpen] = useState(false);
  const [preview, setPreview] = useState(null); // {url, x, y, col, loading}
  const fileInput = useRef(null);
  const folderInput = useRef(null);
  const logsEndRef = useRef(null);
  const hoverTimer = useRef(null);

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

  const checkOllama = async ({ setDefault = false, attempts = 1 } = {}) => {
    setOllamaStatus("checking");
    setOllamaError("");
    // Ollama may still be starting up when the page loads, so a single failed
    // probe shouldn't condemn it — retry a few times before showing the error.
    for (let i = 0; i < attempts; i++) {
      try {
        const res = await fetch("/api/ollama/status");
        const data = await res.json();
        if (data.ok) {
          setOllamaModels(data.models || []);
          setOllamaModel((m) => m || pickDefaultModel(data.models));
          setOllamaStatus("ok");
          if (setDefault) setEngine("ollama");
          return;
        }
        setOllamaError(data.error || "Ollama not reachable");
      } catch {
        setOllamaError("Could not reach Ollama");
      }
      if (i < attempts - 1) await new Promise((r) => setTimeout(r, 2000));
    }
    setOllamaStatus("error");
  };

  // On mount: probe Ollama (patiently — it may still be booting) and default
  // to it if available.
  useEffect(() => { checkOllama({ setDefault: true, attempts: 5 }); }, []);

  // On mount: probe Gemini/Claude too, so their engine buttons only appear
  // once we know a valid key is configured (mirrors the Ollama probe above).
  useEffect(() => { checkGemini(); checkClaude(); }, []);

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
    if (data.enabled !== undefined) setGeminiEnabled(!!data.enabled);
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

  const applyClaudeStatus = (data) => {
    if (data.enabled !== undefined) setClaudeEnabled(!!data.enabled);
    if (data.ok) {
      setClaudeModels(data.models || []);
      setClaudeModel((m) => m || pickDefaultModel(data.models));
      setClaudeStatus("ok");
      return;
    }
    setClaudeError(data.error || "Claude not reachable");
    setClaudeStatus(data.key_set ? "error" : "no-key");
  };

  const checkClaude = async () => {
    setClaudeStatus("checking");
    setClaudeError("");
    try {
      const { data } = await fetchJson("/api/claude/status");
      applyClaudeStatus(data);
    } catch (err) {
      setClaudeError(err.message);
      setClaudeStatus("error");
    }
  };

  const openSettings = async () => {
    setSettingsOpen(true);
    setGeminiKeyError("");
    setGeminiKeyInput("");
    setClaudeKeyError("");
    setClaudeKeyInput("");
    try {
      const { data } = await fetchJson("/api/gemini/key");
      setGeminiKeyInfo(data);
    } catch (err) {
      setGeminiKeyInfo(null);
      setGeminiKeyError(err.message);
    }
    try {
      const { data } = await fetchJson("/api/claude/key");
      setClaudeKeyInfo(data);
    } catch (err) {
      setClaudeKeyInfo(null);
      setClaudeKeyError(err.message);
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

  const setGeminiEnabledRemote = async (enabled) => {
    setGeminiEnabledSaving(true);
    try {
      const { data } = await fetchJson("/api/gemini/enabled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (data.ok) setGeminiEnabled(data.enabled);
      else setGeminiKeyError(data.error || "Could not update setting");
    } catch (err) {
      setGeminiKeyError(err.message);
    } finally {
      setGeminiEnabledSaving(false);
    }
  };

  const saveClaudeKey = async () => {
    const key = claudeKeyInput.trim();
    if (!key) return;
    setClaudeSavingKey(true);
    setClaudeKeyError("");
    try {
      const { data } = await fetchJson("/api/claude/key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: key }),
      });
      if (data.ok) {
        setClaudeKeyInput("");
        setClaudeKeyInfo({ key_set: data.key_set, masked: data.masked, source: data.source });
        applyClaudeStatus(data);
        flash("Claude API key saved.", "info");
      } else {
        setClaudeKeyError(data.error || "Key was rejected");
      }
    } catch (err) {
      setClaudeKeyError(err.message);
    } finally {
      setClaudeSavingKey(false);
    }
  };

  const removeClaudeKey = async () => {
    setClaudeKeyError("");
    try {
      const { data } = await fetchJson("/api/claude/key", { method: "DELETE" });
      if (!data.ok) {
        setClaudeKeyError(data.error || "Could not remove key");
        return;
      }
      setClaudeKeyInfo({ key_set: data.key_set, masked: data.masked, source: data.source });
      // Env-var keys survive removal of the saved one, so re-probe instead of
      // assuming Claude is now unconfigured.
      setClaudeModel("");
      setClaudeModels([]);
      checkClaude();
      flash("Saved Claude API key removed.", "info");
    } catch (err) {
      setClaudeKeyError(err.message);
    }
  };

  const setClaudeEnabledRemote = async (enabled) => {
    setClaudeEnabledSaving(true);
    try {
      const { data } = await fetchJson("/api/claude/enabled", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (data.ok) setClaudeEnabled(data.enabled);
      else setClaudeKeyError(data.error || "Could not update setting");
    } catch (err) {
      setClaudeKeyError(err.message);
    } finally {
      setClaudeEnabledSaving(false);
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

  // Re-probe whenever the user switches to an engine and it isn't confirmed
  // up — including after an earlier failed check (they may have started
  // Ollama, or added a key, since). Also fall back to Regex whenever the
  // active engine's status resolves to unavailable (Ollama stopped, a
  // Gemini/Claude key was removed, or the engine was turned off in
  // Settings) so we never leave the UI on a hidden engine button.
  useEffect(() => {
    if (engine === "ollama") {
      if (ollamaStatus === "error") setEngine("regex");
      else if (ollamaStatus !== "ok" && ollamaStatus !== "checking") checkOllama({ attempts: 2 });
    }
    if (engine === "gemini") {
      if (geminiStatus === "error" || geminiStatus === "no-key" || (geminiStatus === "ok" && !geminiEnabled)) {
        setEngine("regex");
      } else if (geminiStatus !== "ok" && geminiStatus !== "checking") {
        checkGemini();
      }
    }
    if (engine === "claude") {
      if (claudeStatus === "error" || claudeStatus === "no-key" || (claudeStatus === "ok" && !claudeEnabled)) {
        setEngine("regex");
      } else if (claudeStatus !== "ok" && claudeStatus !== "checking") {
        checkClaude();
      }
    }
  }, [engine, ollamaStatus, geminiStatus, claudeStatus, geminiEnabled, claudeEnabled]);

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
  }, []);

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  const setItemStatus = (id, status, error) =>
    setQueue((q) =>
      q.map((it) => (it.id === id ? { ...it, status, error } : it))
    );

  const extractOne = async (item, orderIdx) => {
    setItemStatus(item.id, "reading");
    try {
      let res;
      const model =
        engine === "ollama" ? ollamaModel
        : engine === "gemini" ? geminiModel
        : engine === "claude" ? claudeModel
        : "";
      if (item.file) {
        const fd = new FormData();
        fd.append("file", item.file, item.name);
        fd.append("engine", engine);
        if (model) fd.append("model", model);
        res = await fetch("/api/extract", { method: "POST", body: fd });
      } else {
        res = await fetch("/api/extract", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: item.path, engine, model }),
        });
      }
      let data;
      try {
        data = await res.json();
      } catch {
        throw new Error(`Server error (HTTP ${res.status})`);
      }
      if (!res.ok) throw new Error(data.error || "Extraction failed");
      // Results can arrive out of order when extracting concurrently; keep the
      // table sorted by queue position. _qid ties the row to its queue item so
      // a retried file replaces its old row instead of duplicating it.
      const row = { ...data.row, _qidx: orderIdx, _qid: item.id };
      setRows((r) =>
        [...r.filter((x) => x._qid !== item.id), row].sort(
          (a, b) => (a._qidx ?? 0) - (b._qidx ?? 0)
        )
      );
      setItemStatus(item.id, "done");
    } catch (err) {
      setItemStatus(item.id, "error", err.message);
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
    // Regex extraction is CPU-bound in the backend, so a few PDFs in flight at
    // once overlap nicely; Ollama runs one generation at a time, keep it serial.
    // Gemini/Claude are cloud APIs — a little concurrency is fine, but stay
    // under typical rate limits.
    const limit = engine === "ollama" ? 1 : engine === "gemini" || engine === "claude" ? 2 : 3;
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

  const copyAllData = async () => {
    if (!rows.length) return flash("No results to copy.", "error");
    const tsv = [
      COLUMNS.join("\t"),
      ...rows.map((row) => COLUMNS.map((c) => String(row[c] ?? "")).join("\t")),
    ].join("\n");
    try {
      await navigator.clipboard.writeText(tsv);
      flash(`Copied ${rows.length} rows to clipboard.`, "info");
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

  const cellHoverProps = (row, col) =>
    row._doc_id && row._locations?.[col]
      ? {
          onMouseEnter: (e) => showPreview(e, row, col),
          onMouseMove: movePreview,
          onMouseLeave: hidePreview,
          onClick: (e) => {
            e.stopPropagation();
            openPdf(row._doc_id);
          },
        }
      : {};

  const openPdf = (docId) => {
    if (!docId) return;
    // Create a temporary link to trigger the PDF download/view
    // This approach is less likely to be blocked by popup blockers than window.open
    const link = document.createElement('a');
    link.href = `/api/open-pdf?doc_id=${docId}`;
    // We don't set download attribute because we want to potentially display inline
    // depending on browser capabilities and plugin/settings
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

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
            <span className="engine-label">Engine:</span>
            <div className="engine-toggle">
              <button
                className={"engine-btn" + (engine === "regex" ? " active" : "")}
                onClick={() => setEngine("regex")}
              >Regex</button>
              {ollamaStatus === "ok" && (
                <button
                  className={"engine-btn" + (engine === "ollama" ? " active" : "")}
                  onClick={() => setEngine("ollama")}
                >Ollama</button>
              )}
              {geminiStatus === "ok" && geminiEnabled && (
                <button
                  className={"engine-btn" + (engine === "gemini" ? " active" : "")}
                  onClick={() => setEngine("gemini")}
                >Gemini</button>
              )}
              {claudeStatus === "ok" && claudeEnabled && (
                <button
                  className={"engine-btn" + (engine === "claude" ? " active" : "")}
                  onClick={() => setEngine("claude")}
                >Claude</button>
              )}
            </div>
            {engine === "ollama" && (
              <div className="ollama-config">
                {ollamaStatus === "checking" && <span className="muted">Checking…</span>}
                {ollamaStatus === "error" && (
                  <span className="ollama-err" title={ollamaError}>
                    ✕ Not reachable
                    <button className="retry-btn" onClick={() => checkOllama({ attempts: 3 })}>Retry</button>
                  </span>
                )}
                {ollamaStatus === "ok" && ollamaModels.length === 0 && (
                  <span className="muted">No models installed</span>
                )}
                {ollamaStatus === "ok" && ollamaModels.length > 0 && (
                  <ModelDropdown
                    models={ollamaModels}
                    value={ollamaModel}
                    onChange={setOllamaModel}
                  />
                )}
              </div>
            )}
            {engine === "gemini" && (
              <div className="ollama-config">
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
                    <span className="muted engine-cloud-note" title="Unlike Regex/Ollama, the Gemini engine sends document contents to Google's API.">
                      ☁ sends PDFs to Google
                    </span>
                  </>
                )}
              </div>
            )}
            {engine === "claude" && (
              <div className="ollama-config">
                {claudeStatus === "checking" && <span className="muted">Checking…</span>}
                {claudeStatus === "no-key" && (
                  <span className="gemini-key-row">
                    <span className="ollama-err">✕ No API key</span>
                    <button className="key-save-btn" onClick={openSettings}>
                      ⚙ Add key in Settings
                    </button>
                  </span>
                )}
                {claudeStatus === "error" && (
                  <span className="ollama-err" title={claudeError}>
                    ✕ {claudeError || "Not reachable"}
                    <button className="retry-btn" onClick={checkClaude}>Retry</button>
                  </span>
                )}
                {claudeStatus === "ok" && (
                  <>
                    <ModelDropdown
                      models={claudeModels}
                      value={claudeModel}
                      onChange={setClaudeModel}
                    />
                    <span className="muted engine-cloud-note" title="Unlike Regex/Ollama, the Claude engine sends document contents to Anthropic's API.">
                      ☁ sends PDFs to Anthropic
                    </span>
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        <div
          className={"dropzone" + (dragging ? " active" : "")}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={(e) => { if (!e.defaultPrevented) fileInput.current?.click(); }}
        >
          <div className="dz-icon">⬆</div>
          <div className="dz-text">
            <strong>Drag &amp; drop PDFs here</strong>
            <div className="muted">or click to pick files</div>
            <button
              className="dz-folder-btn"
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); folderInput.current?.click(); }}
            >
              📁 Pick a folder
            </button>
          </div>
        </div>

        {/* hidden native pickers */}
        <input
          ref={fileInput}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
        />
        <input
          ref={folderInput}
          type="file"
          hidden
          onChange={(e) => { if (e.target.files) addFiles(e.target.files); e.target.value = ""; }}
        />

        {/* File grid */}
        {queue.length > 0 && (
          <div className="queue-row">
            <div className="file-grid">
              {queue.map((it) => (
                <div key={it.id} className={`file-box status-${it.status}`}>
                  <div className="file-box-progress-track">
                    <div
                      className={`file-box-progress${it.status === "reading" ? " indeterminate" : ""}`}
                      style={{ width: it.status === "done" ? "100%" : it.status === "reading" ? undefined : "0%" }}
                    />
                  </div>
                  <button className="file-box-x" onClick={() => removeItem(it.id)} title="Remove">×</button>
                  <div className="file-box-icon">📄</div>
                  <div className="file-box-body">
                    <div className="file-box-name" title={it.name}>{it.name}</div>
                    {it.error && (
                      <div className="file-box-error-wrap">
                        <div className="file-box-error">{it.error}</div>
                        <div className="file-box-error-tooltip">{it.error}</div>
                      </div>
                    )}
                    {it.status === "error" && (
                      <button className="retry-btn" onClick={() => setItemStatus(it.id, "pending")}>
                        Retry
                      </button>
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
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="rownum">#</th>
                  {COLUMNS.map((c) => <th key={c}>{c}</th>)}
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
                        <span className="verify-badge" title="Click to open PDF">🔍</span>
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
                            value={CAMEL_COLS.has(c) ? toTitleCase(raw) : raw}
                            onChange={(e) => editCell(i, c, e.target.value)}
                            rows={1}
                          />
                          {verifyBadge}
                        </td>
                      );
                    })}
                    <td>
                      <button className="x" onClick={() => deleteRow(i)} title="Delete row">×</button>
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
                <label
                  className="provider-toggle"
                  title={geminiEnabled ? "Hide the Gemini engine" : "Show the Gemini engine"}
                >
                  <input
                    type="checkbox"
                    checked={geminiEnabled}
                    disabled={geminiEnabledSaving || !geminiKeyInfo?.key_set}
                    onChange={(e) => setGeminiEnabledRemote(e.target.checked)}
                  />
                  <span className="provider-toggle-track"><span className="provider-toggle-thumb" /></span>
                  <span className="provider-toggle-label">{geminiEnabled ? "On" : "Off"}</span>
                </label>
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
                <h3>Claude API key</h3>
                <label
                  className="provider-toggle"
                  title={claudeEnabled ? "Hide the Claude engine" : "Show the Claude engine"}
                >
                  <input
                    type="checkbox"
                    checked={claudeEnabled}
                    disabled={claudeEnabledSaving}
                    onChange={(e) => setClaudeEnabledRemote(e.target.checked)}
                  />
                  <span className="provider-toggle-track"><span className="provider-toggle-thumb" /></span>
                  <span className="provider-toggle-label">{claudeEnabled ? "On" : "Off"}</span>
                </label>
              </div>
              <p className="muted settings-hint">
                Used by the <strong>Claude</strong> engine. Stored locally in{" "}
                <code>~/.pdfxl_config.json</code> — it never leaves this machine
                except to call Anthropic's API. Get a key from{" "}
                <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">
                  the Anthropic Console
                </a>.
              </p>

              {claudeKeyInfo?.key_set ? (
                <div className="settings-key-current">
                  <span className="settings-key-masked">{claudeKeyInfo.masked}</span>
                  {claudeKeyInfo.source === "env" ? (
                    <span className="muted">from environment variable (remove it from your shell to change)</span>
                  ) : (
                    <button className="retry-btn" onClick={removeClaudeKey}>Remove</button>
                  )}
                </div>
              ) : (
                <div className="muted settings-key-current">No key configured.</div>
              )}

              {claudeKeyInfo?.source !== "env" && (
                <div className="gemini-key-row">
                  <input
                    className="gemini-key-input settings-key-input"
                    type="password"
                    placeholder={claudeKeyInfo?.key_set ? "Paste a new key to replace it" : "Paste Claude API key"}
                    value={claudeKeyInput}
                    onChange={(e) => setClaudeKeyInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") saveClaudeKey(); }}
                    disabled={claudeSavingKey}
                  />
                  <button
                    className="key-save-btn"
                    onClick={saveClaudeKey}
                    disabled={claudeSavingKey || !claudeKeyInput.trim()}
                  >
                    {claudeSavingKey ? "Validating…" : "Save"}
                  </button>
                </div>
              )}
              {claudeKeyError && <div className="ollama-err">✕ {claudeKeyError}</div>}
            </div>
          </div>
        </div>
      )}

      {toast && <div className={"toast " + toast.kind}>{toast.msg}</div>}
    </div>
  );
}
