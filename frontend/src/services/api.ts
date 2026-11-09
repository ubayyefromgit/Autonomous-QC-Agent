import type {
  AuditProgress,
  AuditSession,
  Evidence,
  Finding,
  OverviewTelemetry,
  Project,
  RemediationProposal,
  ReportRecord,
  RepositoryFile,
  TestRun,
} from "../types/qc";

const API_BASE = "/api/v1";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem("qc_access_token");
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const resp = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({ message: resp.statusText }));
    throw new Error(errBody.message || errBody.detail || `HTTP ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

async function uploadMultipart<T>(path: string, formData: FormData): Promise<T> {
  const token = localStorage.getItem("qc_access_token");
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const resp = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!resp.ok) {
    const errBody = await resp.json().catch(() => ({ message: resp.statusText }));
    throw new Error(errBody.message || errBody.detail || `HTTP ${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export const qcApi = {
  getOverview: () => request<OverviewTelemetry>("/system/overview"),
  getHealth: () => request<Record<string, any>>("/system/health"),
  getAgents: () => request<{ agents: any[]; total_registered: number }>("/system/agents"),
  getExecutors: () => request<Record<string, any>>("/system/executors"),
  getAgentActivity: () => request<{ executions: any[]; events: any[] }>("/system/agent-activity"),
  getRuntimeConfig: () => request<Record<string, any>>("/system/runtime-config"),
  updateRuntimeConfig: (payload: Record<string, any>) =>
    request<Record<string, any>>("/system/runtime-config", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  pickLocalFolder: () =>
    request<{ selected_path: string; cancelled: boolean }>("/system/pick-folder", {
      method: "POST",
    }),

  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (payload: {
    name: string;
    description?: string;
    root_path: string;
    repository_url?: string;
    execution_mode?: string;
  }) =>
    request<Project>("/projects", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadProjectZip: (formData: FormData) =>
    uploadMultipart<Project>("/projects/upload-zip", formData),
  uploadProjectFiles: (formData: FormData) =>
    uploadMultipart<Project>("/projects/upload-files", formData),
  cloneGitProject: (payload: {
    repository_url: string;
    name?: string;
    description?: string;
    branch?: string;
    git_token?: string;
    execution_mode?: string;
    env_content?: string;
  }) =>
    request<Project>("/projects/clone-git", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getProjectReadiness: (id: string) =>
    request<Record<string, any>>(`/projects/${id}/readiness`),
  saveProjectEnv: (id: string, envContent: string) =>
    request<{ project_id: string; env_path: string; status: string }>(
      `/projects/${id}/env`,
      {
        method: "POST",
        body: JSON.stringify({ env_content: envContent }),
      }
    ),
  deleteProject: (id: string) =>
    request<{ id: string; status: string }>(`/projects/${id}`, {
      method: "DELETE",
    }),
  discoverProject: (id: string) =>
    request<{ project_id: string; session_id: string; manifest: any; files_persisted: number }>(
      `/projects/${id}/discover`,
      { method: "POST" }
    ),
  getProjectManifest: (id: string) =>
    request<{ project_id: string; session_id: string | null; manifest: any }>(
      `/projects/${id}/manifest`
    ),
  getProjectFiles: (
    id: string,
    params?: { inspection_status?: string; language?: string; boundary?: string }
  ) => {
    const qs = new URLSearchParams();
    if (params?.inspection_status) qs.set("inspection_status", params.inspection_status);
    if (params?.language) qs.set("language", params.language);
    if (params?.boundary) qs.set("boundary", params.boundary);
    const qStr = qs.toString() ? `?${qs.toString()}` : "";
    return request<RepositoryFile[]>(`/projects/${id}/files${qStr}`);
  },

  startAudit: (
    projectId: string,
    payload: {
      audit_scope: string;
      runner_mode: string;
      run_immediately?: boolean;
      run_synchronously?: boolean;
    }
  ) =>
    request<AuditSession>(`/projects/${projectId}/audits`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listAudits: (projectId?: string) =>
    request<AuditSession[]>(projectId ? `/audits?project_id=${projectId}` : "/audits"),
  getAudit: (auditId: string) => request<AuditSession>(`/audits/${auditId}`),
  getAuditProgress: (auditId: string) =>
    request<AuditProgress>(`/audits/${auditId}/progress`),
  cancelAudit: (auditId: string) =>
    request<AuditSession>(`/audits/${auditId}/cancel`, { method: "POST" }),
  resumeAudit: (auditId: string) =>
    request<AuditSession>(`/audits/${auditId}/resume?run_synchronously=true`, {
      method: "POST",
    }),
  getAuditTestRuns: (auditId: string) =>
    request<TestRun[]>(`/audits/${auditId}/test-runs`),

  listFindings: (params?: {
    project_id?: string;
    session_id?: string;
    severity?: string;
    category?: string;
    agent_name?: string;
    verification_status?: string;
    lifecycle_status?: string;
  }) => {
    const qs = new URLSearchParams();
    Object.entries(params || {}).forEach(([k, v]) => {
      if (v) qs.set(k, v);
    });
    const qStr = qs.toString() ? `?${qs.toString()}` : "";
    return request<Finding[]>(`/findings${qStr}`);
  },
  getFinding: (findingId: string) => request<Finding>(`/findings/${findingId}`),
  getFindingEvidence: (findingId: string) =>
    request<Evidence[]>(`/findings/${findingId}/evidence`),
  listAllEvidence: (sessionId?: string) =>
    request<Evidence[]>(sessionId ? `/evidence?session_id=${sessionId}` : "/evidence"),

  createProposal: (findingId: string, proposedCodeOverride?: string) =>
    request<RemediationProposal>(`/findings/${findingId}/proposals`, {
      method: "POST",
      body: JSON.stringify({
        proposed_code_override: proposedCodeOverride || null,
      }),
    }),
  listProposals: (sessionId?: string) =>
    request<RemediationProposal[]>(
      sessionId ? `/remediation?session_id=${sessionId}` : "/remediation"
    ),
  getProposal: (proposalId: string) =>
    request<RemediationProposal>(`/remediation/${proposalId}`),
  approveProposal: (proposalId: string, patchChecksum: string, comments?: string) =>
    request<RemediationProposal>(`/remediation/${proposalId}/approve`, {
      method: "POST",
      body: JSON.stringify({
        patch_checksum: patchChecksum,
        reviewer_name: "Principal QC Architect",
        comments: comments || "Approved via QC Approval Center",
      }),
    }),
  rejectProposal: (proposalId: string, patchChecksum: string, comments?: string) =>
    request<RemediationProposal>(`/remediation/${proposalId}/reject`, {
      method: "POST",
      body: JSON.stringify({
        patch_checksum: patchChecksum,
        reviewer_name: "Principal QC Architect",
        comments: comments || "Rejected via QC Approval Center",
      }),
    }),
  applyProposal: (proposalId: string) =>
    request<RemediationProposal>(`/remediation/${proposalId}/apply`, {
      method: "POST",
    }),

  generateReport: (auditId: string, format: "HTML" | "PDF" = "HTML") =>
    request<ReportRecord>(`/audits/${auditId}/reports`, {
      method: "POST",
      body: JSON.stringify({ report_format: format }),
    }),
  listReports: () => request<ReportRecord[]>("/reports"),
};

