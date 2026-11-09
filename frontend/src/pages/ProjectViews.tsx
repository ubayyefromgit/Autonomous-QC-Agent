import React, { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { qcApi } from "../services/api";
import type { AuditSession, Finding, Project, RepositoryFile } from "../types/qc";

export const ProjectsPage: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [rootPath, setRootPath] = useState("C:\\Users\\BISON TECH\\Desktop\\GMI\\QC Agent");
  const [description, setDescription] = useState("");
  const [execMode, setExecMode] = useState("LOCAL");
  const [message, setMessage] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const navigate = useNavigate();

  const loadProjects = async () => {
    const list = await qcApi.listProjects();
    setProjects(list);
  };

  useEffect(() => {
    loadProjects();
  }, []);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(null);
    try {
      const created = await qcApi.createProject({
        name: name || "QC Intelligence Platform (Self-Audit)",
        root_path: rootPath,
        description: description || "Registered software repository",
        execution_mode: execMode,
      });
      setName("");
      setDescription("");
      await loadProjects();
      setMessage(`Registered project '${created.name}' (${created.id})`);
    } catch (err: any) {
      setMessage(`Error: ${err.message}`);
    }
  };

  const handleDiscover = async (projectId: string) => {
    setBusyId(projectId);
    setMessage(null);
    try {
      const res = await qcApi.discoverProject(projectId);
      await loadProjects();
      setMessage(
        `Discovery complete: ${res.files_persisted} files inventoried (${res.manifest.coverage.inspection_coverage_percent}% coverage).`
      );
    } catch (err: any) {
      setMessage(`Discovery error: ${err.message}`);
    } finally {
      setBusyId(null);
    }
  };

  const handleRunAudit = async (projectId: string, scope = "FULL") => {
    setBusyId(projectId);
    setMessage(null);
    try {
      const audit = await qcApi.startAudit(projectId, {
        audit_scope: scope,
        runner_mode: "LOCAL",
        run_immediately: true,
        run_synchronously: true,
      });
      await loadProjects();
      navigate(`/live-monitor?auditId=${audit.id}`);
    } catch (err: any) {
      setMessage(`Audit error: ${err.message}`);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">
          2. Registered Software Projects
        </h2>
        <p className="text-xs text-slate-400">
          Register authorized project directories or repositories for discovery and deterministic technical auditing
        </p>
      </div>

      {message && (
        <div className="p-3 rounded-lg bg-sky-500/10 border border-sky-500/30 text-xs text-sky-300">
          {message}
        </div>
      )}

      <form
        onSubmit={handleRegister}
        className="p-5 rounded-xl bg-slate-900 border border-slate-800 grid grid-cols-1 md:grid-cols-4 gap-4 items-end"
      >
        <div>
          <label className="block text-xs text-slate-400 mb-1">Project Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g., QC Intelligence Platform"
            className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs"
            required
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            Local Root Path
          </label>
          <input
            type="text"
            value={rootPath}
            onChange={(e) => setRootPath(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs font-mono"
            required
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">
            Default Runner Mode
          </label>
          <select
            value={execMode}
            onChange={(e) => setExecMode(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 text-xs"
          >
            <option value="LOCAL">LOCAL (Isolated Process Workspace)</option>
            <option value="DOCKER">DOCKER (Disposable Container Sandbox)</option>
          </select>
        </div>
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-xs font-semibold text-white"
        >
          Register Project
        </button>
      </form>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {projects.map((p) => {
          const cov = p.detected_stack?.coverage;
          return (
            <div
              key={p.id}
              className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3"
            >
              <div className="flex items-start justify-between">
                <div>
                  <Link
                    to={`/projects/${p.id}`}
                    className="text-base font-bold text-sky-400 hover:underline"
                  >
                    {p.name}
                  </Link>
                  <p className="text-xs font-mono text-slate-400 mt-0.5">
                    {p.root_path}
                  </p>
                </div>
                <span className="px-2 py-0.5 rounded bg-slate-800 text-xs font-semibold">
                  {p.last_release_gate || "UNAUDITED"}
                </span>
              </div>

              <div className="grid grid-cols-4 gap-2 text-xs bg-slate-950 p-3 rounded-lg border border-slate-800">
                <div>
                  <div className="text-slate-400">Audits</div>
                  <div className="font-semibold">{p.total_audits}</div>
                </div>
                <div>
                  <div className="text-slate-400">Last Score</div>
                  <div className="font-semibold">
                    {p.last_audit_score !== null ? `${p.last_audit_score}/100` : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-slate-400">Coverage</div>
                  <div className="font-semibold">
                    {cov ? `${cov.inspection_coverage_percent}%` : "—"}
                  </div>
                </div>
                <div>
                  <div className="text-slate-400">Open Issues</div>
                  <div className="font-semibold text-amber-400">
                    {p.unresolved_findings_count}
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5 text-[11px]">
                {(p.detected_stack?.languages || []).map((lang) => (
                  <span
                    key={lang}
                    className="px-2 py-0.5 rounded bg-sky-500/10 text-sky-300 border border-sky-500/20"
                  >
                    {lang}
                  </span>
                ))}
                {(p.detected_stack?.frameworks || []).map((fw) => (
                  <span
                    key={fw}
                    className="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                  >
                    {fw}
                  </span>
                ))}
              </div>

              <div className="flex items-center gap-2 pt-2">
                <button
                  disabled={busyId === p.id}
                  onClick={() => handleDiscover(p.id)}
                  className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs font-medium border border-slate-700"
                >
                  {busyId === p.id ? "Working..." : "1. Discover Files"}
                </button>
                <button
                  disabled={busyId === p.id}
                  onClick={() => handleRunAudit(p.id, "FULL")}
                  className="px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-xs font-semibold text-white"
                >
                  2. Run Full Audit
                </button>
                <Link
                  to={`/projects/${p.id}`}
                  className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-xs"
                >
                  3. Project Details →
                </Link>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export const ProjectDetailsPage: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [audits, setAudits] = useState<AuditSession[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);

  useEffect(() => {
    if (!projectId) return;
    Promise.all([
      qcApi.getProject(projectId),
      qcApi.listAudits(projectId),
      qcApi.listFindings({ project_id: projectId }),
    ]).then(([proj, auds, fnds]) => {
      setProject(proj);
      setAudits(auds);
      setFindings(fnds);
    });
  }, [projectId]);

  if (!project) {
    return <div className="text-xs text-slate-400">Loading project details...</div>;
  }

  const cov = project.detected_stack?.coverage;
  const latestAudit = audits[0];
  const dimensions = latestAudit?.scorecard?.dimensions || {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-100">
            3. Project Details — {project.name}
          </h2>
          <p className="text-xs font-mono text-slate-400">{project.root_path}</p>
        </div>
        <Link
          to={`/repository?projectId=${project.id}`}
          className="px-3 py-1.5 rounded-lg bg-sky-600 text-xs font-semibold text-white"
        >
          Open Repository File Explorer →
        </Link>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-xs">
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Repository Files</div>
          <div className="text-xl font-bold mt-1">
            {cov?.files_discovered ?? 0}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Inspection Coverage</div>
          <div className="text-xl font-bold text-emerald-400 mt-1">
            {cov?.inspection_coverage_percent ?? 0}%
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Last Audit Status</div>
          <div className="text-xl font-bold mt-1">
            {project.last_audit_status || "NONE"}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Quality Score</div>
          <div className="text-xl font-bold text-sky-400 mt-1">
            {project.last_audit_score !== null ? `${project.last_audit_score}/100` : "—"}
          </div>
        </div>
        <div className="p-4 rounded-xl bg-slate-900 border border-slate-800">
          <div className="text-slate-400">Unresolved Issues</div>
          <div className="text-xl font-bold text-amber-400 mt-1">
            {project.unresolved_findings_count}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
          <h3 className="text-sm font-semibold">Detected Architecture &amp; Stack</h3>
          <div className="text-xs space-y-2">
            <div>
              <span className="text-slate-400">Languages: </span>
              {(project.detected_stack?.languages || []).join(", ") || "Run Discovery"}
            </div>
            <div>
              <span className="text-slate-400">Frameworks: </span>
              {(project.detected_stack?.frameworks || []).join(", ") || "—"}
            </div>
            <div>
              <span className="text-slate-400">Databases: </span>
              {(project.detected_stack?.databases || []).join(", ") || "—"}
            </div>
            <div>
              <span className="text-slate-400">Infrastructure: </span>
              {(project.detected_stack?.infrastructure || []).join(", ") || "—"}
            </div>
            <div>
              <span className="text-slate-400">Test Frameworks: </span>
              {(project.detected_stack?.test_frameworks || []).join(", ") || "—"}
            </div>
          </div>
        </div>

        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-3">
          <h3 className="text-sm font-semibold">8-Dimension Quality Scorecard</h3>
          <div className="space-y-2 text-xs">
            {Object.entries(dimensions).map(([dim, info]: [string, any]) => (
              <div key={dim} className="flex items-center justify-between">
                <span className="text-slate-300">{dim}</span>
                <span className="font-mono">
                  {info.score}/100 (weight {Math.round(info.weight * 100)}%)
                </span>
              </div>
            ))}
            {Object.keys(dimensions).length === 0 && (
              <div className="text-slate-500">Run an audit to populate the scorecard.</div>
            )}
          </div>
        </div>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800">
        <h3 className="text-sm font-semibold mb-3">
          Audit History ({audits.length}) &amp; Unresolved Issues ({findings.length})
        </h3>
        <div className="space-y-2 text-xs">
          {audits.map((a) => (
            <div
              key={a.id}
              className="p-3 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-between"
            >
              <div>
                <span className="font-mono text-sky-400">{a.id.slice(0, 8)}</span> · Scope:{" "}
                <strong>{a.audit_scope}</strong> · Status: <strong>{a.status}</strong>
              </div>
              <div>
                Score: <strong>{a.overall_score ?? "—"}/100</strong> · Gate:{" "}
                <strong>{a.release_gate}</strong>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export const RepositoryExplorerPage: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [boundaryFilter, setBoundaryFilter] = useState<string>("");
  const [files, setFiles] = useState<RepositoryFile[]>([]);

  useEffect(() => {
    qcApi.listProjects().then((list) => {
      setProjects(list);
      if (list.length > 0) setSelectedProjectId(list[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selectedProjectId) return;
    qcApi
      .getProjectFiles(selectedProjectId, {
        inspection_status: statusFilter || undefined,
        boundary: boundaryFilter || undefined,
      })
      .then(setFiles);
  }, [selectedProjectId, statusFilter, boundaryFilter]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100">
            4. Repository Manifest &amp; File Coverage Explorer
          </h2>
          <p className="text-xs text-slate-400">
            Complete file-level inspection tracking with SHA-256 hashes, boundaries, and explicit exclusion reasons
          </p>
        </div>

        <div className="flex gap-2 text-xs">
          <select
            value={selectedProjectId}
            onChange={(e) => setSelectedProjectId(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700"
          >
            <option value="">All Statuses</option>
            <option value="INSPECTED">INSPECTED</option>
            <option value="EXCLUDED">EXCLUDED</option>
            <option value="PARTIALLY_INSPECTED">PARTIALLY_INSPECTED</option>
            <option value="UNSUPPORTED">UNSUPPORTED</option>
            <option value="FAILED">FAILED</option>
            <option value="PENDING">PENDING</option>
          </select>

          <select
            value={boundaryFilter}
            onChange={(e) => setBoundaryFilter(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-700"
          >
            <option value="">All Boundaries</option>
            <option value="BACKEND">BACKEND</option>
            <option value="FRONTEND">FRONTEND</option>
            <option value="DATABASE">DATABASE</option>
            <option value="TESTS">TESTS</option>
            <option value="SHARED">SHARED</option>
            <option value="CONFIG">CONFIG</option>
          </select>
        </div>
      </div>

      <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-800 text-slate-400">
              <th className="py-2 pr-3">Relative Path</th>
              <th className="py-2 pr-3">Language</th>
              <th className="py-2 pr-3">Boundary</th>
              <th className="py-2 pr-3">Lines / Size</th>
              <th className="py-2 pr-3">Status</th>
              <th className="py-2 pr-3">Reason / Notes</th>
              <th className="py-2">SHA-256</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {files.map((f) => (
              <tr key={f.id} className="hover:bg-slate-800/30">
                <td className="py-2 pr-3 font-mono text-sky-300">
                  {f.relative_path}
                  {f.is_entrypoint && (
                    <span className="ml-2 px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 text-[10px]">
                      ENTRYPOINT
                    </span>
                  )}
                </td>
                <td className="py-2 pr-3">{f.language}</td>
                <td className="py-2 pr-3">{f.component_boundary}</td>
                <td className="py-2 pr-3">
                  {f.line_count}L / {f.size_bytes}B
                </td>
                <td className="py-2 pr-3">
                  <span
                    className={`px-2 py-0.5 rounded font-semibold ${
                      f.inspection_status === "INSPECTED"
                        ? "bg-emerald-500/15 text-emerald-300"
                        : f.inspection_status === "EXCLUDED"
                        ? "bg-slate-800 text-slate-400"
                        : "bg-amber-500/15 text-amber-300"
                    }`}
                  >
                    {f.inspection_status}
                  </span>
                </td>
                <td className="py-2 pr-3 text-slate-400">
                  {f.status_reason || "—"}
                </td>
                <td className="py-2 font-mono text-slate-500">
                  {f.sha256_hash ? f.sha256_hash.slice(0, 12) : "—"}
                </td>
              </tr>
            ))}
            {files.length === 0 && (
              <tr>
                <td colSpan={7} className="py-6 text-center text-slate-500">
                  No repository file records found. Run Discovery on a project first.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

