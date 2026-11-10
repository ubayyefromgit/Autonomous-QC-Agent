import React, { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cpu,
  Database,
  FileCode2,
  FileSpreadsheet,
  FolderGit2,
  Gauge,
  GitPullRequestDraft,
  KeyRound,
  LayoutDashboard,
  Moon,
  PlayCircle,
  Radio,
  RefreshCw,
  Rocket,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Sun,
  TestTube2,
  X,
} from "lucide-react";
import { qcApi } from "../services/api";

const PRIMARY_NAV = [
  { to: "/", label: "New Audit & Results", icon: Rocket },
  { to: "/findings", label: "Findings & Issues", icon: AlertTriangle },
  { to: "/approvals", label: "Fix Approvals", icon: CheckCircle2 },
  { to: "/reports", label: "Audit Reports", icon: FileSpreadsheet },
  { to: "/projects", label: "Projects", icon: FolderGit2 },
];

const ADVANCED_NAV = [
  { to: "/overview", label: "Dashboard Overview", icon: LayoutDashboard },
  { to: "/live-monitor", label: "Live Agent Monitor", icon: Radio },
  { to: "/repository", label: "Files & Coverage", icon: FileCode2 },
  { to: "/evidence", label: "Evidence Vault", icon: ShieldCheck },
  { to: "/test-results", label: "Test Runs", icon: TestTube2 },
  { to: "/security", label: "Security Details", icon: ShieldAlert },
  { to: "/performance", label: "Performance Details", icon: Gauge },
  { to: "/settings", label: "System Settings", icon: Settings },
];

export const DashboardLayout: React.FC = () => {
  const [health, setHealth] = useState<string>("CHECKING");
  const [dbEngine, setDbEngine] = useState<string>("DB");
  const [healthData, setHealthData] = useState<any>(null);
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [showPgModal, setShowPgModal] = useState<boolean>(false);
  const [pgHost, setPgHost] = useState<string>("127.0.0.1");
  const [pgPort, setPgPort] = useState<number>(5432);
  const [pgUser, setPgUser] = useState<string>("postgres");
  const [pgPassword, setPgPassword] = useState<string>("");
  const [pgDatabase, setPgDatabase] = useState<string>("qc_platform");
  const [pgConnecting, setPgConnecting] = useState<boolean>(false);
  const [pgError, setPgError] = useState<string | null>(null);
  const [pgSuccess, setPgSuccess] = useState<string | null>(null);

  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const saved = localStorage.getItem("qc_theme");
    return saved === "light" ? "light" : "dark";
  });

  useEffect(() => {
    const rootEl = document.documentElement;
    if (theme === "light") {
      rootEl.classList.add("theme-light");
      rootEl.classList.remove("theme-dark");
    } else {
      rootEl.classList.add("theme-dark");
      rootEl.classList.remove("theme-light");
    }
    localStorage.setItem("qc_theme", theme);
  }, [theme]);

  const fetchHealth = () => {
    qcApi
      .getHealth()
      .then((res) => {
        setHealth(res.status || "HEALTHY");
        setDbEngine(res.database?.engine || "Connected");
        setHealthData(res);
        if (res.database?.host_postgres_port) {
          setPgPort(res.database.host_postgres_port);
        }
      })
      .catch(() => setHealth("OFFLINE"));
  };

  useEffect(() => {
    fetchHealth();
  }, []);

  const toggleTheme = () => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  };

  const handleConnectPostgres = async (e: React.FormEvent) => {
    e.preventDefault();
    setPgConnecting(true);
    setPgError(null);
    setPgSuccess(null);
    try {
      const res = await qcApi.configureDatabase({
        host: pgHost,
        port: Number(pgPort),
        username: pgUser,
        password: pgPassword,
        database: pgDatabase,
      });
      setPgSuccess(res.message || "Successfully connected to PostgreSQL! Reloading workspace...");
      setTimeout(() => {
        window.location.reload();
      }, 1200);
    } catch (err: any) {
      setPgError(err.message || "Failed to authenticate or connect to PostgreSQL");
    } finally {
      setPgConnecting(false);
    }
  };

  const isPgActive = dbEngine.toLowerCase().includes("postgres");
  const hostPgDetected = Boolean(healthData?.database?.host_postgres_detected);

  return (
    <div className="min-h-screen flex bg-slate-950 text-slate-100">
      <aside className="w-64 border-r border-slate-800 bg-slate-900/70 flex flex-col shrink-0">
        <div className="p-5 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-sky-500/15 border border-sky-500/40 flex items-center justify-center text-sky-400">
              <Cpu className="w-4 h-4" />
            </div>
            <div>
              <h1 className="font-bold text-sm tracking-tight text-slate-100">
                QC Agent
              </h1>
              <p className="text-[11px] text-slate-400">
                Autonomous Audit Studio
              </p>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Workspace
          </div>
          {PRIMARY_NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                  isActive
                    ? "bg-sky-500/15 text-sky-400 border border-sky-500/30"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
                }`
              }
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}

          <div className="pt-3">
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="w-full flex items-center justify-between px-3 py-1.5 text-[11px] font-semibold text-slate-400 hover:text-slate-200"
            >
              <span>More Inspector Views</span>
              {showAdvanced ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
            </button>

            {showAdvanced && (
              <div className="mt-1 space-y-0.5 pl-1">
                {ADVANCED_NAV.map(({ to, label, icon: Icon }) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 px-3 py-1.5 rounded-lg text-xs transition-colors ${
                        isActive
                          ? "bg-sky-500/15 text-sky-400 font-medium"
                          : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
                      }`
                    }
                  >
                    <Icon className="w-3.5 h-3.5 shrink-0" />
                    <span>{label}</span>
                  </NavLink>
                ))}
              </div>
            )}
          </div>
        </nav>

        <div className="p-3 border-t border-slate-800 text-xs bg-slate-950/60 flex flex-col gap-2">
          {/* Host PostgreSQL Detected notification if currently running on SQLite */}
          {hostPgDetected && !isPgActive && (
            <div className="p-2 rounded-lg bg-sky-950/50 border border-sky-700/60 text-[11px] text-sky-200 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-semibold flex items-center gap-1">
                  🐘 Host PG Detected
                </span>
                <span className="text-[10px] text-sky-400 font-mono">
                  Port {healthData?.database?.host_postgres_port || 5432}
                </span>
              </div>
              <p className="text-[10px] text-slate-300">
                Running in SQLite fallback. Connect your PostgreSQL instance in 1 click:
              </p>
              <button
                type="button"
                onClick={() => {
                  setPgError(null);
                  setPgSuccess(null);
                  setShowPgModal(true);
                }}
                className="w-full py-1 text-center rounded bg-sky-600 hover:bg-sky-500 text-white font-semibold text-[11px] transition-colors"
              >
                Connect to PostgreSQL
              </button>
            </div>
          )}

          <div className="flex items-center justify-between">
            <span
              className="text-slate-300 flex items-center gap-1.5 text-[11px] font-medium cursor-pointer hover:text-sky-300 transition-colors"
              onClick={() => {
                setPgError(null);
                setPgSuccess(null);
                setShowPgModal(true);
              }}
              title={isPgActive ? "PostgreSQL is active (Click to change connection)" : "Click to connect to PostgreSQL"}
            >
              <Activity
                className={`w-3.5 h-3.5 ${
                  isPgActive ? "text-emerald-400" : "text-sky-400"
                } shrink-0`}
              />
              <span className="truncate max-w-[120px]">
                {isPgActive ? "PostgreSQL" : "SQLite Embedded"}
              </span>
            </span>
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-semibold ${
                health === "HEALTHY"
                  ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                  : "bg-amber-500/15 text-amber-400 border border-amber-500/30"
              }`}
            >
              {health}
            </span>
          </div>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 border-b border-slate-800 bg-slate-900/40 px-6 flex items-center justify-between">
          <div className="text-xs text-slate-400 font-medium">
            Autonomous Software Quality Control &amp; Project Audit Platform
          </div>
          <div className="flex items-center gap-3 text-xs">
            <button
              type="button"
              onClick={toggleTheme}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-medium transition-colors"
              title="Switch between Dark and Light Theme"
            >
              {theme === "dark" ? (
                <>
                  <Sun className="w-3.5 h-3.5 text-amber-400" />
                  <span>Light Mode</span>
                </>
              ) : (
                <>
                  <Moon className="w-3.5 h-3.5 text-sky-400" />
                  <span>Dark Mode</span>
                </>
              )}
            </button>
          </div>
        </header>

        <main className="flex-1 p-6 overflow-y-auto max-w-6xl w-full mx-auto">
          <Outlet />
        </main>
      </div>

      {/* PostgreSQL Connection Modal */}
      {showPgModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="bg-slate-900 border border-slate-700 rounded-xl max-w-md w-full shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
            <div className="p-4 border-b border-slate-800 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Database className="w-4 h-4 text-sky-400" />
                <h3 className="font-bold text-sm text-slate-100">
                  {isPgActive ? "PostgreSQL Configuration" : "Connect to PostgreSQL"}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setShowPgModal(false)}
                className="text-slate-400 hover:text-slate-200 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleConnectPostgres} className="p-5 space-y-4 text-xs">
              <p className="text-slate-300 text-xs leading-relaxed">
                {hostPgDetected
                  ? `A PostgreSQL server was detected on port ${pgPort}. Enter your PostgreSQL password to authenticate and switch database storage to PostgreSQL.`
                  : "Connect to your local or remote PostgreSQL database instance. Tables will be initialized automatically."}
              </p>

              {pgError && (
                <div className="p-3 rounded-lg bg-rose-500/15 border border-rose-500/40 text-rose-300 text-xs">
                  {pgError}
                </div>
              )}

              {pgSuccess && (
                <div className="p-3 rounded-lg bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 text-xs">
                  {pgSuccess}
                </div>
              )}

              <div className="grid grid-cols-3 gap-2">
                <div className="col-span-2 space-y-1">
                  <label className="text-slate-400 font-medium">Host</label>
                  <input
                    type="text"
                    value={pgHost}
                    onChange={(e) => setPgHost(e.target.value)}
                    required
                    className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-200 font-mono"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-slate-400 font-medium">Port</label>
                  <input
                    type="number"
                    value={pgPort}
                    onChange={(e) => setPgPort(Number(e.target.value))}
                    required
                    className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-200 font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-medium">Username</label>
                <input
                  type="text"
                  value={pgUser}
                  onChange={(e) => setPgUser(e.target.value)}
                  required
                  className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-200 font-mono"
                />
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-medium flex items-center justify-between">
                  <span>Password</span>
                  <span className="text-[10px] text-slate-500">(Leave blank if no password)</span>
                </label>
                <input
                  type="password"
                  value={pgPassword}
                  onChange={(e) => setPgPassword(e.target.value)}
                  placeholder="Enter PostgreSQL password..."
                  className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-200 font-mono"
                />
              </div>

              <div className="space-y-1">
                <label className="text-slate-400 font-medium">Database Name</label>
                <input
                  type="text"
                  value={pgDatabase}
                  onChange={(e) => setPgDatabase(e.target.value)}
                  required
                  className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-700 text-slate-200 font-mono"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowPgModal(false)}
                  className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={pgConnecting}
                  className="px-4 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold transition-colors flex items-center gap-1.5 disabled:opacity-50"
                >
                  {pgConnecting ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      <span>Testing Connection...</span>
                    </>
                  ) : (
                    <span>Connect &amp; Switch</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
