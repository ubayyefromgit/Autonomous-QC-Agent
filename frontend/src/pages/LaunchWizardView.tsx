import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  FolderOpen,
  GitBranch,
  HelpCircle,
  KeyRound,
  Play,
  Terminal,
  UploadCloud,
} from "lucide-react";
import { qcApi } from "../services/api";
import type { Project } from "../types/qc";

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

  // Project intake tab state ("zip" | "files" | "folder" | "git")
  const [intakeTab, setIntakeTab] = useState<"zip" | "files" | "folder" | "git">("zip");
  const [projectName, setProjectName] = useState("");
  const [auditScope, setAuditScope] = useState("FULL");
  const [targetEnvContent, setTargetEnvContent] = useState("");

  // ZIP / Files / Folder / Git state
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [multiFiles, setMultiFiles] = useState<FileList | null>(null);
  const [localFolderPath, setLocalFolderPath] = useState("");
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

  const loadInitial = async () => {
    const [rc, projs] = await Promise.all([
      qcApi.getRuntimeConfig(),
      qcApi.listProjects(),
    ]);
    setRuntimeConfig(rc);
    if (rc.ai_config) {
      setLlmProvider(rc.ai_config.default_llm_provider || "ollama");
      setOllamaUrl(rc.ai_config.ollama_base_url || "http://127.0.0.1:11434");
      setRunnerMode(rc.ai_config.default_runner_mode || "LOCAL");
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
      const updated = await qcApi.updateRuntimeConfig({
        default_llm_provider: llmProvider,
        ollama_base_url: ollamaUrl,
        gemini_api_key: geminiKey || undefined,
        openai_api_key: openaiKey || undefined,
        github_token: githubToken || undefined,
        default_runner_mode: runnerMode,
      });
      setRuntimeConfig(updated);
      setGeminiKey("");
      setOpenaiKey("");
      setGithubToken("");
      setStatusBanner({
        type: "success",
        text: "Configuration saved.",
      });
      setShowApiKeys(false);
    } catch (err: any) {
      setStatusBanner({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const handlePickNativeFolder = async () => {
    setStatusBanner({
      type: "info",
      text: "Opening folder browser...",
    });
    try {
      const res = await qcApi.pickLocalFolder();
      if (!res.cancelled && res.selected_path) {
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
    }
  };

  const handleProjectIntake = async (runAuditImmediately: boolean) => {
    setBusy(true);
    setStatusBanner(null);
    try {
      let createdProject: Project;

      if (intakeTab === "zip") {
        if (!zipFile) {
          throw new Error("Please select a .zip archive file to upload.");
        }
        const fd = new FormData();
        fd.append("file", zipFile);
        fd.append("name", projectName || zipFile.name.replace(/\.zip$/i, ""));
        fd.append("description", "Uploaded ZIP archive");
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
        fd.append("description", "Uploaded project files");
        fd.append("execution_mode", runnerMode);
        fd.append("env_content", targetEnvContent);
        createdProject = await qcApi.uploadProjectFiles(fd);
      } else if (intakeTab === "folder") {
        if (!localFolderPath.trim()) {
          throw new Error("Please enter or browse a valid local folder path.");
        }
        const parts = localFolderPath.replace(/\\/g, "/").split("/");
        createdProject = await qcApi.createProject({
          name: projectName || parts[parts.length - 1] || "Local Software Project",
          root_path: localFolderPath.trim(),
          description: "Local directory registered via Launch Hub",
          execution_mode: runnerMode,
        });
        if (targetEnvContent.trim()) {
          await qcApi.saveProjectEnv(createdProject.id, targetEnvContent);
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
          run_immediately: true,
          run_synchronously: true,
        });
        navigate(`/live-monitor?auditId=${audit.id}`);
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
              AI Mode: {llmProvider.toUpperCase()}
              {llmProvider === "ollama" ? " (No Key Needed)" : ""}
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

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label className="block text-slate-400 mb-1">AI Provider</label>
              <select
                value={llmProvider}
                onChange={(e) => setLlmProvider(e.target.value)}
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
                <input
                  type="text"
                  value={ollamaUrl}
                  onChange={(e) => setOllamaUrl(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
                />
              </div>
            )}

            {llmProvider === "gemini" && (
              <div>
                <label className="block text-slate-400 mb-1">
                  Google Gemini API Key
                </label>
                <input
                  type="password"
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                  placeholder={
                    aiCfg.has_gemini_key
                      ? `Saved (${aiCfg.gemini_key_masked})`
                      : "Enter AIzaSy..."
                  }
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
                />
              </div>
            )}

            {llmProvider === "openai" && (
              <div>
                <label className="block text-slate-400 mb-1">
                  OpenAI API Key
                </label>
                <input
                  type="password"
                  value={openaiKey}
                  onChange={(e) => setOpenaiKey(e.target.value)}
                  placeholder={
                    aiCfg.has_openai_key
                      ? `Saved (${aiCfg.openai_key_masked})`
                      : "Enter sk-..."
                  }
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
                />
              </div>
            )}

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
          <div className="p-5 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
            <label className="block text-slate-300 font-medium">
              Project Folder Path
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={localFolderPath}
                onChange={(e) => setLocalFolderPath(e.target.value)}
                placeholder="Click Browse or paste C:\path\to\project"
                className="flex-1 px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 font-mono"
              />
              <button
                type="button"
                onClick={handlePickNativeFolder}
                className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white flex items-center gap-1.5 shrink-0"
              >
                <FolderOpen className="w-4 h-4" />
                <span>Browse...</span>
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
        <div className="flex flex-wrap items-center justify-end gap-3 pt-2 border-t border-slate-800">
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
