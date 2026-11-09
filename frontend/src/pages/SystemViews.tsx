import React, { useEffect, useState } from "react";
import { qcApi } from "../services/api";
import type { AuditSession, ReportRecord } from "../types/qc";

export const ReportsPage: React.FC = () => {
  const [audits, setAudits] = useState<AuditSession[]>([]);
  const [reports, setReports] = useState<ReportRecord[]>([]);
  const [selectedAuditId, setSelectedAuditId] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);

  const loadData = async () => {
    const [auds, reps] = await Promise.all([
      qcApi.listAudits(),
      qcApi.listReports(),
    ]);
    setAudits(auds);
    setReports(reps);
    if (auds.length > 0 && !selectedAuditId) {
      setSelectedAuditId(auds[0].id);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleGenerate = async (format: "HTML" | "PDF") => {
    if (!selectedAuditId) return;
    setBusy(true);
    try {
      await qcApi.generateReport(selectedAuditId, format);
      await loadData();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100">
            15. Technical Audit Reports (HTML &amp; PDF)
          </h2>
          <p className="text-xs text-slate-400">
            21-section executive &amp; technical audit reports with truthful completeness disclosure and SHA-256 verification
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <select
            value={selectedAuditId}
            onChange={(e) => setSelectedAuditId(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700"
          >
            {audits.map((a) => (
              <option key={a.id} value={a.id}>
                {a.project_name || a.project_id.slice(0, 8)} — {a.audit_scope} (
                {a.overall_score ?? "—"}/100)
              </option>
            ))}
          </select>
          <button
            disabled={busy || !selectedAuditId}
            onClick={() => handleGenerate("HTML")}
            className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white disabled:opacity-50"
          >
            Generate HTML Report
          </button>
          <button
            disabled={busy || !selectedAuditId}
            onClick={() => handleGenerate("PDF")}
            className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold text-white disabled:opacity-50"
          >
            Generate PDF Report
          </button>
        </div>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400">
              <th className="py-2 pr-3">Report ID</th>
              <th className="py-2 pr-3">Audit Session</th>
              <th className="py-2 pr-3">Format</th>
              <th className="py-2 pr-3">Overall Score</th>
              <th className="py-2 pr-3">Release Gate</th>
              <th className="py-2 pr-3">Completeness</th>
              <th className="py-2 pr-3">SHA-256</th>
              <th className="py-2">Download</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {reports.map((r) => (
              <tr key={r.id} className="hover:bg-slate-800/30">
                <td className="py-2.5 pr-3 font-mono text-sky-400">
                  {r.id.slice(0, 8)}
                </td>
                <td className="py-2.5 pr-3 font-mono">{r.session_id.slice(0, 8)}</td>
                <td className="py-2.5 pr-3 font-bold">{r.report_format}</td>
                <td className="py-2.5 pr-3 font-bold">{r.overall_score}/100</td>
                <td className="py-2.5 pr-3">
                  <span
                    className={`px-2 py-0.5 rounded font-semibold ${
                      r.release_recommendation === "APPROVED"
                        ? "bg-emerald-500/15 text-emerald-300"
                        : r.release_recommendation === "REJECTED"
                        ? "bg-rose-500/15 text-rose-300"
                        : "bg-amber-500/15 text-amber-300"
                    }`}
                  >
                    {r.release_recommendation}
                  </span>
                </td>
                <td className="py-2.5 pr-3">
                  {r.audit_complete
                    ? "COMPLETE"
                    : `INCOMPLETE (${r.incomplete_checks.length})`}
                </td>
                <td className="py-2.5 pr-3 font-mono text-slate-500">
                  {r.sha256_checksum.slice(0, 12)}...
                </td>
                <td className="py-2.5">
                  <a
                    href={`/api/v1/reports/${r.id}/download`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-sky-400 hover:underline font-semibold"
                  >
                    Download {r.report_format} →
                  </a>
                </td>
              </tr>
            ))}
            {reports.length === 0 && (
              <tr>
                <td colSpan={8} className="py-6 text-center text-slate-500">
                  No reports generated yet. Select an audit session and click Generate HTML or PDF Report.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const AgentActivityPage: React.FC = () => {
  const [agents, setAgents] = useState<any[]>([]);
  const [executions, setExecutions] = useState<any[]>([]);
  const [events, setEvents] = useState<any[]>([]);

  useEffect(() => {
    Promise.all([qcApi.getAgents(), qcApi.getAgentActivity()]).then(
      ([agRes, actRes]) => {
        setAgents(agRes.agents || []);
        setExecutions(actRes.executions || []);
        setEvents(actRes.events || []);
      }
    );
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">
          16. Specialized Agent Registry &amp; Execution Telemetry
        </h2>
        <p className="text-xs text-slate-400">
          10 specialized deterministic QC agents coordinated by the Master Orchestrator DAG
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3 text-xs">
        {agents.map((ag) => (
          <div
            key={ag.agent_type}
            className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1.5"
          >
            <div className="font-bold text-sky-400">{ag.agent_type}</div>
            <div className="text-[11px] text-slate-400">Phase: {ag.phase}</div>
            <div className="text-[11px] text-slate-300">{ag.description}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 text-xs">
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <h3 className="text-sm font-semibold mb-3">
            Agent Execution Records ({executions.length})
          </h3>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {executions.map((ex) => (
              <div
                key={ex.id}
                className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between"
              >
                <div>
                  <div className="font-semibold text-slate-200">
                    {ex.agent_name}
                  </div>
                  <div className="text-[11px] text-slate-400">
                    Provider: {ex.llm_provider} · Duration: {ex.duration_seconds}s
                  </div>
                </div>
                <div className="text-right">
                  <div className="text-emerald-400 font-semibold">
                    {ex.findings_produced} finding(s)
                  </div>
                  <div className="text-[11px] text-slate-500">{ex.status}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
          <h3 className="text-sm font-semibold mb-3">
            Immutable Audit Event Stream ({events.length})
          </h3>
          <div className="space-y-2 max-h-96 overflow-y-auto font-mono text-[11px]">
            {events.map((ev) => (
              <div
                key={ev.id}
                className="p-2.5 rounded bg-slate-950 border border-slate-800"
              >
                <div className="text-sky-400">
                  [{ev.event_type}] Actor: {ev.actor}
                </div>
                <div className="text-slate-400 mt-0.5">
                  {JSON.stringify(ev.payload)}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export const SystemSettingsPage: React.FC = () => {
  const [health, setHealth] = useState<any>(null);
  const [executors, setExecutors] = useState<any>(null);

  useEffect(() => {
    Promise.all([qcApi.getHealth(), qcApi.getExecutors()]).then(([h, ex]) => {
      setHealth(h);
      setExecutors(ex);
    });
  }, []);

  return (
    <div className="space-y-6 text-xs">
      <div>
        <h2 className="text-xl font-bold text-slate-100">
          17. System Settings, Isolation Policies &amp; Scoring Weights
        </h2>
        <p className="text-xs text-slate-400">
          Execution runner sandboxes, command allowlists, AI provider gateway configuration, and 8-dimension weights
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
          <h3 className="text-sm font-semibold text-slate-200">
            Platform Health &amp; AI Gateway
          </h3>
          <pre className="p-3 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto">
            {JSON.stringify(health, null, 2)}
          </pre>
        </div>

        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
          <h3 className="text-sm font-semibold text-slate-200">
            Execution Sandboxes, Allowlists &amp; Scoring Weights
          </h3>
          <pre className="p-3 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto max-h-96">
            {JSON.stringify(executors, null, 2)}
          </pre>
        </div>
      </div>
    </div>
  );
};

