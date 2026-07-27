# .NET Framework 4.8 (WPF) Port Plan — Windows 7 SP1+ Support

This document is the implementation plan for porting pdf_xl from its current
Python (Flask) + React stack to a native .NET Framework 4.8 WPF desktop app,
so it runs natively on Windows 7 SP1 and later. It's written to be picked up
and executed from a Windows machine (the current authoring environment is
macOS with no .NET SDK or Windows 7 VM available, so no code has been
written yet — this is the full plan only).

## Context: why this port, and what it replaces

The app **already runs on Windows 7 today**, via Python 3.8 (frozen with
PyInstaller) + a bundled VC++ redistributable + a pinned `pypdfium2==3.21.0`
build. Commit `f2c51ee` deliberately removed a native webview
(pywebview/WebView2) in favor of "Flask server + open in the user's own
browser," specifically because WebView2 isn't reliably available on Windows
7. This works, but `PACKAGING.md` flags it as fragile and warns against ever
bumping the pinned Python version — it's a maintenance-drift risk, not a
stable foundation.

This port replaces that whole stack with a native WPF app: no Python
interpreter to freeze, no browser dependency, no HTTP server at all — the UI
calls the extraction/PDF logic directly, in-process.

**Decisions already made** (do not re-litigate these without a reason):
- **UI framework: WPF**, not WinForms — better fit for the app's theming,
  popups, and data-bound editable grid.
- **LLM scope: Gemini only**, matching current code. Ollama and
  Claude/Anthropic were already fully removed from this codebase in an
  earlier commit (`677b244`) and are explicitly out of scope for this port.
- **API surface: only what the current UI actually uses.** The current
  Flask backend has endpoints (`/api/scan`, `/api/export`, `/api/open-pdf`,
  `/api/pick_output`) that the live React UI never calls — confirmed dead
  code. Do not port them.
- **Architecture: fully native, in-process.** No embedded HTTP server
  (no ASP.NET Core/Kestrel). WPF view models call C# service classes
  directly. This also permanently avoids ever reintroducing a
  WebView2-style Windows 7 risk.

**Open product question, not yet decided — surface it, don't assume:**
the current repo also builds macOS (`packaging/macos/make_dmg.sh`) and Linux
(`packaging/linux/make_appimage.sh`) artifacts. .NET Framework is
Windows-only, so this port necessarily drops macOS/Linux distribution unless
a separate Python build is kept alive for those platforms indefinitely.

## What's being replaced (source mapping)

| Current file | Role | Replaced by |
|---|---|---|
| `app.py` (655 lines, Flask) | HTTP routes, SSE log stream, macOS-only Keychain/AppleScript code (irrelevant here), doc registry, page-render cache | `PdfXl.Core` services called directly from WPF view models |
| `extract_policies.py` (594 lines) | pdfplumber text/word-box extraction, pypdfium2 page rendering, Gemini REST calls, field normalization, field-location search for hover-preview | `PdfXl.Core/Extraction/*` |
| `frontend/src/App.jsx` (943-line single React component) | Topbar, drag-drop intake w/ 2-worker concurrency + model-fallback retry, editable results grid (currency/date formatting, CSV-to-clipboard), collapsible log panel, hover PDF preview popover, Settings modal, toasts, light/dark/system theme | `PdfXl.App` WPF views/view models |
| `packaging/windows/installer.iss` + `.github/workflows/build.yml` | Inno Setup installer (`MinVersion=6.1sp1`) bundling `vc_redist.x64.exe`, built by a Python-3.8-pinned CI job | Same Inno Setup script, adapted; Windows-only CI job, no Python pin |

None of this is a line-by-line translation — it's a from-scratch native
implementation reproducing the same behavior, informed by reading the
current implementation closely (file:line references below point at the
current Python/JS code to consult while implementing).

## Solution / project structure

```
PdfXl.sln
src/
  PdfXl.Core/                 (class library, NO WPF references — must build/test headless)
    Extraction/
      PdfTextExtractor.cs      // PdfPig: per-page text + word boxes
                                //   replaces extract_policies.py: read_document() (~L218-245), read_text()
      PdfPageRenderer.cs       // pdfium wrapper: page -> bitmap
                                //   replaces extract_policies.py: pdf_pages_to_b64() (~L177, ~L322-348)
      GeminiClient.cs          // HttpClient REST calls (text + vision variants)
                                //   replaces extract_policies.py: _gemini_generate() (~L253-312),
                                //   extract_fields_gemini(), extract_fields_gemini_vision()
      GeminiModelProbe.cs      // parallel model probing + status/recommendation
                                //   replaces extract_policies.py: gemini_status() (~L396-459),
                                //   _gemini_usable(), _recommended_gemini()
      ExtractionService.cs     // text-vs-vision routing orchestration
                                //   replaces app.py: _do_extract()/_extract_one() (~L377-393),
                                //   extract_policies.py: _is_text_poor() (~L110-112, threshold 200 chars)
      FieldNormalizer.cs       // JSON parsing/coercion into the canonical 10-field row
                                //   replaces extract_policies.py: _parse_llm_json(), _normalize_llm_fields() (~L131-167)
      FieldLocator.cs          // bounding-box search for hover-preview
                                //   replaces extract_policies.py: locate_fields() (~L470-543),
                                //   _locate_in_pages(), _norm_token()
      PreviewRenderer.cs       // crop + highlight rectangle, PDF-point coords, top-left origin
                                //   replaces app.py: _render_page() (~L274, @lru_cache(maxsize=8)),
                                //   _render_crop() (~L280-315)
      DocRegistry.cs           // in-memory doc_id -> file path, FIFO cap 500
                                //   replaces app.py: _register_doc(), _DOC_REGISTRY (~L113-144)
      Models/
        ExtractedRow.cs        // Party Name, Insurance Company, Policy No., Reg Number,
                                // Type of Insurance, Premium (Without GST), Premium,
                                // Date Start, End Date, NCB, SourceFile
        FieldLocation.cs       // page, x0, top, x1, bottom
        GeminiModelInfo.cs
    Settings/
      ApiKeyStore.cs           // DPAPI-backed secure storage
                                //   replaces app.py: _keychain_get/_set (~L173-202, macOS-only today),
                                //   _config_read/_write_key, _load_saved_key, _save_key,
                                //   _gemini_key/_gemini_key_info (~L232-271, env-var precedence)
      AppSettings.cs           // theme preference persistence
    Logging/
      LogSink.cs, LogEntry.cs  // bounded in-process log event source (cap 200)
                                //   replaces app.py: _UILogHandler (~L49-58),
                                //   deque(maxlen=200) + per-client queue.Queue fan-out (~L44-58)
  PdfXl.App/                  (WPF executable, net48)
    App.xaml / App.xaml.cs     // sets ServicePointManager.SecurityProtocol (TLS1.2) at startup
    app.manifest                // dpiAware=true (not PerMonitorV2), Win7 supportedOS GUID
    Views/
      MainWindow.xaml/.cs
      SettingsDialog.xaml/.cs
      PreviewPopup.xaml/.cs
    ViewModels/
      MainViewModel.cs          // SemaphoreSlim(2)-gated extraction pipeline + model-fallback retry
      FileQueueItemViewModel.cs
      ResultRowViewModel.cs
      SettingsViewModel.cs
      LogPanelViewModel.cs
    Converters/
      CurrencyConverter.cs      // ₹ formatting/parsing
      DateFormatConverter.cs    // multi-format date parse/reformat
    Themes/
      Base.xaml / Light.xaml / Dark.xaml
    Infrastructure/
      RelayCommand.cs, ViewModelBase.cs   // ~40 lines total, hand-rolled MVVM, no framework needed
      ClipboardCsvWriter.cs               // RFC4180 CSV, not TSV — matches current app.jsx behavior
tests/
  PdfXl.Core.Tests/           // validate against PDFs/ sample files, compare to current Python output
```

**Project format:** SDK-style `.csproj` (`<TargetFramework>net48</TargetFramework>`,
`<UseWPF>true</UseWPF>` for the App project) — modern tooling, still compiles
against .NET Framework 4.8, no functional difference to the shipped app.

**MVVM approach:** hand-rolled `ViewModelBase`/`RelayCommand` (~40 lines,
no NuGet dependency) — this app is modest enough (one main window, one
dialog, one popup) that a full MVVM framework (Prism, MVVM Light) adds
machinery with no payoff. Only pull in `CommunityToolkit.Mvvm` if
hand-rolled boilerplate becomes genuinely painful during Phase 2.

## NuGet / library choices

| Concern | Package | Why |
|---|---|---|
| PDF text + word bounding boxes | **PdfPig** (`UglyToad.PdfPig`, ~0.1.9) | Pure managed .NET, Apache 2.0, no native DLL. `Page.GetWords()` gives per-word `BoundingBox` in PDF-point coords — direct pdfplumber replacement, close enough to port `locate_fields` logic directly. |
| PDF page → image rendering | **PdfiumViewer** (`PdfiumViewer`, ~2.13.0) + a native binary package (e.g. `PdfiumViewer.Native.x86_64.v8-xfa`) | **Primary candidate, unverified — see Risk section below.** Chosen because it's an old (~2018) prebuilt native binary, similar vintage to the `pypdfium2==3.21.0` pin already proven to work on Windows 7/8/8.1. Only `PdfDocument.Render(...)` is needed, no WinForms control. Fallbacks if Win7 validation fails: `Docnet.Core` (MIT, newer bundled PDFium build ~5445, higher Win7 risk — worth a quick empirical try since it's low-cost), Patagames Pdfium.Net SDK (commercial, explicitly documents Windows XP/Vista/7/8/8.1/10/11 support — use as a paid fallback if free options fail), or direct P/Invoke against an old standalone `pdfium.dll` sourced from `bblanchon/pdfium-binaries`'s older tagged releases (most control, most effort, guaranteed-compatible vintage). |
| Gemini HTTP calls | `System.Net.Http.HttpClient` (built into .NET Framework 4.8, no NuGet) | Must explicitly set `ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12 \| SecurityProtocolType.Tls11` at app startup — Windows 7 SP1 does not negotiate TLS 1.2 by default at the Schannel level (see Win7 checklist). |
| JSON parsing | **Newtonsoft.Json** (13.0.3) | MIT, standard on .NET Framework, targets `net45`+. `System.Text.Json` is avoidable friction on Framework — no benefit here. |
| Secure API key storage | `System.Security.Cryptography.ProtectedData` — **in-box** on .NET Framework 4.8, just add a `<Reference Include="System.Security" />`, no NuGet package needed (the NuGet package of the same name is only for backporting to .NET Core/Standard, not needed here) | DPAPI-encrypted file under `%LOCALAPPDATA%\PdfXl\config.dat` — a genuine security upgrade over the current cross-platform fallback (plaintext JSON + best-effort chmod on non-macOS, which is what Windows uses today). |
| xlsx export | none | Out of scope (export endpoint unused by current UI). "Copy as CSV" needs only a hand-written RFC4180 CSV escaper. |

## Backend responsibility → in-process service mapping

| Current Flask endpoint | Behavior | C# replacement |
|---|---|---|
| `GET /api/gemini/status` | Lists usable Gemini models (version ≥2.5, text→JSON only), probes each with a 1-token dummy call via `ThreadPoolExecutor(max_workers=10)`, recommends a flash model | `GeminiModelProbe.GetStatusAsync()` — `SemaphoreSlim(10)`-gated parallel `Task.WhenAll` over `HttpClient.PostAsync` probes, bound directly into view models, no serialization boundary |
| `GET/POST/DELETE /api/gemini/key` | Env var (`GEMINI_API_KEY`/`GOOGLE_API_KEY`) precedence over saved key; masked display; Keychain (mac) / plaintext file fallback | `ApiKeyStore.GetKeyInfo()` / `SaveKey(string)` / `DeleteKey()` — same env var precedence order, DPAPI storage, validation via `GeminiModelProbe` |
| `POST /api/extract` | Text-vs-vision routing based on `_is_text_poor` (<200 chars), raw-PDF-bytes shortcut if ≤20MB else render ≤2 pages | `ExtractionService.ExtractAsync(path, model)` — `PdfTextExtractor` → routing → `GeminiClient.ExtractTextAsync` or `PdfPageRenderer` + `GeminiClient.ExtractVisionAsync`. Returns `ExtractedRow` directly; no upload/temp-copy step since the WPF app already has a real on-disk path (drag-drop/file-picker) |
| `GET /api/preview` | Zoomed/highlighted crop PNG via `doc_id`/page/bbox, 8-entry LRU page cache, FIFO-capped doc registry (500) | `PreviewRenderer.RenderCrop(docId, page, bbox)` — `DocRegistry` (same FIFO cap 500), 8-entry bounded page-render cache (`System.Runtime.Caching.MemoryCache` or manual LRU), highlight box via `System.Drawing.Graphics.DrawRectangle` (closest 1:1 port of the current Pillow crop+highlight code), result bound directly to an `Image` control — no HTTP round-trip |
| `GET /api/logs` (SSE) | `deque(maxlen=200)` + per-client `queue.Queue` fan-out | `LogSink` — bounded `ObservableCollection<LogEntry>` (cap 200) + plain C# event, subscribed directly by `LogPanelViewModel`. No polling/fan-out needed for a single in-process UI client |
| — (client-side, App.jsx) | 2-worker concurrent extraction + per-file model-fallback retry on quota/rate-limit/unknown-model errors | `SemaphoreSlim(2)`-gated `Task`-based pipeline in `MainViewModel`, retry loop advances through `GeminiModelProbe` results on failure |

**Explicitly not ported:** `/api/scan`, `/api/export`, `/api/open-pdf`,
`/api/pick_output` — confirmed unused by the current UI.

## UI mapping (7 screens → WPF controls)

1. **Topbar** — `DockPanel`: title, theme selector bound to
   `AppSettings.Theme`, Settings button (`SettingsDialog.ShowDialog()`),
   static "Local only" indicator (now literally always true).
2. **PDF intake** — `Border` with native WPF `AllowDrop`/`Drop`/`DragOver`;
   `Microsoft.Win32.OpenFileDialog` (multi-select) + WinForms
   `FolderBrowserDialog` interop for folder-pick; `ItemsControl` file queue
   bound to `ObservableCollection<FileQueueItemViewModel>`, `DataTemplate`
   per item with status-triggered badge `Style`s (Pending/Reading/Done/Error
   enum + `DataTrigger`), shimmer via `Storyboard`/`DoubleAnimation` or
   `ProgressBar IsIndeterminate="True"` for "reading", Retry/Copy-error
   buttons visible only in Error state.
3. **Editable results grid** — `System.Windows.Controls.DataGrid` (built
   into `PresentationFramework`) bound to
   `ObservableCollection<ResultRowViewModel>`; 10 field columns + Source
   File as `DataGridTextColumn`s with `CurrencyConverter`/
   `DateFormatConverter` `IValueConverter`s; built-in in-place editing
   (`IsReadOnly="False"`); row-delete via `DataGridTemplateColumn` button
   with linked queue-item cleanup; toolbar "Copy as CSV" using
   `ClipboardCsvWriter` (proper comma/quote/newline escaping, matching the
   current CSV — not TSV — behavior from commit `c1d50b2`).
4. **Log panel** — collapsible `Expander`/`GridSplitter` panel, `ItemsControl`
   bound to `LogSink`, auto-scroll on new entries when open (gate on an
   `IsOpen` flag so it doesn't fight user scroll).
5. **Hover/on-demand preview** — `Popup` anchored to the grid cell (simpler
   than an `Adorner`), `PlacementTarget` = the cell; trigger via
   `MouseEnter` + `DispatcherTimer` debounce, or a per-row "eye" button
   (more desktop-idiomatic, avoids accidental-preview-storm while
   dragging); `Image` bound to a synchronously-produced `BitmapSource`
   from `PreviewRenderer`.
6. **Settings modal** — `SettingsDialog` window: masked key display,
   Save/Validate/Remove buttons, env-var-precedence banner with input
   disabled when `ApiKeyStore.GetKeyInfo().Source == KeySource.EnvironmentVariable`.
   Note: `PasswordBox.Password` isn't natively bindable in WPF — needs a
   small attached-property helper or explicit code-behind read on Save.
7. **Toast notifications** — `ItemsControl` of `Border`s in a corner
   `Grid`, `ObservableCollection<ToastViewModel>`, `DispatcherTimer`
   auto-remove, `Storyboard` fade-in/out. No external toast package.

**Theming:** `ResourceDictionary`-based (`Base.xaml` shared styles +
`Light.xaml`/`Dark.xaml` brush overrides), merged into
`Application.Resources.MergedDictionaries` and swapped at runtime. "System"
theme reads `HKCU\...\Personalize\AppsUseLightTheme`, which **does not
exist pre-Windows-10** — System mode must gracefully fall back to Light on
Windows 7 (document this as an explicit, intentional behavior difference
from the web app's `prefers-color-scheme`, which also has no meaningful
Win7 signal).

## Windows 7 SP1 compatibility checklist

- **TFM:** `net48`. Microsoft's own .NET Framework 4.8 system requirements
  cover Windows 7 SP1 / Server 2008 R2 SP1.
- **Prerequisite OS updates** (parallel to today's VC++ redist bundling):
  - Servicing stack update **KB3020369** — needed before 4.8 installs
    cleanly on an unpatched image.
  - Current **Microsoft Root Certificate Authority 2011** update — needed
    for offline .NET 4.8 installer signature validation.
  - The **.NET Framework 4.8 offline installer** itself
    (`ndp48-x86-x64-allos-enu.exe`, ~120MB) — bundle it in the Inno Setup
    installer the same way `vc_redist.x64.exe` is bundled today, with a
    skip-if-already-present check reading
    `HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full\Release` and
    comparing against the documented ≥528040 threshold for 4.8, mirroring
    the existing `VCRedistNeedsInstall` pattern in `installer.iss`.
- **TLS 1.2 — a real, new gotcha, not present in the Python build:**
  Windows 7 SP1 does not enable TLS 1.1/1.2 in Schannel by default.
  - OS layer: needs the **KB3140245**-era update plus a registry fix
    under `HKLM\SYSTEM\CurrentControlSet\Control\SecurityProviders\SCHANNEL\Protocols\TLS 1.2`.
    The installer should apply this (with an elevation prompt) when it
    detects Windows 7, or the app should detect a failed handshake and
    show a friendly message pointing at the fix.
  - App layer: set `ServicePointManager.SecurityProtocol =
    SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11` explicitly at
    startup in `App.xaml.cs` — .NET 4.8's `SystemDefault` is fine *only if*
    the OS-level fix is applied.
- **DPI:** in `app.manifest`, use classic `<dpiAware>true</dpiAware>`
  (system-DPI-aware). Do **not** request `PerMonitorV2` — it requires
  Windows 10 1607+ and can cause manifest-parsing issues on Win7.
- **`app.manifest` `<supportedOS>`:** explicitly include the Windows 7 GUID
  (`{35138b9a-5d96-4fbd-8e2d-a2440225f93a}`) — without it, some shell/
  common-dialog behavior silently degrades to Vista-compat mode.
- **APIs to avoid entirely:** `WebView2`/`Microsoft.Web.WebView2` (hard
  constraint — this is exactly what the Python build removed and why),
  `Windows.UI.*`/WinRT interop, `System.Runtime.InteropServices.WindowsRuntime`,
  `Microsoft.Toolkit.Win32.UI.Controls`. Safe/fine on Win7:
  `System.Runtime.Caching.MemoryCache`, `HttpClient`, `System.Drawing`,
  `Microsoft.Win32.OpenFileDialog`, WinForms `FolderBrowserDialog` interop.
- **Architecture:** match the current installer's
  `ArchitecturesInstallIn64BitMode=x64` — build as `AnyCPU` or explicit
  `x64` consistent with whichever native pdfium DLL bitness is bundled; no
  cross-bitness P/Invoke.
- **Validate on a real Windows 7 SP1 VM**, not just version flags — this
  project's own history (the `pypdfium2` pin, the VC++ redist requirement)
  shows library-doc compatibility claims are not reliable without
  hands-on testing.

## Packaging

Adapt `packaging/windows/installer.iss` directly rather than starting over:
- Keep `MinVersion=6.1sp1`, `ArchitecturesInstallIn64BitMode=x64`, the
  desktop-icon task, Start Menu group, and uninstaller config unchanged.
- Replace the PyInstaller onefolder `[Files]` source (`dist\InsurancePolicyExtractor`)
  with the `dotnet publish` (framework-dependent, `-p:SelfContained=false`)
  output — `PdfXl.App.exe` + managed DLLs + the native pdfium DLL (verify
  at implementation time whether the pdfium NuGet package's `.targets` file
  places the native DLL next to the exe or under `runtimes\win-x64\native\`
  — this has been flagged as sometimes unreliable by wrapper-library docs).
- Replace the `vc_redist.x64.exe` conditional-bundle `[Code]` block with an
  equivalent block for `ndp48-x86-x64-allos-enu.exe`, using a
  `Net48NeedsInstall` check function analogous to the existing
  `VCRedistNeedsInstall`.
- Add a TLS-1.2 registry-enablement `[Code]` step, gated on detected
  Windows 7 (`GetWindowsVersion` check already used for `MinVersion`
  logic can be extended).
- **CI (`.github/workflows/build.yml`):** simplifies to a **Windows-only**
  job — drop the Python 3.8 pin, drop the PyInstaller step, drop
  `pip install`. Whether to keep the macOS/Linux jobs building the *old*
  Python app in parallel (for as long as that platform support is still
  wanted) is the open product question flagged above — don't silently
  delete those jobs without confirming.

## PDFium-on-Windows-7 risk (biggest unknown in this port)

The Python build had to pin `pypdfium2==3.21.0` specifically because newer
PDFium builds dropped Windows 7/8/8.1 support (compiled against a newer
Windows-10-baseline toolchain). **The same risk applies to every .NET
PDFium wrapper**, because they all embed a prebuilt native `pdfium.dll` —
the C# wrapper is irrelevant to Win7 compatibility; only the native
binary's own build baseline matters.

Resolution path, in order:
1. Try `PdfiumViewer` + its ~2018-vintage native binary package first
   (see library table above) — chosen for its age, not despite it.
2. If that fails on a real Win7 SP1 VM, try `Docnet.Core` (low-cost test,
   though its bundled PDFium is much newer and thus higher-risk).
3. If both fail, fall back to the commercial Patagames Pdfium.Net SDK,
   which explicitly documents Windows 7 support in its current system
   requirements.
4. Last resort: source an old standalone `pdfium.dll` (e.g. from
   `bblanchon/pdfium-binaries`'s older tagged releases, or a build
   contemporary with `pypdfium2==3.21.0`) and P/Invoke directly, bypassing
   any wrapper's bundled binary.

**Do a Phase 0 spike before committing further** — this needs an actual
Windows 7 SP1 VM (not available in the environment this plan was written
in). Load each free candidate's native DLL and render one page from a
sample in `PDFs/`; lock in the choice before Phase 1 architecture assumes
a specific one.

## Phase breakdown / milestones

**Phase 0 — Win7/PDFium spike (do first, requires a Windows 7 SP1 VM)**
- Confirm .NET Framework 4.8 installs cleanly with the documented
  prerequisite KBs (KB3020369, root CA update).
- Confirm a chosen pdfium wrapper's native DLL loads and renders a page
  from a `PDFs/` sample in a trivial console app; fall back through the
  candidate list above if it fails.
- Confirm a `HttpClient` TLS 1.2 handshake to
  `generativelanguage.googleapis.com` succeeds, pre- and post- the
  registry fix.
- Output: locked-in pdfium library choice + confirmed prerequisite KB list.

**Phase 1 — Core extraction pipeline (headless, no XAML)**
- Build all of `PdfXl.Core` per the class list above.
- Validate field-for-field against the current Python app's output for
  the sample PDFs already in `PDFs/`, via `PdfXl.Core.Tests` and/or a
  console harness.
- Milestone: can extract all 10 fields + locate bounding boxes + render a
  preview crop from the command line.

**Phase 2 — WPF shell + intake + results grid**
- `PdfXl.App` scaffold, drag-drop + file/folder picker, file queue with
  status badges, 2-worker concurrent extraction with model-fallback
  retry, `DataGrid` results with currency/date converters, row delete,
  CSV-to-clipboard.
- Milestone: usable end-to-end app (drop PDFs → editable grid → copy CSV).

**Phase 3 — Preview, settings, logging, theming**
- Hover/on-demand preview popup, Settings dialog + key management, log
  panel, light/dark/system theming with Win7 fallback, toasts.
- Milestone: feature parity with the current React UI's 7 screens.

**Phase 4 — Packaging & Windows 7 validation (requires a Win7 SP1 VM)**
- `dotnet publish` framework-dependent build, adapt
  `packaging/windows/installer.iss`, trim CI to Windows-only.
- Full manual pass on a clean Windows 7 SP1 image: install → launch →
  extract → preview → settings → uninstall.
- Milestone: `InsurancePolicyExtractorSetup.exe` installs and runs
  correctly on a clean Windows 7 SP1 VM end to end.

## Verification strategy

- **Phase 1:** unit/console-harness comparison of extracted fields against
  the current Python app's output, using the PDFs already checked into
  `PDFs/`.
- **Phase 2–3:** manual exercise of each screen against the same PDFs,
  compared side-by-side against the live Python app (field values,
  currency/date formatting, CSV copy output, preview crop accuracy).
- **Phase 4:** end-to-end install/run/uninstall on a real Windows 7 SP1 VM
  — the only reliable way to confirm the port's actual goal, given this
  project's own history of compatibility claims not holding up without
  hands-on testing (see the PDFium risk section).

## Getting started (resuming this plan on a Windows machine)

1. Install the .NET SDK (8.x or later; it can still target `net48`).
2. Install Visual Studio 2022 (Community is fine) or use `dotnet` CLI +
   any editor — WPF designer support is nicer in VS but not required.
3. `dotnet new sln -n PdfXl`, then create the three projects under `src/`
   and `tests/` per the structure above (`dotnet new classlib` for
   `PdfXl.Core`, `dotnet new wpf` for `PdfXl.App`, `dotnet new xunit` for
   the test project), each retargeted to `net48` in the `.csproj`.
4. Do Phase 0 first — it determines the pdfium package choice that
   everything else in Phase 1 depends on.
5. Work through Phases 1→4 in order; each has a concrete milestone above
   to check against before moving on.
