import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { qcApi } from "../services/api";
import type { Evidence, Finding } from "../types/qc";

export const FindingsPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [findings, setFindings] = useState<Finding[]>([]);
  const [severity, setSeverity] = useState<string>("");
  const [category, setCategory] = useState<string>("");
  const [verification, setVerification] = useState<string>("");
  const [lifecycle, setLifecycle] = useState<string>("");
  const [agentName, setAgentName] = useState<string>("");

  const sessionId = searchParams.get("sessionId") || "";

  const loadFindings = async () => {
    const res = await qcApi.listFindings({
      session_id: sessionId || undefined,
      severity: severity || undefined,
      category: category || undefined,
      verification_status: verification || undefined,
      lifecycle_status: lifecycle || undefined,
      agent_name: agentName || undefined,
    });
    setFindings(res);
  };

  useEffect(() => {
    loadFindings();
  }, [sessionId, severity, category, verification, lifecycle, agentName]);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">
          7. Evidence-Backed Findings Explorer
        </h2>
        <p className="text-xs text-slate-400">
          Filter deduplicated findings across severity, category, agent, verification status, and lifecycle state
        </p>
      </div>

      <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value)}
          className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
        >
          <option value="">All Severities</option>
          <option value="CRITICAL">CRITICAL</option>
          <option value="HIGH">HIGH</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="LOW">LOW</option>
          <option value="INFORMATIONAL">INFORMATIONAL</option>
        </select>

        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
        >
          <option value="">All Categories</option>
          <option value="SECURITY">SECURITY</option>
          <option value="BACKEND">BACKEND</option>
          <option value="FRONTEND">FRONTEND</option>
          <option value="DATABASE">DATABASE</option>
          <option value="ARCHITECTURE">ARCHITECTURE</option>
          <option value="CODE_QUALITY">CODE_QUALITY</option>
          <option value="PERFORMANCE">PERFORMANCE</option>
          <option value="INTEGRATION">INTEGRATION</option>
          <option value="INCOMPLETE_IMPLEMENTATION">INCOMPLETE_IMPLEMENTATION</option>
        </select>

        <select
          value={verification}
          onChange={(e) => setVerification(e.target.value)}
          className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
        >
          <option value="">All Verification States</option>
          <option value="REPRODUCED">REPRODUCED</option>
          <option value="CONFIRMED">CONFIRMED</option>
          <option value="SUSPECTED">SUSPECTED</option>
          <option value="UNVERIFIED">UNVERIFIED</option>
        </select>

        <select
          value={lifecycle}
          onChange={(e) => setLifecycle(e.target.value)}
          className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
        >
          <option value="">All Lifecycle States</option>
          <option value="OPEN">OPEN</option>
          <option value="CONFIRMED">CONFIRMED</option>
          <option value="PATCH_PROPOSED">PATCH_PROPOSED</option>
          <option value="APPROVED">APPROVED</option>
          <option value="RESOLVED">RESOLVED</option>
        </select>

        <select
          value={agentName}
          onChange={(e) => setAgentName(e.target.value)}
          className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
        >
          <option value="">All Agents</option>
          <option value="CodeQualityAgent">CodeQualityAgent</option>
          <option value="ArchitectureAuditAgent">ArchitectureAuditAgent</option>
          <option value="BackendQAAgent">BackendQAAgent</option>
          <option value="FrontendQAAgent">FrontendQAAgent</option>
          <option value="DatabaseAuditAgent">DatabaseAuditAgent</option>
          <option value="SecurityAuditAgent">SecurityAuditAgent</option>
          <option value="PerformanceAuditAgent">PerformanceAuditAgent</option>
          <option value="IntegrationFlowAgent">IntegrationFlowAgent</option>
        </select>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400">
              <th className="py-2 pr-3">Severity</th>
              <th className="py-2 pr-3">Title &amp; Location</th>
              <th className="py-2 pr-3">Category / Agent</th>
              <th className="py-2 pr-3">Verification</th>
              <th className="py-2 pr-3">Lifecycle</th>
              <th className="py-2 pr-3">Evidence</th>
              <th className="py-2">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {findings.map((f) => (
              <tr key={f.id} className="hover:bg-slate-800/30">
                <td className="py-2.5 pr-3">
                  <span
                    className={`px-2 py-0.5 rounded font-bold ${
                      f.severity === "CRITICAL" || f.severity === "HIGH"
                        ? "bg-rose-500/15 text-rose-300 border border-rose-500/30"
                        : f.severity === "MEDIUM"
                        ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                        : "bg-sky-500/15 text-sky-300 border border-sky-500/30"
                    }`}
                  >
                    {f.severity}
                  </span>
                </td>
                <td className="py-2.5 pr-3">
                  <Link
                    to={`/findings/${f.id}`}
                    className="font-semibold text-slate-100 hover:text-sky-400"
                  >
                    {f.title}
                  </Link>
                  <div className="font-mono text-[11px] text-slate-400 mt-0.5">
                    {f.file_path || "Global"}
                    {f.line_start ? `:${f.line_start}` : ""}
                  </div>
                </td>
                <td className="py-2.5 pr-3">
                  <div>{f.category}</div>
                  <div className="text-[11px] text-slate-400">{f.agent_name}</div>
                </td>
                <td className="py-2.5 pr-3">
                  <span className="px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-300 font-semibold">
                    {f.verification_status}
                  </span>
                </td>
                <td className="py-2.5 pr-3">
                  <span className="px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                    {f.lifecycle_status}
                  </span>
                </td>
                <td className="py-2.5 pr-3 font-mono">
                  {f.evidence_count} item(s)
                </td>
                <td className="py-2.5">
                  <Link
                    to={`/findings/${f.id}`}
                    className="text-sky-400 hover:underline font-medium"
                  >
                    8. Inspect &amp; Remediate →
                  </Link>
                </td>
              </tr>
            ))}
            {findings.length === 0 && (
              <tr>
                <td colSpan={7} className="py-6 text-center text-slate-500">
                  No findings match the current filter criteria.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const FindingDetailsPage: React.FC = () => {
  const { findingId } = useParams<{ findingId: string }>();
  const [finding, setFinding] = useState<Finding | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [creatingProposal, setCreatingProposal] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!findingId) return;
    Promise.all([
      qcApi.getFinding(findingId),
      qcApi.getFindingEvidence(findingId),
    ]).then(([f, ev]) => {
      setFinding(f);
      setEvidence(ev);
    });
  }, [findingId]);

  const handleGenerateProposal = async () => {
    if (!finding) return;
    setCreatingProposal(true);
    try {
      const proposal = await qcApi.createProposal(finding.id);
      navigate(`/approvals?proposalId=${proposal.id}`);
    } finally {
      setCreatingProposal(false);
    }
  };

  if (!finding) {
    return <div className="text-xs text-slate-400">Loading finding details...</div>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 rounded bg-rose-500/20 text-rose-300 text-xs font-bold">
              {finding.severity}
            </span>
            <span className="px-2.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-xs font-semibold">
              {finding.verification_status}
            </span>
            <span className="px-2.5 py-0.5 rounded bg-slate-800 text-slate-300 text-xs">
              Lifecycle: {finding.lifecycle_status}
            </span>
          </div>
          <h2 className="text-xl font-bold text-slate-100">
            8. {finding.title}
          </h2>
          <p className="text-xs font-mono text-sky-400 mt-1">
            Location: {finding.file_path || "N/A"}
            {finding.line_start ? `:${finding.line_start}-${finding.line_end}` : ""} ·
            Fingerprint: {finding.fingerprint}
          </p>
        </div>

        <button
          disabled={creatingProposal}
          onClick={handleGenerateProposal}
          className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-xs font-semibold text-white"
        >
          {creatingProposal
            ? "Synthesizing Patch..."
            : "Generate Remediation Proposal & Diff →"}
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-xs">
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
          <h3 className="text-sm font-semibold text-slate-200">
            Technical Description &amp; Root Cause
          </h3>
          <p className="text-slate-300 leading-relaxed">{finding.description}</p>
          <div>
            <span className="text-slate-400 font-semibold">Root Cause: </span>
            <span className="text-slate-200">{finding.root_cause || "—"}</span>
          </div>
          <div>
            <span className="text-slate-400 font-semibold">Expected Behavior: </span>
            <span className="text-slate-200">{finding.expected_behavior || "—"}</span>
          </div>
          <div>
            <span className="text-slate-400 font-semibold">Actual Behavior: </span>
            <span className="text-rose-300">{finding.actual_behavior || "—"}</span>
          </div>
        </div>

        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
          <h3 className="text-sm font-semibold text-slate-200">
            Reproduction Steps &amp; Recommended Fix
          </h3>
          <div>
            <div className="text-slate-400 font-semibold mb-1">
              Deterministic Reproduction Steps:
            </div>
            <ol className="list-decimal list-inside space-y-1 text-slate-300">
              {(finding.reproduction_steps || []).map((st, idx) => (
                <li key={idx}>{st}</li>
              ))}
            </ol>
          </div>
          <div>
            <span className="text-slate-400 font-semibold">Impact: </span>
            <span className="text-amber-300">{finding.impact || "—"}</span>
          </div>
          <div>
            <span className="text-slate-400 font-semibold">Recommended Fix: </span>
            <span className="text-emerald-300">{finding.recommended_fix || "—"}</span>
          </div>
        </div>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4">
        <h3 className="text-sm font-semibold text-slate-200">
          Linked Cryptographic Evidence ({evidence.length})
        </h3>
        <div className="space-y-3">
          {evidence.map((ev) => (
            <div
              key={ev.id}
              className="p-4 rounded-lg bg-slate-950 border border-slate-800 space-y-2 text-xs"
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold text-sky-400">
                  [{ev.evidence_type}] Tool: {ev.source_tool}
                </span>
                <span className="font-mono text-slate-400">
                  SHA-256: {ev.sha256_checksum}
                </span>
              </div>
              {ev.content_excerpt && (
                <pre className="p-3 rounded bg-slate-900 border border-slate-800 font-mono text-[11px] text-slate-200 overflow-x-auto whitespace-pre-wrap">
                  {ev.content_excerpt}
                </pre>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export const EvidenceExplorerPage: React.FC = () => {
  const [evidenceList, setEvidenceList] = useState<Evidence[]>([]);

  useEffect(() => {
    qcApi.listAllEvidence().then(setEvidenceList);
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">
          9. Cryptographic Evidence Vault Explorer
        </h2>
        <p className="text-xs text-slate-400">
          Immutable SHA-256 verified source excerpts, execution logs, HTTP responses, browser traces, and AST outputs
        </p>
      </div>

      <div className="space-y-3">
        {evidenceList.map((ev) => (
          <div
            key={ev.id}
            className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-2 text-xs"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 font-semibold">
                  {ev.evidence_type}
                </span>
                <span className="text-slate-300 font-medium">
                  Source Tool: {ev.source_tool}
                </span>
                {ev.finding_id && (
                  <Link
                    to={`/findings/${ev.finding_id}`}
                    className="text-amber-400 hover:underline"
                  >
                    Linked Finding →
                  </Link>
                )}
              </div>
              <div className="flex items-center gap-3 font-mono text-[11px] text-slate-400">
                <span>SHA-256: {ev.sha256_checksum.slice(0, 20)}...</span>
                <a
                  href={`/api/v1/evidence/${ev.id}/download`}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sky-400 hover:underline"
                >
                  Download Raw Artifact
                </a>
              </div>
            </div>
            {ev.content_excerpt && (
              <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto whitespace-pre-wrap">
                {ev.content_excerpt}
              </pre>
            )}
          </div>
        ))}
        {evidenceList.length === 0 && (
          <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 text-center text-xs text-slate-500">
            No evidence artifacts stored yet.
          </div>
        )}
      </div>
    </div>
  );
};

