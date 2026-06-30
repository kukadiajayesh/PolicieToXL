import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

const AMOUNT_COLS = new Set(["Premium"]);
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

const THEME_ORDER = ["system", "light", "dark"];
const THEME_META = {
  system: { icon: "🖥", label: "System" },
  light: { icon: "☀", label: "Light" },
  dark: { icon: "🌙", label: "Dark" },
};

export default function App() {
  const [queue, setQueue] = useState([]);
  const [rows, setRows] = useState([]);
  const [outputPath, setOutputPath] = useState("");
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
  const [logs, setLogs] = useState([]);
  const [logsOpen, setLogsOpen] = useState(false);
  const fileInput = useRef(null);
  const folderInput = useRef(null);
  const logsEndRef = useRef(null);

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

  const checkOllama = async ({ setDefault = false } = {}) => {
    setOllamaStatus("checking");
    setOllamaError("");
    try {
      const res = await fetch("/api/ollama/status");
      const data = await res.json();
      if (data.ok) {
        setOllamaModels(data.models || []);
        setOllamaModel((m) => m || data.models?.[0] || "");
        setOllamaStatus("ok");
        if (setDefault) setEngine("ollama");
      } else {
        setOllamaStatus("error");
        setOllamaError(data.error || "Ollama not reachable");
      }
    } catch {
      setOllamaStatus("error");
      setOllamaError("Could not reach Ollama");
    }
  };

  // On mount: probe Ollama and default to it if available.
  useEffect(() => { checkOllama({ setDefault: true }); }, []);

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

  useEffect(() => {
    if (engine === "ollama" && ollamaStatus === null) checkOllama();
  }, [engine]);

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

  const extractOne = async (item) => {
    setItemStatus(item.id, "reading");
    try {
      let res;
      if (item.file) {
        const fd = new FormData();
        fd.append("file", item.file, item.name);
        fd.append("engine", engine);
        if (engine === "ollama") fd.append("model", ollamaModel);
        res = await fetch("/api/extract", { method: "POST", body: fd });
      } else {
        res = await fetch("/api/extract", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: item.path, engine, model: engine === "ollama" ? ollamaModel : "" }),
        });
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Extraction failed");
      setRows((r) => [...r, data.row]);
      setItemStatus(item.id, "done");
    } catch (err) {
      setItemStatus(item.id, "error", err.message);
    }
  };

  const runAll = async () => {
    const pending = queue.filter((it) => it.status === "pending");
    if (!pending.length) return flash("Nothing pending to process.", "error");
    setBusy(true);
    setRows([]);
    setQueue((q) =>
      q.map((it) => (it.status === "done" || it.status === "error" ? { ...it, status: "pending", error: undefined } : it))
    );
    for (const item of queue) {
      await extractOne(item);
    }
    setBusy(false);
    flash("Done processing.", "info");
  };

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

  const deleteRow = (rowIdx) =>
    setRows((r) => r.filter((_, i) => i !== rowIdx));

  const pickOutputPath = async () => {
    try {
      const res = await fetch("/api/pick_output", { method: "POST" });
      const data = await res.json();
      if (data.path) setOutputPath(data.path);
    } catch {
      flash("Could not open file picker.", "error");
    }
  };

  const saveToDisk = async () => {
    if (!rows.length) return flash("No results to export.", "error");
    setBusy(true);
    try {
      const res = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows, output_path: outputPath }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Export failed");
      flash(`Saved ${data.rows} rows → ${data.saved}`, "info");
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const downloadExcel = async () => {
    if (!rows.length) return flash("No results to export.", "error");
    setBusy(true);
    try {
      const res = await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows }),
      });
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "Export failed");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "policies.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setBusy(false);
    }
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
              <button
                className={"engine-btn" + (engine === "ollama" ? " active" : "")}
                onClick={() => setEngine("ollama")}
              >Ollama</button>
            </div>
            {engine === "ollama" && (
              <div className="ollama-config">
                {ollamaStatus === "checking" && <span className="muted">Checking…</span>}
                {ollamaStatus === "error" && (
                  <span className="ollama-err" title={ollamaError}>
                    ✕ Not reachable
                    <button className="retry-btn" onClick={checkOllama}>Retry</button>
                  </span>
                )}
                {ollamaStatus === "ok" && ollamaModels.length === 0 && (
                  <span className="muted">No models installed</span>
                )}
                {ollamaStatus === "ok" && ollamaModels.length > 0 && (
                  <select
                    className="model-select"
                    value={ollamaModel}
                    onChange={(e) => setOllamaModel(e.target.value)}
                  >
                    {ollamaModels.map((m) => <option key={m} value={m}>{m}</option>)}
                  </select>
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
                <div className="file-box-name" title={it.name}>{it.name}</div>
                <span className={`${STATUS[it.status].cls} file-status-badge`}>
                  {STATUS[it.status].label}
                </span>
                {it.error && <div className="file-box-error" title={it.error}>{it.error}</div>}
              </div>
            ))}
          </div>
        )}

        {queue.length > 0 && (
          <div className="row gap queue-actions">
            <div className="mini-stats">
              <span className="badge pending">{counts.pending} pending</span>
              <span className="badge done">{counts.done} done</span>
              {counts.error > 0 && <span className="badge error">{counts.error} error</span>}
            </div>
            <div className="row" style={{ marginLeft: "auto" }}>
              <button className="btn primary" onClick={runAll} disabled={busy || !queue.length}>
                {busy ? "Processing…" : "Extract all"}
              </button>
              <button className="btn ghost" onClick={clearAll} disabled={busy || !queue.length}>
                Clear
              </button>
            </div>
          </div>
        )}
      </section>

      {/* Results */}
      <section className="card results">
        <div className="card-head">
          <h2>2 · Results {rows.length > 0 && <span className="count">({rows.length})</span>}</h2>
          <div className="row output-row">
            <button className="btn" onClick={pickOutputPath} disabled={busy}>
              📁 Choose output
            </button>
            <span className="output-path-display" title={outputPath}>
              {outputPath || <span className="muted">No path chosen — will download</span>}
            </span>
            {outputPath && (
              <button className="btn" onClick={saveToDisk} disabled={busy || !rows.length}>
                Save to disk
              </button>
            )}
            <button className="btn primary" onClick={downloadExcel} disabled={busy || !rows.length}>
              Download .xlsx
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
                      if (AMOUNT_COLS.has(c)) {
                        return (
                          <td key={c} className="col-amount">
                            <input className="cell cell-amount" value={formatAmount(raw)} onChange={(e) => editCell(i, c, e.target.value)} />
                          </td>
                        );
                      }
                      if (DATE_COLS.has(c)) {
                        return (
                          <td key={c} className="col-date">
                            <input className="cell cell-date" value={formatDate(raw)} onChange={(e) => editCell(i, c, e.target.value)} />
                          </td>
                        );
                      }
                      return (
                        <td key={c}>
                          <textarea
                            className="cell"
                            value={CAMEL_COLS.has(c) ? toTitleCase(raw) : raw}
                            onChange={(e) => editCell(i, c, e.target.value)}
                            rows={1}
                          />
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

      {toast && <div className={"toast " + toast.kind}>{toast.msg}</div>}
    </div>
  );
}
