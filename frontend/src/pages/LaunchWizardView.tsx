import React, { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  FileText,
  FolderOpen,
  GitBranch,
  HelpCircle,
  KeyRound,
  MessageSquare,
  Play,
  RefreshCw,
  Sparkles,
  Terminal,
  UploadCloud,
} from "lucide-react";
import { qcApi } from "../services/api";
import type { AuditSession, Finding, Project } from "../types/qc";

function formatRunTimestamp(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function computeRunDuration(started?: string | null, completed?: string | null): string {
  if (!started || !completed) return "—";
  const s = new Date(started).getTime();
  const c = new Date(completed).getTime();
  if (isNaN(s) || isNaN(c) || c < s) return "—";
  const sec = ((c - s) / 1000).toFixed(1);
  return `${sec}s`;
}

export const LaunchWizardPage: React.FC = () => {
  const navigate = useNavigate();

  // Collapsible drawers for minimal UI
  const [showInstructions, setShowInstructions] = useState(false);
  const [showApiKeys, setShowApiKeys] = useState(false);
  const [showEnvEditor, setShowEnvEditor] = useState(false);
  const [showReadiness, setShowReadiness] = useState(false);

  // Runtime config & instructions state
  const [runtimeConfig, setRuntimeConfig] = useState<Record<string, any> | null>(null);
  const [llmProvider, setLlmProvider] = useState("ollama");
  const [ollamaUrl, setOllamaUrl] = useState("http://127.0.0.1:11434");
  const [geminiKey, setGeminiKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [githubToken, setGithubToken] = useState("");
  const [runnerMode, setRunnerMode] = useState("LOCAL");

  // Dynamic AI Models state for the selected provider & API key
  const [selectedModel, setSelectedModel] = useState("qwen2.5-coder:7b");
  const [providerModels, setProviderModels] = useState<{ id: string; label: string }[]>([]);
  const [modelsSource, setModelsSource] = useState<string>("default_catalog");
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [fetchingModels, setFetchingModels] = useState(false);

  // Project intake tab state ("zip" | "files" | "folder" | "git")
  const [intakeTab, setIntakeTab] = useState<"zip" | "files" | "folder" | "git">("zip");
  const [projectName, setProjectName] = useState("");
  const [auditScope, setAuditScope] = useState("FULL");
  const [projectDocumentation, setProjectDocumentation] = useState("");
  const [docFileNames, setDocFileNames] = useState<string[]>([]);
  const docFileInputRef = useRef<HTMLInputElement | null>(null);
  const [customInstructions, setCustomInstructions] = useState("");
  const [targetEnvContent, setTargetEnvContent] = useState("");
  const [generatingFixId, setGeneratingFixId] = useState<string | null>(null);

  // Instant Readable Audit Result & Run History state
  const [recentAudits, setRecentAudits] = useState<AuditSession[]>([]);
  const [activeAuditResult, setActiveAuditResult] = useState<AuditSession | null>(null);
  const [activeAuditFindings, setActiveAuditFindings] = useState<Finding[]>([]);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  // ZIP / Files / Folder / Git state
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [multiFiles, setMultiFiles] = useState<FileList | null>(null);
  const [folderFiles, setFolderFiles] = useState<FileList | null>(null);
  const [localFolderPath, setLocalFolderPath] = useState("");
  const [browsingFolder, setBrowsingFolder] = useState(false);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const [gitRepoUrl, setGitRepoUrl] = useState("");
  const [gitBranch, setGitBranch] = useState("main");
  const [gitPrivateToken, setGitPrivateToken] = useState("");

  // Project Readiness Advisor state
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedReadinessProjectId, setSelectedReadinessProjectId] = useState<string>("");
  const [readinessData, setReadinessData] = useState<Record<string, any> | null>(null);
  const [editableProjectEnv, setEditableProjectEnv] = useState<string>("");

  const [busy, setBusy] = useState(false);
  const [statusBanner, setStatusBanner] = useState<{
    type: "success" | "error" | "info";
    text: string;
  } | null>(null);

  const fetchModelsForProvider = async (
    prov: string,
    overrideKey?: string,
    overrideOllamaUrl?: string
  ) => {
    setFetchingModels(true);
    setModelsError(null);
    try {
      const keyToUse =
        overrideKey !== undefined
          ? overrideKey
          : prov === "gemini"
          ? geminiKey
          : prov === "openai"
          ? openaiKey
          : undefined;
      const res = await qcApi.fetchProviderModels({
        provider: prov,
        api_key: keyToUse || undefined,
        ollama_base_url: overrideOllamaUrl || ollamaUrl,
      });
      setProviderModels(res.models || []);
      setModelsSource(res.source || "default_catalog");
      setModelsError(res.error || null);
      if (res.models && res.models.length > 0) {
        const exists = res.models.some((m) => m.id === res.selected_model);
        setSelectedModel(exists ? res.selected_model : res.models[0].id);
      } else if (res.selected_model) {
        setSelectedModel(res.selected_model);
      }
    } catch (err: any) {
      setModelsError(err.message);
    } finally {
      setFetchingModels(false);
    }
  };

  const loadReadableResultForAudit = async (audit: AuditSession, scroll = false) => {
    setActiveAuditResult(audit);
    try {
      const fList = await qcApi.listFindings({ session_id: audit.id });
      setActiveAuditFindings(fList);
    } catch {
      setActiveAuditFindings([]);
    }
    if (scroll) {
      setTimeout(() => {
        resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 150);
    }
  };

  const loadInitial = async () => {
    const [rc, projs, auditsList] = await Promise.all([
      qcApi.getRuntimeConfig(),
      qcApi.listProjects(),
      qcApi.listAudits(),
    ]);
    setRuntimeConfig(rc);
    setRecentAudits(auditsList);
    if (auditsList.length > 0 && !activeAuditResult) {
      await loadReadableResultForAudit(auditsList[0], false);
    }
    if (rc.ai_config) {
      const initialProv = rc.ai_config.default_llm_provider || "ollama";
      setLlmProvider(initialProv);
      setOllamaUrl(rc.ai_config.ollama_base_url || "http://127.0.0.1:11434");
      setRunnerMode(rc.ai_config.default_runner_mode || "LOCAL");
      await fetchModelsForProvider(
        initialProv,
        undefined,
        rc.ai_config.ollama_base_url || "http://127.0.0.1:11434"
      );
    }
    setProjects(projs);
    if (projs.length > 0 && !selectedReadinessProjectId) {
      setSelectedReadinessProjectId(projs[0].id);
    }
  };

  useEffect(() => {
    loadInitial();
  }, []);

  useEffect(() => {
    if (!selectedReadinessProjectId) return;
    qcApi.getProjectReadiness(selectedReadinessProjectId).then((rd) => {
      setReadinessData(rd);
      setEditableProjectEnv(rd.current_env_content || "");
    });
  }, [selectedReadinessProjectId]);

  const handleSaveApiKeys = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setStatusBanner(null);
    try {
      const payload: Record<string, any> = {
        default_llm_provider: llmProvider,
        ollama_base_url: ollamaUrl,
        gemini_api_key: geminiKey || undefined,
        openai_api_key: openaiKey || undefined,
        github_token: githubToken || undefined,
        default_runner_mode: runnerMode,
      };
      if (llmProvider === "gemini") {
        payload.gemini_model = selectedModel;
      } else if (llmProvider === "openai") {
        payload.openai_model = selectedModel;
      } else {
        payload.ollama_model = selectedModel;
      }
      const updated = await qcApi.updateRuntimeConfig(payload);
      setRuntimeConfig(updated);
      setGeminiKey("");
      setOpenaiKey("");
      setGithubToken("");
      setStatusBanner({
        type: "success",
        text: `AI Provider (${llmProvider.toUpperCase()}) and Model (${selectedModel}) saved.`,
      });
      setShowApiKeys(false);
    } catch (err: any) {
      setStatusBanner({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const handlePickNativeFolder = async () => {
    setBrowsingFolder(true);
    setStatusBanner({
      type: "info",
      text: "Opening folder browser dialog... (Check your taskbar if it opens behind the window, or use 'Pick in Browser')",
    });
    try {
      const res = await qcApi.pickLocalFolder();
      if (!res.cancelled && res.selected_path) {
        setFolderFiles(null);
        setLocalFolderPath(res.selected_path);
        if (!projectName) {
          const parts = res.selected_path.replace(/\\/g, "/").split("/");
          setProjectName(parts[parts.length - 1] || "Local Project");
        }
        setStatusBanner({
          type: "success",
          text: `Selected folder: ${res.selected_path}`,
        });
      } else {
        setStatusBanner(null);
      }
    } catch (err: any) {
      setStatusBanner({ type: "error", text: err.message });
    } finally {
      setBrowsingFolder(false);
    }
  };

  const handleBrowserFolderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setFolderFiles(files);
    const firstRel = (files[0] as any).webkitRelativePath || files[0].name || "SelectedFolder";
    const topFolder = firstRel.split("/")[0] || "SelectedFolder";
    setLocalFolderPath(`${topFolder} (${files.length} files selected via browser)`);
    if (!projectName) {
      setProjectName(topFolder);
    }
    setStatusBanner({
      type: "success",
      text: `Selected folder '${topFolder}' (${files.length} files) via browser.`,
    });
  };

  const handleDocFilesUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    const names: string[] = [];
    const chunks: string[] = [];
    for (const file of Array.from(files)) {
      names.push(file.name);
      try {
        const rawText = await file.text();
        // Clean out non-printable control characters if user uploaded a binary doc/pdf
        const cleaned = rawText
          .replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]+/g, " ")
          .trim()
          .slice(0, 12000);
        if (cleaned.length > 20) {
          chunks.push(`--- Documentation File: ${file.name} ---\n${cleaned}`);
        } else {
          chunks.push(
            `--- Documentation File: ${file.name} (${Math.round(file.size / 1024)} KB) ---`
          );
        }
      } catch {
        chunks.push(
          `--- Documentation File: ${file.name} (${Math.round(file.size / 1024)} KB) ---`
        );
      }
    }
    setDocFileNames((prev) => Array.from(new Set([...prev, ...names])));
    setProjectDocumentation((prev) =>
      [prev.trim(), ...chunks].filter(Boolean).join("\n\n")
    );
    setStatusBanner({
      type: "success",
      text: `Loaded ${names.length} project documentation file(s): ${names.join(", ")}`,
    });
  };

  const handleOpenFixApproval = async (findingId: string) => {
    setGeneratingFixId(findingId);
    try {
      const proposal = await qcApi.createProposal(findingId);
      navigate(`/approvals?proposalId=${proposal.id}`);
    } catch (err: any) {
      setStatusBanner({
        type: "error",
        text: `Could not generate code fix proposal: ${err.message}`,
      });
    } finally {
      setGeneratingFixId(null);
    }
  };

  const handleProjectIntake = async (runAuditImmediately: boolean) => {
    setBusy(true);
    setStatusBanner(null);
    try {
      if (runAuditImmediately && !projectDocumentation.trim()) {
        throw new Error(
          "Project Details & Documentation is required before running an audit. Please upload your project documentation file(s) (README, architecture, requirements) or enter the project details in Step 2 below."
        );
      }

      let createdProject: Project;
      const docSummary =
        projectDocumentation.trim().slice(0, 1000) ||
        "Project registered via Launch Hub";

      if (intakeTab === "zip") {
        if (!zipFile) {
          throw new Error("Please select a .zip archive file to upload.");
        }
        const fd = new FormData();
        fd.append("file", zipFile);
        fd.append("name", projectName || zipFile.name.replace(/\.zip$/i, ""));
        fd.append("description", docSummary);
        fd.append("execution_mode", runnerMode);
        fd.append("env_content", targetEnvContent);
        createdProject = await qcApi.uploadProjectZip(fd);
      } else if (intakeTab === "files") {
        if (!multiFiles || multiFiles.length === 0) {
          throw new Error("Please select one or more source files to upload.");
        }
        const fd = new FormData();
        const relPaths: string[] = [];
        Array.from(multiFiles).forEach((f) => {
          fd.append("files", f);
          relPaths.push((f as any).webkitRelativePath || f.name);
        });
        fd.append("relative_paths", JSON.stringify(relPaths));
        fd.append("name", projectName || "Uploaded Source Project");
        fd.append("description", docSummary);
        fd.append("execution_mode", runnerMode);
        fd.append("env_content", targetEnvContent);
        createdProject = await qcApi.uploadProjectFiles(fd);
      } else if (intakeTab === "folder") {
        if (folderFiles && folderFiles.length > 0) {
          const fd = new FormData();
          const relPaths: string[] = [];
          Array.from(folderFiles).forEach((f) => {
            fd.append("files", f);
            relPaths.push((f as any).webkitRelativePath || f.name);
          });
          fd.append("relative_paths", JSON.stringify(relPaths));
          fd.append("name", projectName || "Local Folder Project");
          fd.append("description", docSummary);
          fd.append("execution_mode", runnerMode);
          fd.append("env_content", targetEnvContent);
          createdProject = await qcApi.uploadProjectFiles(fd);
        } else {
          if (!localFolderPath.trim()) {
            throw new Error("Please enter or browse a valid local folder path.");
          }
          const parts = localFolderPath.replace(/\\/g, "/").split("/");
          createdProject = await qcApi.createProject({
            name: projectName || parts[parts.length - 1] || "Local Software Project",
            root_path: localFolderPath.trim(),
            description: docSummary,
            execution_mode: runnerMode,
          });
          if (targetEnvContent.trim()) {
            await qcApi.saveProjectEnv(createdProject.id, targetEnvContent);
          }
        }
      } else {
        if (!gitRepoUrl.trim()) {
          throw new Error("Please enter a Git repository URL (e.g., https://github.com/org/repo.git).");
        }
        createdProject = await qcApi.cloneGitProject({
          repository_url: gitRepoUrl.trim(),
          name: projectName || undefined,
          branch: gitBranch || "main",
          git_token: gitPrivateToken || undefined,
          execution_mode: runnerMode,
          env_content: targetEnvContent || undefined,
        });
      }

      await qcApi.discoverProject(createdProject.id);
      const updatedProjects = await qcApi.listProjects();
      setProjects(updatedProjects);
      setSelectedReadinessProjectId(createdProject.id);

      if (runAuditImmediately) {
        const audit = await qcApi.startAudit(createdProject.id, {
          audit_scope: auditScope,
          runner_mode: runnerMode,
          custom_instructions: customInstructions.trim() || undefined,
          project_documentation: projectDocumentation.trim(),
          run_immediately: true,
          run_synchronously: true,
        });
        const updatedAudits = await qcApi.listAudits();
        setRecentAudits(updatedAudits);
        await loadReadableResultForAudit(audit, true);
        setStatusBanner({
          type: "success",
          text: `Audit completed for '${createdProject.name}' (Score: ${audit.overall_score ?? "—"}/100). View your readable insights & file coverage below!`,
        });
      } else {
        const rd = await qcApi.getProjectReadiness(createdProject.id);
        setReadinessData(rd);
        setEditableProjectEnv(rd.current_env_content || "");
        setShowReadiness(true);
        setStatusBanner({
          type: "success",
          text: `Project '${createdProject.name}' ready. Review its setup checklist below.`,
        });
      }
    } catch (err: any) {
      setStatusBanner({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const handleSaveTargetProjectEnv = async () => {
    if (!selectedReadinessProjectId) return;
    setBusy(true);
    try {
      await qcApi.saveProjectEnv(selectedReadinessProjectId, editableProjectEnv);
      const rd = await qcApi.getProjectReadiness(selectedReadinessProjectId);
      setReadinessData(rd);
      setStatusBanner({
        type: "success",
        text: "Saved .env file to target project.",
      });
    } catch (err: any) {
      setStatusBanner({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const tools = runtimeConfig?.system_tools || [];
  const steps = runtimeConfig?.instructions?.quick_start_steps || [];
  const aiCfg = runtimeConfig?.ai_config || {};
  const installedCount = tools.filter((t: any) => t.installed).length;

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Minimal Header + Quick Action Pills */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100">
            New Project Audit
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Upload your code, verify optional API keys or setup instructions, and launch an autonomous QC audit.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button
            type="button"
            onClick={() => setShowInstructions((v) => !v)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-200 font-medium"
          >
            <HelpCircle className="w-3.5 h-3.5 text-sky-400" />
            <span>
              Instructions &amp; Tools ({installedCount}/{tools.length})
            </span>
            {showInstructions ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>

          <button
            type="button"
            onClick={() => setShowApiKeys((v) => !v)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-200 font-medium"
          >
            <KeyRound className="w-3.5 h-3.5 text-amber-400" />
            <span>
              AI: {llmProvider.toUpperCase()} ({selectedModel})
            </span>
            {showApiKeys ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>

      {statusBanner && (
        <div
          className={`p-3.5 rounded-xl border text-xs font-medium ${
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

      {/* Collapsible Drawer 1: Instructions & System Tools */}
      {showInstructions && (
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4 text-xs">
          <div className="font-bold text-sm text-slate-100">
            How to Run an Audit &amp; What Needs Manual Setup
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {steps.map((s: any) => (
              <div
                key={s.step}
                className="p-3 rounded-lg bg-slate-950 border border-slate-800 space-y-1"
              >
                <div className="font-semibold text-sky-400">{s.title}</div>
                <p className="text-slate-300">{s.summary}</p>
                <p className="text-[11px] text-amber-400 pt-1">
                  <strong>Manual Setup:</strong> {s.manual_action_required}
                </p>
              </div>
            ))}
          </div>

          <div className="pt-2">
            <div className="font-semibold text-slate-200 mb-2">
              System Tools Status
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {tools.map((t: any) => (
                <div
                  key={t.name}
                  className="p-2.5 rounded-lg bg-slate-950 border border-slate-800 flex flex-col justify-between"
                  title={t.installed ? t.version : `Install: ${t.install_command}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-semibold text-slate-200">
                      {t.name}
                    </span>
                    <span
                      className={
                        t.installed ? "text-emerald-400" : "text-amber-400"
                      }
                    >
                      {t.installed ? "✓" : "!"}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-400 mt-1 truncate">
                    {t.installed ? "Installed" : t.install_command}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Collapsible Drawer 2: API Keys & AI Provider */}
      {showApiKeys && (
        <form
          onSubmit={handleSaveApiKeys}
          className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4 text-xs"
        >
          <div className="flex items-center justify-between">
            <div>
              <div className="font-bold text-sm text-slate-100">
                AI Provider &amp; Optional API Keys
              </div>
              <p className="text-slate-400">
                Local mode requires no API keys. Select Gemini or OpenAI only if you want cloud LLM analysis.
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-slate-400 mb-1">AI Provider</label>
              <select
                value={llmProvider}
                onChange={(e) => {
                  const nextProv = e.target.value;
                  setLlmProvider(nextProv);
                  fetchModelsForProvider(nextProv);
                }}
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
              >
                <option value="ollama">Local / Deterministic (Free, No Key)</option>
                <option value="gemini">Google Gemini (Requires Key)</option>
                <option value="openai">OpenAI (Requires Key)</option>
              </select>
            </div>

            {llmProvider === "ollama" && (
              <div>
                <label className="block text-slate-400 mb-1">
                  Local Ollama URL (Optional)
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={ollamaUrl}
                    onChange={(e) => setOllamaUrl(e.target.value)}
                    className="flex-1 px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
                  />
                  <button
                    type="button"
                    disabled={fetchingModels}
                    onClick={() => fetchModelsForProvider("ollama", undefined, ollamaUrl)}
                    className="px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 font-semibold text-slate-200 flex items-center gap-1.5 shrink-0"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${fetchingModels ? "animate-spin" : ""}`} />
                    <span>Fetch Models</span>
                  </button>
                </div>
              </div>
            )}

            {llmProvider === "gemini" && (
              <div>
                <label className="block text-slate-400 mb-1">
                  Google Gemini API Key
                </label>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={geminiKey}
                    onChange={(e) => setGeminiKey(e.target.value)}
                    placeholder={
                      aiCfg.has_gemini_key
                        ? `Saved (${aiCfg.gemini_key_masked})`
                        : "Enter AIzaSy..."
                    }
                    className="flex-1 px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
                  />
                  <button
                    type="button"
                    disabled={fetchingModels}
                    onClick={() => fetchModelsForProvider("gemini", geminiKey)}
                    className="px-3 py-2 rounded-lg bg-sky-600/20 hover:bg-sky-600/30 border border-sky-500/40 font-semibold text-sky-300 flex items-center gap-1.5 shrink-0"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${fetchingModels ? "animate-spin" : ""}`} />
                    <span>Fetch Models</span>
                  </button>
                </div>
              </div>
            )}

            {llmProvider === "openai" && (
              <div>
                <label className="block text-slate-400 mb-1">
                  OpenAI API Key
                </label>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={openaiKey}
                    onChange={(e) => setOpenaiKey(e.target.value)}
                    placeholder={
                      aiCfg.has_openai_key
                        ? `Saved (${aiCfg.openai_key_masked})`
                        : "Enter sk-..."
                    }
                    className="flex-1 px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
                  />
                  <button
                    type="button"
                    disabled={fetchingModels}
                    onClick={() => fetchModelsForProvider("openai", openaiKey)}
                    className="px-3 py-2 rounded-lg bg-sky-600/20 hover:bg-sky-600/30 border border-sky-500/40 font-semibold text-sky-300 flex items-center gap-1.5 shrink-0"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${fetchingModels ? "animate-spin" : ""}`} />
                    <span>Fetch Models</span>
                  </button>
                </div>
              </div>
            )}

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-slate-400">
                  Select Model ({llmProvider.toUpperCase()})
                </label>
                <span
                  className={`text-[10px] font-semibold ${
                    modelsSource === "live_api" ? "text-emerald-400" : "text-slate-400"
                  }`}
                >
                  {modelsSource === "live_api"
                    ? `✓ Live API (${providerModels.length} available)`
                    : `Default List (${providerModels.length})`}
                </span>
              </div>
              <select
                value={selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
              >
                {providerModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
              {modelsError && (
                <div className="text-[11px] text-amber-400 mt-1">
                  {modelsError}
                </div>
              )}
            </div>

            <div>
              <label className="block text-slate-400 mb-1">
                GitHub Token (Private Repos Only)
              </label>
              <input
                type="password"
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                placeholder={
                  aiCfg.has_github_token
                    ? `Saved (${aiCfg.github_token_masked})`
                    : "Optional (ghp_...)"
                }
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={busy}
              className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white"
            >
              Save Settings
            </button>
          </div>
        </form>
      )}

      {/* Main Minimal Card: Project Source Intake */}
      <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-5 text-xs">
        {/* Clean 4-Tab Selector */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 p-1 rounded-xl bg-slate-950 border border-slate-800">
          {[
            { id: "zip", label: "Upload .ZIP", icon: UploadCloud },
            { id: "files", label: "Upload Files", icon: UploadCloud },
            { id: "folder", label: "Local Folder", icon: FolderOpen },
            { id: "git", label: "Git URL", icon: GitBranch },
          ].map((tab) => {
            const Icon = tab.icon;
            const active = intakeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setIntakeTab(tab.id as any)}
                className={`flex items-center justify-center gap-2 py-2.5 px-3 rounded-lg font-semibold transition-all ${
                  active
                    ? "bg-sky-600 text-white shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                <Icon className="w-4 h-4" />
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Source Input Area */}
        {intakeTab === "zip" && (
          <div className="p-8 rounded-xl bg-slate-950 border border-dashed border-slate-700 text-center space-y-3">
            <UploadCloud className="w-8 h-8 text-sky-400 mx-auto" />
            <div className="text-sm font-semibold text-slate-200">
              Select a `.zip` Archive of Your Project
            </div>
            <input
              type="file"
              accept=".zip"
              onChange={(e) => setZipFile(e.target.files?.[0] || null)}
              className="block mx-auto text-xs text-slate-300 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-sky-600 file:text-white hover:file:bg-sky-500"
            />
            {zipFile && (
              <div className="text-emerald-400 font-mono">
                {zipFile.name} ({Math.round(zipFile.size / 1024)} KB)
              </div>
            )}
          </div>
        )}

        {intakeTab === "files" && (
          <div className="p-8 rounded-xl bg-slate-950 border border-dashed border-slate-700 text-center space-y-3">
            <UploadCloud className="w-8 h-8 text-sky-400 mx-auto" />
            <div className="text-sm font-semibold text-slate-200">
              Select Source Files to Upload
            </div>
            <input
              type="file"
              multiple
              onChange={(e) => setMultiFiles(e.target.files)}
              className="block mx-auto text-xs text-slate-300 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-sky-600 file:text-white hover:file:bg-sky-500"
            />
            {multiFiles && multiFiles.length > 0 && (
              <div className="text-emerald-400 font-mono">
                {multiFiles.length} file(s) selected
              </div>
            )}
          </div>
        )}

        {intakeTab === "folder" && (
          <div className="p-5 rounded-xl bg-slate-950 border border-slate-800 space-y-3">
            <label className="block text-slate-300 font-medium">
              Project Folder Path
            </label>
            <input
              ref={folderInputRef}
              type="file"
              multiple
              {...({ webkitdirectory: "", directory: "" } as any)}
              onChange={handleBrowserFolderChange}
              className="hidden"
            />
            <div className="flex flex-wrap gap-2">
              <input
                type="text"
                value={localFolderPath}
                onChange={(e) => {
                  setFolderFiles(null);
                  setLocalFolderPath(e.target.value);
                }}
                placeholder="Click Browse or paste C:\path\to\project"
                className="flex-1 min-w-[220px] px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 font-mono"
              />
              <button
                type="button"
                disabled={browsingFolder}
                onClick={handlePickNativeFolder}
                className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-50 font-semibold text-white flex items-center gap-1.5 shrink-0"
              >
                <FolderOpen className="w-4 h-4" />
                <span>{browsingFolder ? "Opening..." : "Browse..."}</span>
              </button>
              <button
                type="button"
                onClick={() => folderInputRef.current?.click()}
                className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 font-semibold text-slate-200 flex items-center gap-1.5 shrink-0"
              >
                <UploadCloud className="w-4 h-4 text-sky-400" />
                <span>Pick in Browser</span>
              </button>
            </div>
          </div>
        )}

        {intakeTab === "git" && (
          <div className="p-5 rounded-xl bg-slate-950 border border-slate-800 grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="md:col-span-2">
              <label className="block text-slate-300 font-medium mb-1">
                Git Repository URL
              </label>
              <input
                type="text"
                value={gitRepoUrl}
                onChange={(e) => setGitRepoUrl(e.target.value)}
                placeholder="https://github.com/owner/repository.git"
                className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 font-mono"
              />
            </div>
            <div>
              <label className="block text-slate-300 font-medium mb-1">
                Branch
              </label>
              <input
                type="text"
                value={gitBranch}
                onChange={(e) => setGitBranch(e.target.value)}
                placeholder="main"
                className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 font-mono"
              />
            </div>
            <div className="md:col-span-3">
              <input
                type="password"
                value={gitPrivateToken}
                onChange={(e) => setGitPrivateToken(e.target.value)}
                placeholder="Optional: Private repo token (leave blank for public repos)"
                className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 font-mono"
              />
            </div>
          </div>
        )}

        {/* Minimal Options Row */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-slate-400 mb-1">
              Project Name (Optional)
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="Auto-detected from folder or file name"
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800"
            />
          </div>
          <div>
            <label className="block text-slate-400 mb-1">Audit Scope</label>
            <select
              value={auditScope}
              onChange={(e) => setAuditScope(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800"
            >
              <option value="FULL">Full Audit (All Quality, Security &amp; Runtime Checks)</option>
              <option value="SECURITY">Security Only</option>
              <option value="BACKEND">Backend &amp; API Only</option>
              <option value="FRONTEND">Frontend Only</option>
              <option value="CODE">Static Code &amp; Architecture Only</option>
            </select>
          </div>
        </div>

        {/* Step 2: Project Details & Documentation (REQUIRED TO RUN) */}
        <div
          className={`p-4 rounded-xl border space-y-3 ${
            projectDocumentation.trim()
              ? "bg-emerald-500/5 border-emerald-500/30"
              : "bg-slate-950 border-amber-500/40"
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-sky-400" />
              <span className="text-slate-100 font-bold text-xs">
                Project Details &amp; Documentation
              </span>
              <span
                className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                  projectDocumentation.trim()
                    ? "bg-emerald-500/20 text-emerald-400"
                    : "bg-amber-500/20 text-amber-400"
                }`}
              >
                {projectDocumentation.trim() ? "✓ PROVIDED" : "REQUIRED TO RUN"}
              </span>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <input
                ref={docFileInputRef}
                type="file"
                multiple
                accept=".md,.txt,.json,.yaml,.yml,.rst,.csv,.html,.pdf,.docx,.doc"
                onChange={handleDocFilesUpload}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => docFileInputRef.current?.click()}
                className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 text-white font-semibold flex items-center gap-1.5 text-[11px]"
              >
                <UploadCloud className="w-3.5 h-3.5" />
                <span>Upload Documentation Files (.md, .txt, .pdf, .json)</span>
              </button>
              <button
                type="button"
                onClick={() =>
                  setProjectDocumentation((prev) =>
                    prev.trim()
                      ? prev
                      : "Project Purpose: Web application & backend API service.\nKey Modules: Authentication, core business logic, REST API endpoints, and database persistence.\nAudit Expectations: Verify architecture alignment, security controls, error handling, and production readiness."
                  )
                }
                className="px-2.5 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 text-[11px]"
              >
                + Use Quick Template
              </button>
            </div>
          </div>

          {docFileNames.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span className="text-slate-400">Uploaded docs:</span>
              {docFileNames.map((fn) => (
                <span
                  key={fn}
                  className="px-2 py-0.5 rounded bg-sky-500/15 border border-sky-500/30 text-sky-300 font-mono"
                >
                  {fn}
                </span>
              ))}
              <button
                type="button"
                onClick={() => {
                  setDocFileNames([]);
                  setProjectDocumentation("");
                }}
                className="text-rose-400 hover:underline ml-1"
              >
                Clear
              </button>
            </div>
          )}

          <textarea
            rows={3}
            required
            value={projectDocumentation}
            onChange={(e) => setProjectDocumentation(e.target.value)}
            placeholder="Upload your README / architecture / specification files above, or describe what this project does, its expected features, architecture, and business rules (Required before starting an audit)..."
            className="w-full p-2.5 rounded-lg bg-slate-900 border border-slate-700 text-xs text-slate-100"
          />
        </div>

        {/* Custom Audit Instructions / Focus Prompt */}
        <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="flex items-center gap-1.5 text-slate-200 font-semibold">
              <MessageSquare className="w-3.5 h-3.5 text-sky-400" />
              <span>Audit Instructions / Focus Prompt (Optional)</span>
            </label>
            <div className="flex flex-wrap gap-1.5 text-[10px]">
              {[
                {
                  label: "Security & API Auth",
                  prompt:
                    "Focus on authentication routes, hardcoded secrets, SQL injection risks, and missing input validation.",
                },
                {
                  label: "Unfinished Code & TODOs",
                  prompt:
                    "Identify all unfinished TODO/FIXME blocks, stub functions, and disconnected frontend-to-backend buttons or endpoints.",
                },
                {
                  label: "Database & Error Handling",
                  prompt:
                    "Verify database schema consistency, transaction safety, and uncaught exception handling in API endpoints.",
                },
                {
                  label: "Production Readiness",
                  prompt:
                    "Check complete production readiness across security, architecture, test coverage, and runtime stability.",
                },
              ].map((preset) => (
                <button
                  key={preset.label}
                  type="button"
                  onClick={() => setCustomInstructions(preset.prompt)}
                  className="px-2 py-1 rounded bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300"
                >
                  + {preset.label}
                </button>
              ))}
            </div>
          </div>
          <textarea
            rows={2}
            value={customInstructions}
            onChange={(e) => setCustomInstructions(e.target.value)}
            placeholder="Tell the QC Agent how and what you want to audit (e.g., 'Focus on authentication routes, payment flow edge cases, SQL injection risks, and missing frontend validation')..."
            className="w-full p-2.5 rounded-lg bg-slate-900 border border-slate-700 text-xs text-slate-100"
          />
        </div>

        {/* Optional .env Toggle */}
        <div>
          <button
            type="button"
            onClick={() => setShowEnvEditor((v) => !v)}
            className="text-slate-400 hover:text-slate-200 flex items-center gap-1 text-[11px] font-medium"
          >
            {showEnvEditor ? (
              <ChevronUp className="w-3.5 h-3.5" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5" />
            )}
            <span>Optional: Add custom `.env` variables for this project</span>
          </button>
          {showEnvEditor && (
            <textarea
              rows={3}
              value={targetEnvContent}
              onChange={(e) => setTargetEnvContent(e.target.value)}
              placeholder={"DATABASE_URL=sqlite:///./app.db\nAPI_KEY=..."}
              className="w-full mt-2 p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px]"
            />
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-slate-800">
          <div className="text-[11px] text-slate-400">
            {!projectDocumentation.trim() ? (
              <span className="text-amber-400 font-medium">
                * Please upload or enter Project Details &amp; Documentation above to enable the audit run.
              </span>
            ) : (
              <span className="text-emerald-400 font-medium">
                ✓ Project documentation ready for audit verification.
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={() => handleProjectIntake(false)}
              className="px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 font-medium text-slate-200 border border-slate-700 disabled:opacity-50"
            >
              Check Project Setup Instructions
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => handleProjectIntake(true)}
              className="px-5 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white flex items-center gap-2 disabled:opacity-50"
            >
              <Play className="w-4 h-4" />
              <span>{busy ? "Running Audit..." : "Start Autonomous Audit"}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Simple & Readable Audit Results & Actionable Insights Card */}
      {activeAuditResult && (() => {
        const rawCov =
          activeAuditResult.manifest_summary?.coverage ||
          activeAuditResult.scorecard?.readable_insights?.file_coverage_breakdown ||
          {};
        const filesDiscovered =
          rawCov.files_discovered ?? rawCov.total_discovered ?? 0;
        const filesInScope =
          rawCov.files_in_scope ?? rawCov.in_scope ?? 0;
        const filesInspected =
          rawCov.files_inspected ?? rawCov.inspected ?? 0;
        const filesExcluded =
          rawCov.files_excluded ?? rawCov.excluded ?? 0;
        const coveragePercent =
          rawCov.inspection_coverage_percent ??
          rawCov.coverage_percent ??
          (filesInScope > 0
            ? Math.round((filesInspected / filesInScope) * 100)
            : 100);
        const langCounts: Record<string, number> =
          activeAuditResult.manifest_summary?.language_file_counts ||
          rawCov.language_file_counts ||
          {};

        // Fix any legacy cached "0/0" strings from older runs automatically
        const rawHeadline =
          activeAuditResult.scorecard?.readable_insights?.executive_headline ||
          `Completed ${activeAuditResult.audit_scope} audit with overall score ${
            activeAuditResult.overall_score ?? "—"
          }/100 and ${activeAuditFindings.length} finding(s).`;
        const cleanHeadline = rawHeadline.replace(
          /inspected 0\/0 in-scope files/g,
          `inspected ${filesInspected}/${filesInScope} in-scope files (${filesDiscovered} total discovered)`
        );

        const rawTakeaways: string[] =
          activeAuditResult.scorecard?.readable_insights?.key_takeaways || [];
        const cleanTakeaways = rawTakeaways.map((t) =>
          t.replace(
            /Inspected 0 of 0 in-scope files \(0 total discovered\)/g,
            `Inspected ${filesInspected} of ${filesInScope} in-scope files (${filesDiscovered} total discovered, ${filesExcluded} excluded)`
          )
        );

        return (
          <div
            ref={resultsRef}
            className="p-6 rounded-2xl bg-slate-900 border border-slate-800 space-y-5 text-xs"
          >
            {/* Result Header + Run Timestamps */}
            <div className="flex flex-wrap items-start justify-between gap-4 pb-4 border-b border-slate-800">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-sky-400" />
                  <span className="text-base font-bold text-slate-100">
                    Audit Results &amp; Key Insights —{" "}
                    {activeAuditResult.project_name || "Project"}
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-4 text-[11px] text-slate-400 pt-1">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5 text-sky-400" />
                    <strong>Started:</strong>{" "}
                    {formatRunTimestamp(
                      activeAuditResult.started_at || activeAuditResult.created_at
                    )}
                  </span>
                  <span>
                    <strong>Completed:</strong>{" "}
                    {formatRunTimestamp(activeAuditResult.completed_at)}
                  </span>
                  <span>
                    <strong>Duration:</strong>{" "}
                    {computeRunDuration(
                      activeAuditResult.started_at || activeAuditResult.created_at,
                      activeAuditResult.completed_at
                    )}
                  </span>
                  <span>
                    <strong>Scope:</strong> {activeAuditResult.audit_scope}
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <div className="text-right">
                  <div className="text-[10px] uppercase tracking-wider text-slate-400">
                    Health Score
                  </div>
                  <div className="text-2xl font-extrabold text-sky-400">
                    {activeAuditResult.overall_score ?? "—"}
                    <span className="text-xs font-normal text-slate-400">/100</span>
                  </div>
                </div>
                <span
                  className={`px-3 py-1.5 rounded-lg font-bold text-xs ${
                    activeAuditResult.release_gate === "APPROVED"
                      ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30"
                      : activeAuditResult.release_gate === "BLOCKED"
                      ? "bg-rose-500/15 text-rose-400 border border-rose-500/30"
                      : "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                  }`}
                >
                  {activeAuditResult.release_gate.replace(/_/g, " ")}
                </span>
              </div>
            </div>

            {/* Plain-English Executive Headline */}
            <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
              <div className="font-semibold text-slate-100 text-sm">
                Summary at a Glance
              </div>
              <p className="text-slate-300 leading-relaxed">{cleanHeadline}</p>
            </div>

            {/* Files Covered & Inspection Breakdown Strip */}
            <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-bold text-slate-100 text-xs">
                  Files Covered &amp; Repository Inspection Breakdown
                </span>
                <span className="px-2.5 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 font-bold text-[11px]">
                  {coveragePercent}% In-Scope Coverage ({filesInspected} / {filesInScope} files inspected)
                </span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                  <div className="text-[10px] uppercase text-slate-400">
                    Total Files Discovered
                  </div>
                  <div className="text-lg font-extrabold text-slate-100 mt-0.5">
                    {filesDiscovered}
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                  <div className="text-[10px] uppercase text-slate-400">
                    In-Scope Source Files
                  </div>
                  <div className="text-lg font-extrabold text-sky-400 mt-0.5">
                    {filesInScope}
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                  <div className="text-[10px] uppercase text-slate-400">
                    Files Inspected
                  </div>
                  <div className="text-lg font-extrabold text-emerald-400 mt-0.5">
                    {filesInspected}
                  </div>
                </div>
                <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                  <div className="text-[10px] uppercase text-slate-400">
                    Excluded / Ignored
                  </div>
                  <div className="text-lg font-extrabold text-slate-400 mt-0.5">
                    {filesExcluded}
                  </div>
                </div>
              </div>

              {Object.keys(langCounts).length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 pt-1">
                  <span className="text-[11px] text-slate-400 mr-1">
                    Files by Language:
                  </span>
                  {Object.entries(langCounts).map(([lang, count]) => (
                    <span
                      key={lang}
                      className="px-2.5 py-0.5 rounded-md bg-slate-900 border border-slate-700 text-slate-200 font-mono text-[11px]"
                    >
                      {lang}: <strong>{count}</strong>
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Direct Response to User's Custom Audit Instructions / Project Documentation */}
            {(activeAuditResult.scorecard?.readable_insights?.custom_instructions ||
              activeAuditResult.environment_snapshot?.custom_instructions ||
              activeAuditResult.scorecard?.readable_insights?.project_documentation_summary ||
              activeAuditResult.environment_snapshot?.project_documentation) && (
              <div className="p-4 rounded-xl bg-sky-500/10 border border-sky-500/30 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-sky-400">
                    Project Documentation &amp; Custom Instructions Alignment
                  </span>
                  {activeAuditResult.scorecard?.readable_insights
                    ?.ai_model_used && (
                    <span className="text-[10px] font-mono text-slate-400">
                      Analyzed via{" "}
                      {activeAuditResult.scorecard.readable_insights.ai_model_used}
                    </span>
                  )}
                </div>
                {(activeAuditResult.scorecard?.readable_insights
                  ?.custom_instructions ||
                  activeAuditResult.environment_snapshot?.custom_instructions) && (
                  <div className="text-[11px] text-slate-300 italic">
                    Focus Prompt: &ldquo;
                    {activeAuditResult.scorecard?.readable_insights
                      ?.custom_instructions ||
                      activeAuditResult.environment_snapshot?.custom_instructions}
                    &rdquo;
                  </div>
                )}
                <div className="text-slate-200 whitespace-pre-line leading-relaxed pt-1">
                  {activeAuditResult.scorecard?.readable_insights
                    ?.custom_instructions_response ||
                    "Project documentation and custom focus instructions were evaluated across all active audit agents."}
                </div>
              </div>
            )}

            {/* Key Takeaways Grid */}
            {cleanTakeaways.length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {cleanTakeaways.map((takeaway, idx) => (
                  <div
                    key={idx}
                    className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 flex items-start gap-2.5"
                  >
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                    <span className="text-slate-200 leading-relaxed">
                      {takeaway}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Readable Findings List (Simple Plain-English Cards + 1-Click Fix Approval) */}
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-bold text-sm text-slate-100">
                  Actionable Findings ({activeAuditFindings.length})
                </span>
                {activeAuditFindings.length > 0 && (
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => navigate("/approvals")}
                      className="px-3 py-1 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-500/40 text-emerald-300 font-semibold"
                    >
                      Open Fix Approval Center &rarr;
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        navigate(`/findings?sessionId=${activeAuditResult.id}`)
                      }
                      className="text-sky-400 hover:underline font-medium"
                    >
                      All Findings &rarr;
                    </button>
                  </div>
                )}
              </div>

              {activeAuditFindings.length === 0 ? (
                <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 text-emerald-400 font-medium flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>
                    0 defects or vulnerabilities detected in this audit run. All inspected files passed checks!
                  </span>
                </div>
              ) : (
                <div className="space-y-2.5 max-h-[440px] overflow-y-auto pr-1">
                  {activeAuditFindings.slice(0, 12).map((f) => (
                    <div
                      key={f.id}
                      className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-2"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-2">
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
                          <span className="font-bold text-slate-100">
                            {f.title}
                          </span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-[11px] text-sky-400">
                            {f.file_path || "project"}
                            {f.line_start ? `:${f.line_start}` : ""}
                          </span>
                          {f.file_path && (
                            <button
                              type="button"
                              disabled={generatingFixId === f.id}
                              onClick={() => handleOpenFixApproval(f.id)}
                              className="px-2.5 py-1 rounded-md bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold text-[11px]"
                            >
                              {generatingFixId === f.id
                                ? "Preparing Fix..."
                                : "Review & Approve Fix →"}
                            </button>
                          )}
                        </div>
                      </div>

                      <p className="text-slate-300 leading-relaxed">
                        <strong>Issue:</strong> {f.description}
                      </p>
                      {f.recommended_fix && (
                        <p className="text-emerald-400/90 leading-relaxed">
                          <strong>How to Fix:</strong> {f.recommended_fix}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Quick Actions Footer */}
            <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-800">
              <div className="flex flex-wrap gap-2">
                <a
                  href={`/api/v1/audits/${activeAuditResult.id}/reports/download?format=HTML`}
                  target="_blank"
                  rel="noreferrer"
                  className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 font-semibold text-slate-200 flex items-center gap-1.5"
                >
                  <FileText className="w-3.5 h-3.5 text-sky-400" />
                  <span>Open HTML Report</span>
                </a>
                <button
                  type="button"
                  onClick={async () => {
                    await qcApi.generateReport(activeAuditResult.id, "PDF");
                    window.open(
                      `/api/v1/audits/${activeAuditResult.id}/reports/download?format=PDF`,
                      "_blank"
                    );
                  }}
                  className="px-3.5 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 border border-slate-700 font-semibold text-slate-200 flex items-center gap-1.5"
                >
                  <FileText className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Download PDF Report</span>
                </button>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => navigate("/approvals")}
                  className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-semibold text-white"
                >
                  Review &amp; Approve Code Fixes &rarr;
                </button>
                <button
                  type="button"
                  onClick={() =>
                    navigate(`/live-monitor?auditId=${activeAuditResult.id}`)
                  }
                  className="px-4 py-2 rounded-lg bg-sky-600/20 hover:bg-sky-600/30 border border-sky-500/40 font-semibold text-sky-300"
                >
                  Agent Logs &rarr;
                </button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* Audit Run History with Timestamps */}
      {recentAudits.length > 0 && (
        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 space-y-3 text-xs">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 font-bold text-sm text-slate-100">
              <Clock className="w-4 h-4 text-sky-400" />
              <span>Audit Run History &amp; Timestamps</span>
            </div>
            <span className="text-slate-400 text-[11px]">
              Click any run to view its readable insights
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 text-[11px]">
                  <th className="py-2 pr-3">Project</th>
                  <th className="py-2 pr-3">Started At</th>
                  <th className="py-2 pr-3">Completed At</th>
                  <th className="py-2 pr-3">Duration</th>
                  <th className="py-2 pr-3">Score</th>
                  <th className="py-2 pr-3">Verdict</th>
                  <th className="py-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {recentAudits.slice(0, 8).map((run) => {
                  const isSelected = activeAuditResult?.id === run.id;
                  return (
                    <tr
                      key={run.id}
                      onClick={() => loadReadableResultForAudit(run, true)}
                      className={`cursor-pointer transition-colors ${
                        isSelected
                          ? "bg-sky-500/10"
                          : "hover:bg-slate-800/40"
                      }`}
                    >
                      <td className="py-2.5 pr-3 font-semibold text-slate-200">
                        {run.project_name || "Project"}
                      </td>
                      <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-300">
                        {formatRunTimestamp(run.started_at || run.created_at)}
                      </td>
                      <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-300">
                        {formatRunTimestamp(run.completed_at)}
                      </td>
                      <td className="py-2.5 pr-3 font-mono text-[11px] text-slate-400">
                        {computeRunDuration(
                          run.started_at || run.created_at,
                          run.completed_at
                        )}
                      </td>
                      <td className="py-2.5 pr-3 font-bold text-sky-400">
                        {run.overall_score ?? "—"}/100
                      </td>
                      <td className="py-2.5 pr-3">
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                            run.release_gate === "APPROVED"
                              ? "bg-emerald-500/15 text-emerald-400"
                              : run.release_gate === "BLOCKED"
                              ? "bg-rose-500/15 text-rose-400"
                              : "bg-amber-500/15 text-amber-400"
                          }`}
                        >
                          {run.release_gate.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="py-2.5 text-right">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            loadReadableResultForAudit(run, true);
                          }}
                          className="text-sky-400 hover:underline font-semibold"
                        >
                          View Insights
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Collapsible Project Readiness & Manual Setup Checklist */}
      {projects.length > 0 && (
        <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 space-y-4 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => setShowReadiness((v) => !v)}
              className="flex items-center gap-2 font-bold text-slate-100"
            >
              <Terminal className="w-4 h-4 text-emerald-400" />
              <span>Project Setup &amp; Readiness Guide</span>
              {showReadiness ? (
                <ChevronUp className="w-4 h-4" />
              ) : (
                <ChevronDown className="w-4 h-4" />
              )}
            </button>

            <div className="flex items-center gap-2">
              <select
                value={selectedReadinessProjectId}
                onChange={(e) => {
                  setSelectedReadinessProjectId(e.target.value);
                  setShowReadiness(true);
                }}
                className="px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800"
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {showReadiness && readinessData && (
            <div className="space-y-3 pt-2">
              {(readinessData.checklist || []).map((item: any, idx: number) => (
                <div
                  key={idx}
                  className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-1"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-slate-200">
                      {item.title}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        item.manual_action_needed
                          ? "bg-amber-500/15 text-amber-400"
                          : "bg-emerald-500/15 text-emerald-400"
                      }`}
                    >
                      {item.status}
                    </span>
                  </div>
                  <p className="text-slate-400">{item.instruction}</p>
                  {item.command && (
                    <div className="p-2 rounded bg-slate-900 border border-slate-800 font-mono text-[11px] text-sky-400">
                      $ {item.command}
                    </div>
                  )}
                </div>
              ))}

              <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
                <div className="font-semibold text-slate-200">
                  Project `.env` Configuration
                </div>
                <textarea
                  rows={4}
                  value={editableProjectEnv}
                  onChange={(e) => setEditableProjectEnv(e.target.value)}
                  className="w-full p-2.5 rounded bg-slate-900 border border-slate-800 font-mono text-[11px]"
                />
                <div className="flex justify-end">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={handleSaveTargetProjectEnv}
                    className="px-3 py-1.5 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white flex items-center gap-1.5"
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    <span>Save `.env`</span>
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};
