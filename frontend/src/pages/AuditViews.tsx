import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { qcApi } from "../services/api";
import type { AuditProgress, AuditSession, Project, TestRun } from "../types/qc";

export const AuditSessionsPage: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [audits, setAudits] = useState<AuditSession[]>([]);
  const [selectedProject, setSelectedProject] = useState<string>("");
  const [scope, setScope] = useState<string>("FULL");
  const [runnerMode, setRunnerMode] = useState<string>("LOCAL");
  const [running, setRunning] = useState<boolean>(false);

  const loadAll = async () => {
    const [projs, auds] = await Promise.all([
      qcApi.listProjects(),
      qcApi.listAudits(),
    ]);
    setProjects(projs);
    setAudits(auds);
    if (projs.length > 0 && !selectedProject) {
      setSelectedProject(projs[0].id);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const handleTrigger = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedProject) return;
    setRunning(true);
    try {
      await qcApi.startAudit(selectedProject, {
        audit_scope: scope,
        runner_mode: runnerMode,
        run_immediately: true,
        run_synchronously: true,
      });
      await loadAll();
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">
          5. Audit Sessions &amp; Execution Control
        </h2>
        <p className="text-xs text-slate-400">
          Launch scoped or full-stack audits, inspect scorecards, or resume interrupted sessions
        </p>
      </div>

      <form
        onSubmit={handleTrigger}
        className="p-5 rounded-xl bg-slate-900 border border-slate-800 grid grid-cols-1 md:grid-cols-4 gap-4 items-end text-xs"
      >
        <div>
          <label className="block text-slate-400 mb-1">Target Project</label>
          <select
            value={selectedProject}
            onChange={(e) => setSelectedProject(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-slate-400 mb-1">Audit Scope</label>
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
          >
            <option value="FULL">FULL (All 9 Agent Phases)</option>
            <option value="CODE">CODE (Static + Architecture)</option>
            <option value="BACKEND">BACKEND (Server + API + DB)</option>
            <option value="FRONTEND">FRONTEND (Playwright Browser QA)</option>
            <option value="SECURITY">SECURITY (Secrets + Injection + AST)</option>
            <option value="PERFORMANCE">PERFORMANCE (Latency + Bottlenecks)</option>
            <option value="E2E">E2E (Full-Stack Workflows)</option>
          </select>
        </div>

        <div>
          <label className="block text-slate-400 mb-1">Execution Runner</label>
          <select
            value={runnerMode}
            onChange={(e) => setRunnerMode(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
          >
            <option value="LOCAL">LOCAL (Isolated Process Workspace)</option>
            <option value="DOCKER">DOCKER (Disposable Container)</option>
          </select>
        </div>

        <button
          type="submit"
          disabled={running || !selectedProject}
          className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold text-white disabled:opacity-50"
        >
          {running ? "Executing Audit..." : "Execute Deterministic Audit"}
        </button>
      </form>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400">
              <th className="py-2 pr-3">Session ID</th>
              <th className="py-2 pr-3">Project</th>
              <th className="py-2 pr-3">Scope / Runner</th>
              <th className="py-2 pr-3">Phase / Status</th>
              <th className="py-2 pr-3">Tasks</th>
              <th className="py-2 pr-3">Score</th>
              <th className="py-2 pr-3">Release Gate</th>
              <th className="py-2">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {audits.map((a) => (
              <tr key={a.id} className="hover:bg-slate-800/30">
                <td className="py-2.5 pr-3 font-mono text-sky-400">
                  {a.id.slice(0, 8)}
                </td>
                <td className="py-2.5 pr-3 font-medium">
                  {a.project_name || a.project_id.slice(0, 8)}
                </td>
                <td className="py-2.5 pr-3">
                  {a.audit_scope} / <span className="font-mono">{a.runner_mode}</span>
                </td>
                <td className="py-2.5 pr-3">
                  {a.current_phase} ({a.status})
                </td>
                <td className="py-2.5 pr-3">
                  {a.completed_tasks}/{a.total_tasks} (Failed: {a.failed_tasks})
                </td>
                <td className="py-2.5 pr-3 font-bold">
                  {a.overall_score !== null ? `${a.overall_score}/100` : "—"}
                </td>
                <td className="py-2.5 pr-3">
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
                <td className="py-2.5 space-x-2">
                  <Link
                    to={`/live-monitor?auditId=${a.id}`}
                    className="text-sky-400 hover:underline"
                  >
                    Monitor
                  </Link>
                  <Link
                    to={`/findings?sessionId=${a.id}`}
                    className="text-amber-400 hover:underline"
                  >
                    Findings
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const LiveAuditMonitorPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [audits, setAudits] = useState<AuditSession[]>([]);
  const [selectedAuditId, setSelectedAuditId] = useState<string>(
    searchParams.get("auditId") || ""
  );
  const [progress, setProgress] = useState<AuditProgress | null>(null);

  useEffect(() => {
    qcApi.listAudits().then((list) => {
      setAudits(list);
      if (!selectedAuditId && list.length > 0) {
        setSelectedAuditId(list[0].id);
      }
    });
  }, []);

  const refreshProgress = async (id: string) => {
    if (!id) return;
    const p = await qcApi.getAuditProgress(id);
    setProgress(p);
  };

  useEffect(() => {
    if (!selectedAuditId) return;
    refreshProgress(selectedAuditId);
    const timer = setInterval(() => refreshProgress(selectedAuditId), 3000);
    return () => clearInterval(timer);
  }, [selectedAuditId]);

  const handleCancel = async () => {
    if (!selectedAuditId) return;
    await qcApi.cancelAudit(selectedAuditId);
    await refreshProgress(selectedAuditId);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-100">
            6. Live Audit Monitoring &amp; Task DAG Execution
          </h2>
          <p className="text-xs text-slate-400">
            Progress reflects actual completed tasks in the orchestrator DAG, never synthetic animation
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
                {a.status})
              </option>
            ))}
          </select>

          {progress &&
            !["COMPLETED", "FAILED", "CANCELLED"].includes(progress.status) && (
              <button
                onClick={handleCancel}
                className="px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white font-semibold"
              >
                Cancel Audit
              </button>
            )}
        </div>
      </div>

      {progress ? (
        <>
          <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-6 gap-4 text-xs">
              <div>
                <div className="text-slate-400">Status</div>
                <div className="font-bold text-sm mt-0.5">{progress.status}</div>
              </div>
              <div>
                <div className="text-slate-400">Current Phase</div>
                <div className="font-bold text-sm text-sky-400 mt-0.5">
                  {progress.current_phase}
                </div>
              </div>
              <div>
                <div className="text-slate-400">Completed Tasks</div>
                <div className="font-bold text-sm text-emerald-400 mt-0.5">
                  {progress.completed_tasks} / {progress.total_tasks}
                </div>
              </div>
              <div>
                <div className="text-slate-400">Failed Tasks</div>
                <div className="font-bold text-sm text-rose-400 mt-0.5">
                  {progress.failed_tasks}
                </div>
              </div>
              <div>
                <div className="text-slate-400">Active Agents</div>
                <div className="font-mono text-xs mt-0.5">
                  {progress.active_agents.join(", ") || "Idle"}
                </div>
              </div>
              <div>
                <div className="text-slate-400">Elapsed Time</div>
                <div className="font-bold text-sm mt-0.5">
                  {progress.elapsed_seconds}s
                </div>
              </div>
            </div>

            <div>
              <div className="flex justify-between text-xs mb-1">
                <span>Deterministic Task DAG Completion</span>
                <span className="font-mono font-bold">
                  {progress.progress_percent}%
                </span>
              </div>
              <div className="w-full h-3 rounded-full bg-slate-950 overflow-hidden border border-slate-800">
                <div
                  className="h-full bg-sky-500 transition-all duration-300"
                  style={{ width: `${progress.progress_percent}%` }}
                />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
              <h3 className="text-sm font-semibold mb-3">
                Orchestrator Task Graph ({progress.tasks.length})
              </h3>
              <div className="space-y-2 text-xs">
                {progress.tasks.map((t) => (
                  <div
                    key={t.id}
                    className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between"
                  >
                    <div>
                      <div className="font-semibold text-slate-200">
                        {t.task_key} ({t.agent_type})
                      </div>
                      <div className="text-slate-400 text-[11px]">
                        Phase: {t.phase} · Dependencies:{" "}
                        {t.dependencies.join(", ") || "None"}
                      </div>
                    </div>
                    <div className="text-right">
                      <span
                        className={`px-2 py-0.5 rounded font-semibold ${
                          t.status === "COMPLETED"
                            ? "bg-emerald-500/15 text-emerald-300"
                            : t.status === "FAILED"
                            ? "bg-rose-500/15 text-rose-300"
                            : "bg-slate-800 text-slate-300"
                        }`}
                      >
                        {t.status}
                      </span>
                      <div className="text-[11px] text-slate-500 mt-0.5">
                        {t.duration_seconds !== null ? `${t.duration_seconds}s` : ""}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
              <h3 className="text-sm font-semibold mb-3">
                Runtime Execution Logs ({progress.recent_logs.length})
              </h3>
              <div className="space-y-2 max-h-96 overflow-y-auto font-mono text-[11px]">
                {progress.recent_logs.map((lg) => (
                  <div
                    key={lg.id}
                    className="p-2.5 rounded bg-slate-950 border border-slate-800"
                  >
                    <div className="text-sky-400">
                      [{lg.runner_type}] $ {lg.command} (exit={lg.exit_code},{" "}
                      {lg.duration_seconds}s)
                    </div>
                    {lg.stdout_preview && (
                      <div className="text-slate-300 mt-1 whitespace-pre-wrap">
                        {lg.stdout_preview}
                      </div>
                    )}
                    {lg.stderr_preview && (
                      <div className="text-rose-400 mt-1 whitespace-pre-wrap">
                        {lg.stderr_preview}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="text-xs text-slate-500">
          Select an audit session to view live progress.
        </div>
      )}
    </div>
  );
};

export const TestExecutionPage: React.FC = () => {
  const [audits, setAudits] = useState<AuditSession[]>([]);
  const [selectedAuditId, setSelectedAuditId] = useState<string>("");
  const [testRuns, setTestRuns] = useState<TestRun[]>([]);

  useEffect(() => {
    qcApi.listAudits().then((list) => {
      setAudits(list);
      if (list.length > 0) setSelectedAuditId(list[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selectedAuditId) return;
    qcApi.getAuditTestRuns(selectedAuditId).then(setTestRuns);
  }, [selectedAuditId]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-100">
            10. Deterministic Test Execution Results
          </h2>
          <p className="text-xs text-slate-400">
            Actual pass/fail execution outcomes from Pytest, HTTPX API probes, Playwright Browser, PostgreSQL, and Security scanners
          </p>
        </div>
        <select
          value={selectedAuditId}
          onChange={(e) => setSelectedAuditId(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs"
        >
          {audits.map((a) => (
            <option key={a.id} value={a.id}>
              {a.project_name || a.project_id.slice(0, 8)} — {a.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400">
              <th className="py-2 pr-3">Suite Type</th>
              <th className="py-2 pr-3">Tool</th>
              <th className="py-2 pr-3">Command</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3">Passed / Total</th>
              <th className="py-2 pr-3">Failed</th>
              <th className="py-2 pr-3">Exit Code</th>
              <th className="py-2">Duration</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {testRuns.map((tr) => (
              <tr key={tr.id}>
                <td className="py-2.5 pr-3 font-semibold">{tr.test_suite_type}</td>
                <td className="py-2.5 pr-3">{tr.tool_name}</td>
                <td className="py-2.5 pr-3 font-mono text-sky-300">{tr.command}</td>
                <td className="py-2.5 pr-3">
                  <span
                    className={`px-2 py-0.5 rounded font-semibold ${
                      tr.status === "PASSED"
                        ? "bg-emerald-500/15 text-emerald-300"
                        : "bg-rose-500/15 text-rose-300"
                    }`}
                  >
                    {tr.status}
                  </span>
                </td>
                <td className="py-2.5 pr-3">
                  {tr.passed_tests} / {tr.total_tests}
                </td>
                <td className="py-2.5 pr-3 text-rose-400 font-semibold">
                  {tr.failed_tests}
                </td>
                <td className="py-2.5 pr-3 font-mono">{tr.exit_code}</td>
                <td className="py-2.5">{tr.duration_seconds}s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

