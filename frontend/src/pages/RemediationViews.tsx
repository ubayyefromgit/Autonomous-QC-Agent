import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { qcApi } from "../services/api";
import type { RemediationProposal } from "../types/qc";

export const RemediationProposalsPage: React.FC = () => {
  const [proposals, setProposals] = useState<RemediationProposal[]>([]);

  const loadProposals = async () => {
    const list = await qcApi.listProposals();
    setProposals(list);
  };

  useEffect(() => {
    loadProposals();
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">
          13. Remediation Proposals &amp; Isolated Patch Lifecycle
        </h2>
        <p className="text-xs text-slate-400">
          Every proposed patch is cryptographically bound to a SHA-256 checksum and requires explicit human approval before application
        </p>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400">
              <th className="py-2 pr-3">Proposal ID</th>
              <th className="py-2 pr-3">Target Files</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3">Active Patch Checksum</th>
              <th className="py-2 pr-3">Approvals</th>
              <th className="py-2 pr-3">Regression Runs</th>
              <th className="py-2">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {proposals.map((p) => (
              <tr key={p.id} className="hover:bg-slate-800/30">
                <td className="py-2.5 pr-3 font-mono text-sky-400">
                  {p.id.slice(0, 8)}
                </td>
                <td className="py-2.5 pr-3 font-mono">
                  {p.affected_files.join(", ") || "—"}
                </td>
                <td className="py-2.5 pr-3">
                  <span
                    className={`px-2 py-0.5 rounded font-semibold ${
                      p.status === "VERIFIED_RESOLVED"
                        ? "bg-emerald-500/15 text-emerald-300"
                        : p.status === "APPROVED"
                        ? "bg-sky-500/15 text-sky-300"
                        : p.status === "REJECTED"
                        ? "bg-rose-500/15 text-rose-300"
                        : "bg-amber-500/15 text-amber-300"
                    }`}
                  >
                    {p.status}
                  </span>
                </td>
                <td className="py-2.5 pr-3 font-mono text-slate-400">
                  {p.active_patch_checksum.slice(0, 16)}...
                </td>
                <td className="py-2.5 pr-3">{p.approvals.length}</td>
                <td className="py-2.5 pr-3">{p.regression_runs.length}</td>
                <td className="py-2.5">
                  <Link
                    to={`/approvals?proposalId=${p.id}`}
                    className="text-sky-400 hover:underline font-semibold"
                  >
                    14. Open in Approval Center →
                  </Link>
                </td>
              </tr>
            ))}
            {proposals.length === 0 && (
              <tr>
                <td colSpan={7} className="py-6 text-center text-slate-500">
                  No remediation proposals generated yet. Open any Finding and click &quot;Generate Remediation Proposal&quot;.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const ApprovalCenterPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const [proposals, setProposals] = useState<RemediationProposal[]>([]);
  const [selectedId, setSelectedId] = useState<string>(
    searchParams.get("proposalId") || ""
  );
  const [selected, setSelected] = useState<RemediationProposal | null>(null);
  const [comments, setComments] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  const loadList = async () => {
    const list = await qcApi.listProposals();
    setProposals(list);
    const targetId = selectedId || searchParams.get("proposalId") || list[0]?.id || "";
    if (targetId) {
      setSelectedId(targetId);
      const detail = await qcApi.getProposal(targetId);
      setSelected(detail);
    }
  };

  useEffect(() => {
    loadList();
  }, []);

  const handleSelectChange = async (id: string) => {
    setSelectedId(id);
    setStatusMsg(null);
    if (id) {
      const detail = await qcApi.getProposal(id);
      setSelected(detail);
    }
  };

  const handleApprove = async () => {
    if (!selected) return;
    setBusy(true);
    setStatusMsg(null);
    try {
      const updated = await qcApi.approveProposal(
        selected.id,
        selected.active_patch_checksum,
        comments || "Verified diff and checksum in Approval Center"
      );
      setSelected(updated);
      setStatusMsg(
        `Approved patch checksum ${updated.active_patch_checksum.slice(0, 16)}... Ready for isolated branch application.`
      );
    } catch (err: any) {
      setStatusMsg(`Approval error: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    if (!selected) return;
    setBusy(true);
    setStatusMsg(null);
    try {
      const updated = await qcApi.rejectProposal(
        selected.id,
        selected.active_patch_checksum,
        comments || "Rejected by human reviewer"
      );
      setSelected(updated);
      setStatusMsg(`Proposal rejected.`);
    } catch (err: any) {
      setStatusMsg(`Reject error: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  const handleApplyAndVerify = async () => {
    if (!selected) return;
    setBusy(true);
    setStatusMsg(null);
    try {
      const updated = await qcApi.applyProposal(selected.id);
      setSelected(updated);
      setStatusMsg(
        `Patch applied in isolated working branch and regression suite executed! Final status: ${updated.status}`
      );
    } catch (err: any) {
      setStatusMsg(`Application error: ${err.message}`);
    } finally {
      setBusy(false);
    }
  };

  const activePatch = selected?.patches?.[0];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100">
            14. Human-Controlled Remediation Approval Center
          </h2>
          <p className="text-xs text-slate-400">
            Side-by-side code comparison, unified Git diff, SHA-256 checksum verification, and automated post-patch regression gate
          </p>
        </div>

        <select
          value={selectedId}
          onChange={(e) => handleSelectChange(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700 text-xs"
        >
          {proposals.map((p) => (
            <option key={p.id} value={p.id}>
              Proposal {p.id.slice(0, 8)} — {p.affected_files.join(", ")} ({p.status})
            </option>
          ))}
        </select>
      </div>

      {statusMsg && (
        <div className="p-3 rounded-lg bg-sky-500/15 border border-sky-500/30 text-xs text-sky-300">
          {statusMsg}
        </div>
      )}

      {selected && activePatch ? (
        <div className="space-y-6 text-xs">
          <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <div className="text-slate-400">Proposal Status</div>
              <div className="text-base font-bold text-sky-400 mt-0.5">
                {selected.status}
              </div>
              <div className="text-slate-400 mt-2">Affected File</div>
              <div className="font-mono text-slate-200">
                {activePatch.target_file_path}
              </div>
            </div>
            <div>
              <div className="text-slate-400">SHA-256 Patch Checksum (Immutable Lock)</div>
              <div className="font-mono text-emerald-400 break-all mt-0.5">
                {selected.active_patch_checksum}
              </div>
              <div className="text-slate-400 mt-2">Isolated Working Branch</div>
              <div className="font-mono text-slate-200">
                {activePatch.working_branch || "qc-remediation/<id>"}
              </div>
            </div>
            <div>
              <div className="text-slate-400">Pre-Application Safety Checks</div>
              <div className="mt-1 space-y-1">
                <div>
                  AST Syntax Valid:{" "}
                  <strong className="text-emerald-400">
                    {activePatch.syntax_valid ? "YES" : "NO"}
                  </strong>
                </div>
                <div>
                  Static Checks Passed:{" "}
                  <strong className="text-emerald-400">
                    {activePatch.static_checks_passed ? "YES" : "NO"}
                  </strong>
                </div>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
              <h3 className="text-sm font-semibold text-slate-200">
                Root Cause &amp; Explanation
              </h3>
              <p className="text-slate-300">{selected.root_cause_analysis}</p>
              <p className="text-slate-400">{selected.explanation}</p>
              <div className="pt-2">
                <span className="text-slate-400 font-semibold">Potential Impact: </span>
                <span>{selected.potential_impact}</span>
              </div>
            </div>

            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
              <h3 className="text-sm font-semibold text-slate-200">
                Verification Test Plan &amp; Rollback Procedure
              </h3>
              <ul className="list-disc list-inside text-slate-300 space-y-1">
                {selected.test_plan.map((tp, i) => (
                  <li key={i}>{tp}</li>
                ))}
              </ul>
              <div className="pt-2">
                <span className="text-slate-400 font-semibold">Rollback Procedure: </span>
                <span className="font-mono text-amber-300">
                  {selected.rollback_procedure}
                </span>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
              <div className="font-semibold text-rose-400 mb-2">
                Original Code ({activePatch.target_file_path})
              </div>
              <pre className="p-3 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto max-h-80 whitespace-pre-wrap">
                {activePatch.original_code}
              </pre>
            </div>
            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
              <div className="font-semibold text-emerald-400 mb-2">
                Proposed Remediated Code ({activePatch.target_file_path})
              </div>
              <pre className="p-3 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-200 overflow-x-auto max-h-80 whitespace-pre-wrap">
                {activePatch.proposed_code}
              </pre>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
            <div className="font-semibold text-sky-400 mb-2">
              Unified Git Diff
            </div>
            <pre className="p-3 rounded bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-200 overflow-x-auto whitespace-pre-wrap">
              {activePatch.unified_diff}
            </pre>
          </div>

          <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 flex flex-wrap items-center justify-between gap-4">
            <input
              type="text"
              value={comments}
              onChange={(e) => setComments(e.target.value)}
              placeholder="Reviewer audit note (bound to SHA-256 patch checksum)..."
              className="flex-1 min-w-[260px] px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
            />
            <div className="flex items-center gap-3">
              <button
                disabled={busy}
                onClick={handleApprove}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold text-white disabled:opacity-50"
              >
                1. Approve Checksum
              </button>
              <button
                disabled={busy}
                onClick={handleReject}
                className="px-4 py-2 rounded-lg bg-rose-600 hover:bg-rose-500 font-semibold text-white disabled:opacity-50"
              >
                Reject
              </button>
              <button
                disabled={busy || selected.status !== "APPROVED"}
                onClick={handleApplyAndVerify}
                className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white disabled:opacity-40"
              >
                2. Apply in Isolated Branch &amp; Run Regression Suite
              </button>
            </div>
          </div>

          {selected.regression_runs.length > 0 && (
            <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
              <h3 className="text-sm font-semibold text-emerald-400">
                Post-Patch Regression Verification Results
              </h3>
              {selected.regression_runs.map((rr) => (
                <div
                  key={rr.id}
                  className="p-3 rounded bg-slate-950 border border-slate-800 font-mono text-[11px]"
                >
                  Status: <strong>{rr.status}</strong> · Issue Resolved:{" "}
                  <strong>{String(rr.issue_resolved)}</strong> · Regressions Detected:{" "}
                  <strong>{String(rr.regressions_detected)}</strong> · Pre-Fix:{" "}
                  {JSON.stringify(rr.pre_fix_comparison)} → Post-Fix:{" "}
                  {JSON.stringify(rr.post_fix_comparison)}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-500 text-center">
          Select a remediation proposal to review its diff and approve/reject.
        </div>
      )}
    </div>
  );
};

