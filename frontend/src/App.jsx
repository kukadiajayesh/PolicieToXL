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
  // queue items: { id, name, path?, file?, status, error? }
  const [queue, setQueue] = useState([]);
  const [rows, setRows] = useState([]); // extracted rows (editable)
  const [folder, setFolder] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("theme") || "system"
  );
  const fileInput = useRef(null);
  const folderInput = useRef(null);

  // Apply the chosen theme (resolving "system" via the OS preference) and keep
  // it in sync when the OS preference changes while on system mode.
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

  // Enable folder selection on the hidden input (non-standard attributes that
  // JSX won't pass through reliably).
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

  const scanFolder = async () => {
    if (!folder.trim()) return flash("Enter a folder path first.", "error");
    setBusy(true);
    try {
      const res = await fetch("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ folder }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Scan failed");
      if (!data.files.length) {
        flash("No PDFs found in that folder.", "error");
      } else {
        setQueue((q) => [
          ...q,
          ...data.files.map((f) => ({
            id: uid(),
            name: f.name,
            path: f.path,
            status: "pending",
          })),
        ]);
        flash(`Found ${data.files.length} PDF(s).`, "info");
      }
    } catch (err) {
      flash(err.message, "error");
    } finally {
      setBusy(false);
    }
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
        res = await fetch("/api/extract", { method: "POST", body: fd });
      } else {
        res = await fetch("/api/extract", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: item.path }),
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
    setRows([]); // fresh run
    // reset any prior done/error back so the table matches the queue
    setQueue((q) =>
      q.map((it) => (it.status === "done" || it.status === "error" ? { ...it, status: "pending", error: undefined } : it))
    );
    // process sequentially so the user sees live progress
    for (const item of queue) {
      // re-read latest pending list each loop is overkill; just process all
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
        body: JSON.stringify({ rows }), // no path → stream download
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
          <div className="logo">📄→📊</div>
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

      <section className="grid">
        {/* Input card */}
        <div className="card">
          <h2>1 · Add policy PDFs</h2>

          <label className="field-label">Browse your computer</label>
          <div className="row gap-sm">
            <button
              className="btn"
              onClick={() => folderInput.current?.click()}
              disabled={busy}
            >
              📁 Browse folder
            </button>
            <button
              className="btn"
              onClick={() => fileInput.current?.click()}
              disabled={busy}
            >
              📄 Browse files
            </button>
          </div>

          <div
            className={"dropzone" + (dragging ? " active" : "")}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => fileInput.current?.click()}
          >
            <div className="dz-icon">⬆</div>
            <div>
              <strong>Drag &amp; drop PDFs here</strong>
              <div className="muted">or use the buttons above</div>
            </div>
          </div>

          {/* hidden native pickers */}
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <input
            ref={folderInput}
            type="file"
            hidden
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />

          <div className="or">or enter a folder path</div>

          <div className="row">
            <input
              className="text-input"
              placeholder="/path/to/folder_of_pdfs"
              value={folder}
              onChange={(e) => setFolder(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && scanFolder()}
            />
            <button className="btn" onClick={scanFolder} disabled={busy}>
              Scan
            </button>
          </div>
        </div>

        {/* Queue card */}
        <div className="card">
          <div className="card-head">
            <h2>2 · Queue</h2>
            <div className="mini-stats">
              <span className="badge pending">{counts.pending} pending</span>
              <span className="badge done">{counts.done} done</span>
              {counts.error > 0 && (
                <span className="badge error">{counts.error} error</span>
              )}
            </div>
          </div>

          {queue.length === 0 ? (
            <div className="empty">No files yet. Add some PDFs to begin.</div>
          ) : (
            <ul className="queue">
              {queue.map((it) => (
                <li key={it.id}>
                  <span className="fname" title={it.path || it.name}>
                    {it.name}
                  </span>
                  <span className={STATUS[it.status].cls}>
                    {STATUS[it.status].label}
                  </span>
                  {it.error && <span className="err-msg">{it.error}</span>}
                  <button
                    className="x"
                    onClick={() => removeItem(it.id)}
                    title="Remove"
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="row gap">
            <button className="btn primary" onClick={runAll} disabled={busy || !queue.length}>
              {busy ? "Processing…" : "Extract all"}
            </button>
            <button className="btn ghost" onClick={clearAll} disabled={busy || !queue.length}>
              Clear
            </button>
          </div>
        </div>
      </section>

      {/* Results */}
      <section className="card results">
        <div className="card-head">
          <h2>3 · Results {rows.length > 0 && <span className="count">({rows.length})</span>}</h2>
          <div className="row">
            <input
              className="text-input"
              placeholder="Output path e.g. /path/to/policies.xlsx (blank = download)"
              value={outputPath}
              onChange={(e) => setOutputPath(e.target.value)}
              style={{ minWidth: 320 }}
            />
            <button className="btn" onClick={saveToDisk} disabled={busy || !rows.length}>
              Save to disk
            </button>
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
                  {COLUMNS.map((c) => (
                    <th key={c}>{c}</th>
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
                      if (AMOUNT_COLS.has(c)) {
                        return (
                          <td key={c} className="col-amount">
                            <input
                              className="cell cell-amount"
                              value={formatAmount(raw)}
                              onChange={(e) => editCell(i, c, e.target.value)}
                            />
                          </td>
                        );
                      }
                      if (DATE_COLS.has(c)) {
                        return (
                          <td key={c} className="col-date">
                            <input
                              className="cell cell-date"
                              value={formatDate(raw)}
                              onChange={(e) => editCell(i, c, e.target.value)}
                            />
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
                      <button className="x" onClick={() => deleteRow(i)} title="Delete row">
                        ×
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {toast && <div className={"toast " + toast.kind}>{toast.msg}</div>}
    </div>
  );
}
