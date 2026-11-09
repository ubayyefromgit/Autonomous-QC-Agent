import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { qcApi } from "../services/api";
import type { AuditSession, OverviewTelemetry } from "../types/qc";

export const OverviewPage: React.FC = () => {
  const [telemetry, setTelemetry] = useState<OverviewTelemetry | null>(null);
  const [recentAudits, setRecentAudits] = useState<AuditSession[]>([]);
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    setLoading(true);
    try {
      const [ov, audits] = await Promise.all([
        qcApi.getOverview(),
        qcApi.listAudits(),
      ]);
      setTelemetry(ov);
      setRecentAudits(audits.slice(0, 8));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  if (loading && !telemetry) {
    return <div className="text-slate-400 text-sm">Loading QC Overview Telemetry...</div>;
  }

  const cards = [
    { label: "Registered Projects", value: telemetry?.registered_projects ?? 0, tone: "text-sky-400" },
    { label: "Total Audits", value: telemetry?.total_audits ?? 0, tone: "text-slate-100" },
    { label: "Active Audits", value: telemetry?.active_audits ?? 0, tone: "text-amber-400" },
    { label: "Completed Audits", value: telemetry?.completed_audits ?? 0, tone: "text-emerald-400" },
    { label: "Failed Audits", value: telemetry?.failed_audits ?? 0, tone: "text-rose-400" },
    { label: "Total Findings", value: telemetry?.total_findings ?? 0, tone: "text-slate-100" },
    { label: "Critical Findings", value: telemetry?.critical_findings ?? 0, tone: "text-rose-500" },
    { label: "Security Findings", value: telemetry?.security_findings ?? 0, tone: "text-orange-400" },
    { label: "Pending Approvals", value: telemetry?.pending_approvals ?? 0, tone: "text-purple-400" },
    {
      label: "Avg Audit Duration",
      value: `${telemetry?.average_audit_duration_seconds ?? 0}s`,
      tone: "text-cyan-400",
    },
  ];

  const chartData = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFORMATIONAL"].map((sev) => ({
    severity: sev,
    count: telemetry?.severity_breakdown?.[sev] ?? 0,
  }));

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-100">
            Executive Quality Control Overview
          </h2>
          <p className="text-xs text-slate-400">
            Real-time telemetry across all registered repositories, audit sessions, findings, and remediation gates
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={loadData}
            className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium border border-slate-700"
          >
            Refresh Telemetry
          </button>
          <Link
            to="/"
            className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-xs font-semibold text-white"
          >
            + Upload Project / API Keys &amp; Setup Hub
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {cards.map((c) => (
          <div
            key={c.label}
            className="p-4 rounded-xl bg-slate-900 border border-slate-800 flex flex-col justify-between"
          >
            <span className="text-xs text-slate-400">{c.label}</span>
            <span className={`text-2xl font-bold mt-2 ${c.tone}`}>{c.value}</span>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <h3 className="text-sm font-semibold text-slate-200 mb-4">
            Findings by Severity
          </h3>
          <div className="h-60">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="severity" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={11} allowDecimals={false} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#0f172a",
                    borderColor: "#334155",
                    fontSize: "12px",
                  }}
                />
                <Bar dataKey="count" fill="#38bdf8" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="lg:col-span-2 p-5 rounded-xl bg-slate-900 border border-slate-800">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-slate-200">
              Recent Audit Sessions
            </h3>
            <Link to="/audits" className="text-xs text-sky-400 hover:underline">
              View All Audits →
            </Link>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="py-2 pr-3">Project</th>
                  <th className="py-2 pr-3">Scope</th>
                  <th className="py-2 pr-3">Runner</th>
                  <th className="py-2 pr-3">Status</th>
                  <th className="py-2 pr-3">Tasks</th>
                  <th className="py-2 pr-3">Score</th>
                  <th className="py-2">Release Gate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {recentAudits.map((a) => (
                  <tr key={a.id} className="hover:bg-slate-800/30">
                    <td className="py-2.5 pr-3 font-medium text-slate-200">
                      <Link
                        to={`/projects/${a.project_id}`}
                        className="hover:text-sky-400"
                      >
                        {a.project_name || a.project_id.slice(0, 8)}
                      </Link>
                    </td>
                    <td className="py-2.5 pr-3">{a.audit_scope}</td>
                    <td className="py-2.5 pr-3 font-mono">{a.runner_mode}</td>
                    <td className="py-2.5 pr-3">
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-200">
                        {a.status}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3">
                      {a.completed_tasks}/{a.total_tasks}
                    </td>
                    <td className="py-2.5 pr-3 font-semibold">
                      {a.overall_score !== null ? `${a.overall_score}/100` : "—"}
                    </td>
                    <td className="py-2.5">
                      <span
                        className={`px-2 py-0.5 rounded font-semibold ${
                          a.release_gate === "APPROVED"
                            ? "bg-emerald-500/15 text-emerald-300"
                            : a.release_gate === "REJECTED"
                            ? "bg-rose-500/15 text-rose-300"
                            : "bg-amber-500/15 text-amber-300"
                        }`}
                      >
                        {a.release_gate}
                      </span>
                    </td>
                  </tr>
                ))}
                {recentAudits.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-slate-500">
                      No audit sessions executed yet. Register a project to start an audit.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

