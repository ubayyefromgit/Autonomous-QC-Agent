import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { qcApi } from "../services/api";
import type { AuditSession, Finding, TestRun } from "../types/qc";

export const SecurityAssessmentPage: React.FC = () => {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [audits, setAudits] = useState<AuditSession[]>([]);

  useEffect(() => {
    Promise.all([
      qcApi.listFindings({ category: "SECURITY" }),
      qcApi.listAudits(),
    ]).then(([f, a]) => {
      setFindings(f);
      setAudits(a);
    });
  }, []);

  const latestAudit = audits[0];
  const secScore = latestAudit?.scorecard?.dimensions?.["Security"]?.score ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">
          11. Security Posture &amp; Vulnerability Assessment
        </h2>
        <p className="text-xs text-slate-400">
          Hardcoded secrets, command/SQL injection, dangerous dynamic evaluation (eval/exec/shell=True), CORS, and Bandit SAST findings
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 text-xs">
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Security Dimension Score</div>
          <div className="text-2xl font-bold text-emerald-400 mt-1">
            {secScore !== null ? `${secScore}/100` : "—"}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Total Security Findings</div>
          <div className="text-2xl font-bold text-rose-400 mt-1">
            {findings.length}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Critical / High</div>
          <div className="text-2xl font-bold text-orange-400 mt-1">
            {
              findings.filter(
                (f) => f.severity === "CRITICAL" || f.severity === "HIGH"
              ).length
            }
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Secret Redaction Policy</div>
          <div className="text-sm font-bold text-sky-400 mt-2">
            ACTIVE (Logs + Evidence Vault)
          </div>
        </div>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
        <h3 className="text-sm font-semibold text-slate-200">
          Confirmed Security Vulnerabilities ({findings.length})
        </h3>
        <div className="space-y-3 text-xs">
          {findings.map((f) => (
            <div
              key={f.id}
              className="p-4 rounded-lg bg-slate-950 border border-slate-800 flex items-start justify-between gap-4"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold">
                    {f.severity}
                  </span>
                  <Link
                    to={`/findings/${f.id}`}
                    className="font-semibold text-slate-100 hover:text-sky-400"
                  >
                    {f.title}
                  </Link>
                </div>
                <div className="font-mono text-slate-400">
                  {f.file_path || "N/A"}:{f.line_start || 1}
                </div>
                <p className="text-slate-300">{f.description}</p>
              </div>
              <Link
                to={`/findings/${f.id}`}
                className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-sky-400 shrink-0"
              >
                Inspect Evidence →
              </Link>
            </div>
          ))}
          {findings.length === 0 && (
            <div className="text-slate-500 py-4 text-center">
              Zero security findings detected in the inspected scope.
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const PerformanceAssessmentPage: React.FC = () => {
  const [audits, setAudits] = useState<AuditSession[]>([]);
  const [perfFindings, setPerfFindings] = useState<Finding[]>([]);
  const [perfRuns, setPerfRuns] = useState<TestRun[]>([]);

  useEffect(() => {
    Promise.all([
      qcApi.listAudits(),
      qcApi.listFindings({ category: "PERFORMANCE" }),
    ]).then(async ([auds, fnds]) => {
      setAudits(auds);
      setPerfFindings(fnds);
      if (auds.length > 0) {
        const runs = await qcApi.getAuditTestRuns(auds[0].id);
        setPerfRuns(runs.filter((r) => r.test_suite_type === "PERFORMANCE_BENCHMARK"));
      }
    });
  }, []);

  const latestPerf = perfRuns[0]?.details || {};
  const latestAudit = audits[0];
  const perfScore =
    latestAudit?.scorecard?.dimensions?.["Performance & Scalability"]?.score ?? null;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">
          12. Performance, Latency &amp; Resource Assessment
        </h2>
        <p className="text-xs text-slate-400">
          Empirical p50/p95/p99 latency percentiles, throughput (RPS), CPU &amp; memory telemetry, and event-loop bottleneck analysis
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-6 gap-4 text-xs">
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Performance Score</div>
          <div className="text-xl font-bold text-emerald-400 mt-1">
            {perfScore !== null ? `${perfScore}/100` : "—"}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">p50 Latency</div>
          <div className="text-xl font-bold text-sky-400 mt-1">
            {latestPerf.p50_ms !== undefined ? `${latestPerf.p50_ms} ms` : "—"}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">p95 Latency</div>
          <div className="text-xl font-bold text-amber-400 mt-1">
            {latestPerf.p95_ms !== undefined ? `${latestPerf.p95_ms} ms` : "—"}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">p99 Latency</div>
          <div className="text-xl font-bold text-rose-400 mt-1">
            {latestPerf.p99_ms !== undefined ? `${latestPerf.p99_ms} ms` : "—"}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Throughput (RPS)</div>
          <div className="text-xl font-bold text-cyan-400 mt-1">
            {latestPerf.rps !== undefined ? `${latestPerf.rps} req/s` : "—"}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">System Memory Used</div>
          <div className="text-xl font-bold text-slate-200 mt-1">
            {latestPerf.memory_used_percent !== undefined
              ? `${latestPerf.memory_used_percent}%`
              : "—"}
          </div>
        </div>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3 text-xs">
        <h3 className="text-sm font-semibold text-slate-200">
          Recorded Benchmark Conditions
        </h3>
        <div className="font-mono text-slate-300 bg-slate-950 p-3 rounded-lg border border-slate-800">
          {latestPerf.test_conditions ||
            "Run a FULL or PERFORMANCE audit to record concurrent HTTP benchmark telemetry."}
        </div>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3 text-xs">
        <h3 className="text-sm font-semibold text-slate-200">
          Performance &amp; Concurrency Bottleneck Findings ({perfFindings.length})
        </h3>
        {perfFindings.map((f) => (
          <div
            key={f.id}
            className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between"
          >
            <div>
              <span className="font-bold text-amber-400 mr-2">[{f.severity}]</span>
              <Link to={`/findings/${f.id}`} className="font-semibold hover:text-sky-400">
                {f.title}
              </Link>
              <span className="ml-2 font-mono text-slate-400">
                {f.file_path}:{f.line_start}
              </span>
            </div>
            <Link to={`/findings/${f.id}`} className="text-sky-400 hover:underline">
              Details →
            </Link>
          </div>
        ))}
        {perfFindings.length === 0 && (
          <div className="text-slate-500">
            No synchronous blocking calls or N+1 query loops detected.
          </div>
        )}
      </div>
    </div>
  );
};

