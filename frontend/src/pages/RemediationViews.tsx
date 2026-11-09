import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { CheckCircle2, FileCode2, Sparkles, XCircle } from "lucide-react";
import { qcApi } from "../services/api";
import type { Finding, RemediationProposal } from "../types/qc";

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
          Code Fix Proposals
        </h2>
        <p className="text-xs text-slate-400">
          Review generated code patches and open them in the Fix Approval Center.
        </p>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400">
              <th className="py-2 pr-3">Proposal</th>
              <th className="py-2 pr-3">Target File</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {proposals.map((p) => (
              <tr key={p.id} className="hover:bg-slate-800/30">
                <td className="py-2.5 pr-3 font-mono text-sky-400">
                  #{p.id.slice(0, 8)}
                </td>
                <td className="py-2.5 pr-3 font-mono font-semibold text-slate-200">
                  {p.affected_files.join(", ") || "—"}
                </td>
                <td className="py-2.5 pr-3">
                  <span
                    className={`px-2 py-0.5 rounded font-semibold text-[11px] ${
                      p.status === "VERIFIED" || p.status === "VERIFIED_RESOLVED"
                        ? "bg-emerald-500/15 text-emerald-400"
                        : p.status === "APPROVED"
                        ? "bg-sky-500/15 text-sky-400"
                        : p.status === "REJECTED"
                        ? "bg-rose-500/15 text-rose-400"
                        : "bg-amber-500/15 text-amber-400"
                    }`}
                  >
                    {p.status.replace(/_/g, " ")}
                  </span>
                </td>
                <td className="py-2.5 text-right">
                  <Link
                    to={`/approvals?proposalId=${p.id}`}
                    className="text-sky-400 hover:underline font-semibold"
                  >
                    Review &amp; Approve &rarr;
                  </Link>
                </td>
              </tr>
            ))}
            {proposals.length === 0 && (
              <tr>
                <td colSpan={4} className="py-6 text-center text-slate-500">
                  No fix proposals yet. Open Fix Approvals to generate fixes for your findings.
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
  const [findings, setFindings] = useState<Finding[]>([]);
  const [selectedId, setSelectedId] = useState<string>(
    searchParams.get("proposalId") || ""
  );
  const [selected, setSelected] = useState<RemediationProposal | null>(null);
  const [comments, setComments] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [statusBanner, setStatusBanner] = useState<{
    type: "success" | "error" | "info";
    text: string;
  } | null>(null);

  const loadList = async (preferredId?: string) => {
    const [list, allFindings] = await Promise.all([
      qcApi.listProposals(),
      qcApi.listFindings(),
    ]);
    setProposals(list);
    setFindings(allFindings);

    // Prefer URL param, then preferredId, then first AWAITING_APPROVAL proposal, then first proposal
    const awaiting = list.find((p) => p.status === "AWAITING_APPROVAL" || p.status === "APPROVED");
    const targetId =
      preferredId ||
      searchParams.get("proposalId") ||
      selectedId ||
      awaiting?.id ||
      list[0]?.id ||
      "";
    if (targetId) {
      setSelectedId(targetId);
      try {
        const detail = await qcApi.getProposal(targetId);
        setSelected(detail);
      } catch {
        setSelected(list[0] || null);
      }
    }
  };

  useEffect(() => {
    loadList();
  }, []);

  const handleSelectChange = async (id: string) => {
    setSelectedId(id);
    setStatusBanner(null);
    if (id) {
      const detail = await qcApi.getProposal(id);
      setSelected(detail);
    }
  };

  const handleGenerateProposalForFinding = async (findingId: string) => {
    setBusy(true);
    setStatusBanner({
      type: "info",
      text: "Generating code fix proposal...",
    });
    try {
      const created = await qcApi.createProposal(findingId);
      await loadList(created.id);
      setStatusBanner({
        type: "success",
        text: `Generated code fix proposal for '${created.affected_files.join(", ")}'. Review the changes below and click 'Approve & Apply Fix'.`,
      });
    } catch (err: any) {
      setStatusBanner({
        type: "error",
        text: `Could not generate fix: ${err.message}`,
      });
    } finally {
      setBusy(false);
    }
  };

  const handleApproveAndApply = async () => {
    if (!selected) return;
    setBusy(true);
    setStatusBanner(null);
    try {
      let current = selected;
      if (current.status !== "APPROVED" && current.status !== "VERIFIED") {
        current = await qcApi.approveProposal(
          current.id,
          current.active_patch_checksum,
          comments || "Approved via Fix Approval Center"
        );
      }
      if (current.status === "APPROVED") {
        current = await qcApi.applyProposal(current.id);
      }
      setSelected(current);
      await loadList(current.id);
      setStatusBanner({
        type: "success",
        text: `✓ Fix approved and applied in isolated branch (${
          current.patches?.[0]?.working_branch || "qc-remediation"
        }). Status: ${current.status}`,
      });
    } catch (err: any) {
      setStatusBanner({
        type: "error",
        text: `Approval/Apply error: ${err.message}`,
      });
    } finally {
      setBusy(false);
    }
  };

  const handleApproveOnly = async () => {
    if (!selected) return;
    setBusy(true);
    setStatusBanner(null);
    try {
      const updated = await qcApi.approveProposal(
        selected.id,
        selected.active_patch_checksum,
        comments || "Approved via Fix Approval Center"
      );
      setSelected(updated);
      await loadList(updated.id);
      setStatusBanner({
        type: "success",
        text: "Fix approved! Click 'Apply Fix Now' when ready to apply it.",
      });
    } catch (err: any) {
      setStatusBanner({
        type: "error",
        text: `Approval error: ${err.message}`,
      });
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    if (!selected) return;
    setBusy(true);
    setStatusBanner(null);
    try {
      const updated = await qcApi.rejectProposal(
        selected.id,
        selected.active_patch_checksum,
        comments || "Rejected by reviewer"
      );
      setSelected(updated);
      await loadList(updated.id);
      setStatusBanner({
        type: "info",
        text: "Fix proposal marked as Rejected.",
      });
    } catch (err: any) {
      setStatusBanner({
        type: "error",
        text: `Reject error: ${err.message}`,
      });
    } finally {
      setBusy(false);
    }
  };

  const activePatch = selected?.patches?.[0];
  const proposalFindingIds = new Set(proposals.map((p) => p.finding_id));
  const findingsWithoutProposal = findings.filter(
    (f) => f.file_path && !proposalFindingIds.has(f.id)
  );

  return (
    <div className="space-y-6 max-w-5xl mx-auto text-xs">
      {/* Simple Header + Proposal Selector */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100">
            Fix Approval Center
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Review side-by-side code fixes and approve them before any changes are applied.
          </p>
        </div>

        {proposals.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-slate-400 font-medium">Select Fix:</span>
            <select
              value={selectedId}
              onChange={(e) => handleSelectChange(e.target.value)}
              className="px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 font-medium"
            >
              {proposals.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.affected_files.join(", ")} — [{p.status.replace(/_/g, " ")}] (#
                  {p.id.slice(0, 6)})
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {statusBanner && (
        <div
          className={`p-3.5 rounded-xl border font-medium ${
            statusBanner.type === "success"
              ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300"
              : statusBanner.type === "error"
              ? "bg-rose-500/15 border-rose-500/40 text-rose-300"
              : "bg-sky-500/15 border-sky-500/40 text-sky-300"
          }`}
        >
          {statusBanner.text}
        </div>
      )}

      {selected && activePatch ? (
        <div className="space-y-5">
          {/* TOP ACTION BAR — Always Visible Above the Fold */}
          <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 flex flex-wrap items-center justify-between gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2.5">
                <FileCode2 className="w-4 h-4 text-sky-400" />
                <span className="text-sm font-bold font-mono text-slate-100">
                  {activePatch.target_file_path}
                </span>
                <span
                  className={`px-2.5 py-0.5 rounded text-[11px] font-bold ${
                    selected.status === "VERIFIED"
                      ? "bg-emerald-500/20 text-emerald-400"
                      : selected.status === "APPROVED"
                      ? "bg-sky-500/20 text-sky-400"
                      : selected.status === "REJECTED"
                      ? "bg-rose-500/20 text-rose-400"
                      : "bg-amber-500/20 text-amber-400"
                  }`}
                >
                  {selected.status.replace(/_/g, " ")}
                </span>
              </div>
              <p className="text-slate-300">{selected.root_cause_analysis}</p>
            </div>

            {/* Action Buttons right at the top */}
            <div className="flex flex-wrap items-center gap-2.5">
              {selected.status === "VERIFIED" ? (
                <div className="px-4 py-2 rounded-lg bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 font-bold flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Fix Approved &amp; Applied</span>
                </div>
              ) : (
                <>
                  <input
                    type="text"
                    value={comments}
                    onChange={(e) => setComments(e.target.value)}
                    placeholder="Optional approval note..."
                    className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 w-48"
                  />
                  <button
                    type="button"
                    disabled={busy}
                    onClick={handleApproveAndApply}
                    className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-bold text-white flex items-center gap-1.5 disabled:opacity-50"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    <span>
                      {selected.status === "APPROVED"
                        ? "Apply Fix Now"
                        : "Approve & Apply Fix"}
                    </span>
                  </button>
                  {selected.status !== "APPROVED" && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={handleApproveOnly}
                      className="px-3.5 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white disabled:opacity-50"
                    >
                      Approve Only
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy}
                    onClick={handleReject}
                    className="px-3.5 py-2 rounded-lg bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/40 font-semibold text-rose-300 flex items-center gap-1 disabled:opacity-50"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                    <span>Reject</span>
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Side-by-Side Before & After Code Comparison */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
              <div className="font-semibold text-rose-400">
                Before — Current Code ({activePatch.target_file_path})
              </div>
              <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-300 overflow-x-auto max-h-80 whitespace-pre-wrap">
                {activePatch.original_code || "(Empty file)"}
              </pre>
            </div>
            <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
              <div className="font-semibold text-emerald-400">
                After — Proposed Fix ({activePatch.target_file_path})
              </div>
              <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-200 overflow-x-auto max-h-80 whitespace-pre-wrap">
                {activePatch.proposed_code}
              </pre>
            </div>
          </div>

          {/* Unified Diff Summary */}
          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between">
              <span className="font-semibold text-sky-400">
                Exact Line Changes (Git Diff)
              </span>
              <span className="font-mono text-[11px] text-slate-400">
                Branch: {activePatch.working_branch || "qc-remediation"} · Syntax Valid:{" "}
                {activePatch.syntax_valid ? "Yes" : "No"}
              </span>
            </div>
            <pre className="p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px] text-slate-200 overflow-x-auto max-h-60 whitespace-pre-wrap">
              {activePatch.unified_diff}
            </pre>
          </div>
        </div>
      ) : (
        <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 text-slate-400 text-center">
          No fix proposal selected yet. Generate a code fix from the findings list below.
        </div>
      )}

      {/* Generate Code Fixes for Any Project Finding */}
      {findingsWithoutProposal.length > 0 && (
        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 space-y-3">
          <div className="flex items-center gap-2 font-bold text-sm text-slate-100">
            <Sparkles className="w-4 h-4 text-sky-400" />
            <span>
              Generate Code Fixes for Other Findings ({findingsWithoutProposal.length})
            </span>
          </div>
          <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
            {findingsWithoutProposal.slice(0, 15).map((f) => (
              <div
                key={f.id}
                className="p-3 rounded-xl bg-slate-950 border border-slate-800 flex flex-wrap items-center justify-between gap-3"
              >
                <div className="space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        f.severity === "CRITICAL" || f.severity === "HIGH"
                          ? "bg-rose-500/20 text-rose-400"
                          : f.severity === "MEDIUM"
                          ? "bg-amber-500/20 text-amber-400"
                          : "bg-sky-500/20 text-sky-400"
                      }`}
                    >
                      {f.severity}
                    </span>
                    <span className="font-semibold text-slate-200">{f.title}</span>
                    <span className="font-mono text-[11px] text-sky-400">
                      ({f.file_path}
                      {f.line_start ? `:${f.line_start}` : ""})
                    </span>
                  </div>
                  <p className="text-slate-400 text-[11px]">{f.description}</p>
                </div>

                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleGenerateProposalForFinding(f.id)}
                  className="px-3.5 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white shrink-0 disabled:opacity-50"
                >
                  Generate Fix &rarr;
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
