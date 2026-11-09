import React, { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  Cpu,
  FileCode2,
  FileSpreadsheet,
  FolderGit2,
  Gauge,
  GitPullRequestDraft,
  LayoutDashboard,
  PlayCircle,
  Radio,
  Rocket,
  Settings,
  ShieldAlert,
  ShieldCheck,
  TestTube2,
} from "lucide-react";
import { qcApi } from "../services/api";

const NAV_ITEMS = [
  { to: "/", label: "0. Launch, Upload & Setup Hub", icon: Rocket },
  { to: "/overview", label: "1. Executive Overview", icon: LayoutDashboard },
  { to: "/projects", label: "2. Projects", icon: FolderGit2 },
  { to: "/repository", label: "4. Repository Explorer", icon: FileCode2 },
  { to: "/audits", label: "5. Audit Sessions", icon: PlayCircle },
  { to: "/live-monitor", label: "6. Live Audit Monitor", icon: Radio },
  { to: "/findings", label: "7. Findings Explorer", icon: AlertTriangle },
  { to: "/evidence", label: "9. Evidence Explorer", icon: ShieldCheck },
  { to: "/test-results", label: "10. Test Execution", icon: TestTube2 },
  { to: "/security", label: "11. Security Assessment", icon: ShieldAlert },
  { to: "/performance", label: "12. Performance", icon: Gauge },
  { to: "/remediation", label: "13. Remediation Proposals", icon: GitPullRequestDraft },
  { to: "/approvals", label: "14. Approval Center", icon: CheckCircle2 },
  { to: "/reports", label: "15. Reports (HTML/PDF)", icon: FileSpreadsheet },
  { to: "/agent-activity", label: "16. Agent Activity", icon: Bot },
  { to: "/settings", label: "17. System Settings", icon: Settings },
];

export const DashboardLayout: React.FC = () => {
  const [health, setHealth] = useState<string>("CHECKING");

  useEffect(() => {
    qcApi
      .getHealth()
      .then((res) => setHealth(res.status || "HEALTHY"))
      .catch(() => setHealth("OFFLINE"));
  }, []);

  return (
    <div className="min-h-screen flex bg-slate-950 text-slate-100">
      <aside className="w-72 border-r border-slate-800 bg-slate-900/70 flex flex-col shrink-0">
        <div className="p-5 border-b border-slate-800">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-lg bg-sky-500/15 border border-sky-500/40 flex items-center justify-center text-sky-400">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <h1 className="font-bold text-sm tracking-wide text-slate-100">
                QC INTELLIGENCE
              </h1>
              <p className="text-xs text-slate-400">
                Autonomous Audit Platform v1.0
              </p>
            </div>
          </div>
        </div>

        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                  isActive
                    ? "bg-sky-500/15 text-sky-300 border border-sky-500/30"
                    : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
                }`
              }
            >
              <Icon className="w-4 h-4 shrink-0" />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-slate-800 text-xs flex items-center justify-between bg-slate-950/60">
          <span className="text-slate-400 flex items-center gap-1.5">
            <Activity className="w-3.5 h-3.5 text-emerald-400" />
            Engine Status
          </span>
          <span
            className={`px-2 py-0.5 rounded font-semibold ${
              health === "HEALTHY"
                ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30"
                : "bg-amber-500/15 text-amber-300 border border-amber-500/30"
            }`}
          >
            {health}
          </span>
        </div>
      </aside>

      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-14 border-b border-slate-800 bg-slate-900/40 px-6 flex items-center justify-between">
          <div className="text-xs text-slate-400">
            Evidence-First Deterministic Execution · SHA-256 Checksum-Bound Remediation Approval
          </div>
          <div className="flex items-center gap-3 text-xs">
            <span className="px-2.5 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700">
              Mode A (Dashboard) + Mode B (qc-agent CLI)
            </span>
          </div>
        </header>

        <main className="flex-1 p-6 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

