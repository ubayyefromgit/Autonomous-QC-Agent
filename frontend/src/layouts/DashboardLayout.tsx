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
  FileCode2,
  FileSpreadsheet,
  FolderGit2,
  Gauge,
  GitPullRequestDraft,
  LayoutDashboard,
  Moon,
  PlayCircle,
  Radio,
  Rocket,
  Settings,
  ShieldAlert,
  ShieldCheck,
  Sun,
  TestTube2,
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
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
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

  useEffect(() => {
    qcApi
      .getHealth()
      .then((res) => {
        setHealth(res.status || "HEALTHY");
        setDbEngine(res.database?.engine || "Connected");
      })
      .catch(() => setHealth("OFFLINE"));
  }, []);

  const toggleTheme = () => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  };

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

        <div className="p-3.5 border-t border-slate-800 text-xs flex items-center justify-between bg-slate-950/60">
          <span className="text-slate-400 flex items-center gap-1.5 text-[11px]">
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
            {dbEngine}
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
    </div>
  );
};
