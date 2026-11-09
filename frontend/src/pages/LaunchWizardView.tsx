import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CheckCircle2,
  FolderOpen,
  GitBranch,
  HelpCircle,
  KeyRound,
  Play,
  Terminal,
  UploadCloud,
  Wrench,
} from "lucide-react";
import { qcApi } from "../services/api";
import type { Project } from "../types/qc";

export const LaunchWizardPage: React.FC = () => {
  const navigate = useNavigate();

  // Runtime config & instructions state
  const [runtimeConfig, setRuntimeConfig] = useState<Record<string, any> | null>(null);
  const [llmProvider, setLlmProvider] = useState("ollama");
  const [ollamaUrl, setOllamaUrl] = useState("http://127.0.0.1:11434");
  const [ollamaModel, setOllamaModel] = useState("qwen2.5-coder:7b");
  const [geminiKey, setGeminiKey] = useState("");
  const [geminiModel, setGeminiModel] = useState("gemini-2.5-pro");
  const [openaiKey, setOpenaiKey] = useState("");
  const [openaiModel, setOpenaiModel] = useState("gpt-4o");
  const [githubToken, setGithubToken] = useState("");
  const [runnerMode, setRunnerMode] = useState("LOCAL");

  // Project intake tab state ("zip" | "files" | "folder" | "git")
  const [intakeTab, setIntakeTab] = useState<"zip" | "files" | "folder" | "git">("zip");
  const [projectName, setProjectName] = useState("");
  const [projectDesc, setProjectDesc] = useState("");
  const [auditScope, setAuditScope] = useState("FULL");
  const [targetEnvContent, setTargetEnvContent] = useState("");

  // ZIP / Files state
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [multiFiles, setMultiFiles] = useState<FileList | null>(null);

  // Local folder state
  const [localFolderPath, setLocalFolderPath] = useState(
    "C:\\Users\\BISON TECH\\Desktop\\GMI\\QC Agent"
  );

  // Git clone state
  const [gitRepoUrl, setGitRepoUrl] = useState("");
  const [gitBranch, setGitBranch] = useState("main");
  const [gitPrivateToken, setGitPrivateToken] = useState("");

  // Project Readiness Advisor state
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedReadinessProjectId, setSelectedReadinessProjectId] = useState<string>("");
  const [readinessData, setReadinessData] = useState<Record<string, any> | null>(null);
  const [editableProjectEnv, setEditableProjectEnv] = useState<string>("");

  // Feedback banners
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
      setOllamaModel(rc.ai_config.ollama_model || "qwen2.5-coder:7b");
      setGeminiModel(rc.ai_config.gemini_model || "gemini-2.5-pro");
      setOpenaiModel(rc.ai_config.openai_model || "gpt-4o");
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
        ollama_model: ollamaModel,
        gemini_api_key: geminiKey || undefined,
        gemini_model: geminiModel,
        openai_api_key: openaiKey || undefined,
        openai_model: openaiModel,
        github_token: githubToken || undefined,
        default_runner_mode: runnerMode,
      });
      setRuntimeConfig(updated);
      setGeminiKey("");
      setOpenaiKey("");
      setGithubToken("");
      setStatusBanner({
        type: "success",
        text: "Saved AI provider settings and API keys to local configuration (.env).",
      });
    } catch (err: any) {
      setStatusBanner({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const handlePickNativeFolder = async () => {
    setStatusBanner({
      type: "info",
      text: "Opening Windows Folder Browser dialog...",
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
        fd.append("description", projectDesc || "Uploaded ZIP archive");
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
        fd.append("description", projectDesc || "Uploaded project files");
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
          description: projectDesc || "Local directory registered via Launch Wizard",
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
          description: projectDesc || undefined,
          branch: gitBranch || "main",
          git_token: gitPrivateToken || undefined,
          execution_mode: runnerMode,
          env_content: targetEnvContent || undefined,
        });
      }

      // Run repository discovery automatically
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
        setStatusBanner({
          type: "success",
          text: `Project '${createdProject.name}' uploaded & discovered! Review its tailored Readiness & Setup Instructions below before launching the audit.`,
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
        text: `Saved .env configuration directly into ${rd.root_path}\\.env`,
      });
    } catch (err: any) {
      setStatusBanner({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const handleLaunchAuditForSelected = async () => {
    if (!selectedReadinessProjectId) return;
    setBusy(true);
    try {
      const audit = await qcApi.startAudit(selectedReadinessProjectId, {
        audit_scope: auditScope,
        runner_mode: runnerMode,
        run_immediately: true,
        run_synchronously: true,
      });
      navigate(`/live-monitor?auditId=${audit.id}`);
    } catch (err: any) {
      setStatusBanner({ type: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  };

  const tools = runtimeConfig?.system_tools || [];
  const steps = runtimeConfig?.instructions?.quick_start_steps || [];
  const aiCfg = runtimeConfig?.ai_config || {};

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="p-6 rounded-2xl bg-gradient-to-r from-sky-950/70 via-slate-900 to-slate-900 border border-sky-500/30 flex flex-wrap items-center justify-between gap-4">
        <div>
          <span className="px-2.5 py-0.5 rounded-full bg-sky-500/20 text-sky-300 text-[11px] font-bold uppercase tracking-wider">
            Interactive Launch &amp; Setup Hub
          </span>
          <h2 className="text-2xl font-bold text-slate-100 mt-1">
            Upload Project Data, Configure API Keys &amp; Verify Audit Prerequisites
          </h2>
          <p className="text-xs text-slate-300 mt-1">
            Follow the instructions below to upload a ZIP archive, select a local folder, or clone a Git repository, verify required tools/API keys, and launch an autonomous technical audit.
          </p>
        </div>
      </div>

      {statusBanner && (
        <div
          className={`p-4 rounded-xl border text-xs font-medium ${
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

      {/* SECTION 1: COMPLETE INSTRUCTIONS & SYSTEM PREREQUISITE CHECKER */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4">
          <div className="flex items-center gap-2">
            <HelpCircle className="w-5 h-5 text-sky-400" />
            <h3 className="text-sm font-bold text-slate-100">
              Complete Instructions: What is Required to Run the QC Agent
            </h3>
          </div>
          <div className="space-y-3 text-xs">
            {steps.map((s: any) => (
              <div
                key={s.step}
                className="p-3.5 rounded-lg bg-slate-950 border border-slate-800 space-y-1.5"
              >
                <div className="font-bold text-sky-400">{s.title}</div>
                <p className="text-slate-300 leading-relaxed">{s.summary}</p>
                <div className="text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/20 px-2.5 py-1.5 rounded">
                  <strong>When Manual Configuration is Needed:</strong>{" "}
                  {s.manual_action_required}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Wrench className="w-5 h-5 text-emerald-400" />
              <h3 className="text-sm font-bold text-slate-100">
                Installed System Tools &amp; Manual Installation Guide
              </h3>
            </div>
            <span className="text-[11px] text-slate-400">
              Live Host Environment Check
            </span>
          </div>
          <div className="overflow-x-auto max-h-[420px] overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400">
                  <th className="py-2 pr-2">Tool</th>
                  <th className="py-2 pr-2">Requirement</th>
                  <th className="py-2 pr-2">Status / Version</th>
                  <th className="py-2">Manual Install Command (if missing)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {tools.map((t: any) => (
                  <tr key={t.name} className="hover:bg-slate-800/30">
                    <td className="py-2 pr-2 font-mono font-bold text-slate-200">
                      {t.name}
                    </td>
                    <td className="py-2 pr-2">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                          t.requirement_level.startsWith("REQUIRED")
                            ? "bg-rose-500/15 text-rose-300"
                            : t.requirement_level.startsWith("RECOMMENDED")
                            ? "bg-sky-500/15 text-sky-300"
                            : "bg-slate-800 text-slate-400"
                        }`}
                      >
                        {t.requirement_level}
                      </span>
                    </td>
                    <td className="py-2 pr-2">
                      {t.installed ? (
                        <span className="text-emerald-400 font-medium">
                          ✓ {t.version}
                        </span>
                      ) : (
                        <span className="text-amber-400 font-semibold">
                          ✗ Not Installed
                        </span>
                      )}
                    </td>
                    <td className="py-2 font-mono text-[11px] text-slate-400">
                      {t.installed ? t.purpose : t.install_command}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* SECTION 2: API KEYS & AI PROVIDER CONFIGURATION */}
      <form
        onSubmit={handleSaveApiKeys}
        className="p-5 rounded-xl bg-slate-900 border border-slate-800 space-y-4 text-xs"
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <KeyRound className="w-5 h-5 text-amber-400" />
            <div>
              <h3 className="text-sm font-bold text-slate-100">
                Step 1: API Keys &amp; AI Provider Configuration
              </h3>
              <p className="text-slate-400">
                Deterministic AST, Runtime, API, Database, and Security checks work{" "}
                <strong className="text-emerald-400">without any paid API key</strong>.
                Configure Gemini or OpenAI keys below only if you want cloud LLM analysis.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className="px-2.5 py-1 rounded bg-slate-950 border border-slate-800">
              Ollama Local:{" "}
              <strong
                className={
                  aiCfg.ollama_reachable ? "text-emerald-400" : "text-amber-400"
                }
              >
                {aiCfg.ollama_reachable ? "ONLINE" : "OFFLINE (AST Fallback Active)"}
              </strong>
            </span>
            <span className="px-2.5 py-1 rounded bg-slate-950 border border-slate-800">
              Gemini Key:{" "}
              <strong
                className={
                  aiCfg.has_gemini_key ? "text-emerald-400" : "text-slate-400"
                }
              >
                {aiCfg.has_gemini_key ? aiCfg.gemini_key_masked : "Not Set (Optional)"}
              </strong>
            </span>
            <span className="px-2.5 py-1 rounded bg-slate-950 border border-slate-800">
              OpenAI Key:{" "}
              <strong
                className={
                  aiCfg.has_openai_key ? "text-emerald-400" : "text-slate-400"
                }
              >
                {aiCfg.has_openai_key ? aiCfg.openai_key_masked : "Not Set (Optional)"}
              </strong>
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div>
            <label className="block text-slate-400 mb-1">
              Active AI Mode / Provider
            </label>
            <select
              value={llmProvider}
              onChange={(e) => setLlmProvider(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
            >
              <option value="ollama">Local Ollama + Deterministic (Free)</option>
              <option value="gemini">Google Gemini Cloud (Requires Key)</option>
              <option value="openai">OpenAI Cloud (Requires Key)</option>
            </select>
          </div>

          <div>
            <label className="block text-slate-400 mb-1">
              Ollama URL (Optional Local AI)
            </label>
            <input
              type="text"
              value={ollamaUrl}
              onChange={(e) => setOllamaUrl(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
            />
          </div>

          <div>
            <label className="block text-slate-400 mb-1">
              Google Gemini API Key{" "}
              <span className="text-amber-400">
                {llmProvider === "gemini" ? "(Required)" : "(Optional)"}
              </span>
            </label>
            <input
              type="password"
              value={geminiKey}
              onChange={(e) => setGeminiKey(e.target.value)}
              placeholder={
                aiCfg.has_gemini_key
                  ? `Saved (${aiCfg.gemini_key_masked})`
                  : "AIzaSy..."
              }
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
            />
          </div>

          <div>
            <label className="block text-slate-400 mb-1">
              OpenAI API Key{" "}
              <span className="text-amber-400">
                {llmProvider === "openai" ? "(Required)" : "(Optional)"}
              </span>
            </label>
            <input
              type="password"
              value={openaiKey}
              onChange={(e) => setOpenaiKey(e.target.value)}
              placeholder={
                aiCfg.has_openai_key
                  ? `Saved (${aiCfg.openai_key_masked})`
                  : "sk-..."
              }
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
            />
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
                  : "ghp_... (Optional)"
              }
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700 font-mono"
            />
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={busy}
              className="w-full px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white"
            >
              Save API Keys &amp; Mode
            </button>
          </div>
        </div>
      </form>

      {/* SECTION 3: INTERACTIVE PROJECT DATA UPLOAD & INTAKE */}
      <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 space-y-5 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <UploadCloud className="w-5 h-5 text-sky-400" />
            <div>
              <h3 className="text-sm font-bold text-slate-100">
                Step 2: Upload or Select Target Software Project for Audit
              </h3>
              <p className="text-slate-400">
                Choose how you want to provide your project data: ZIP archive upload, multi-file upload, local folder browser, or Git repository link
              </p>
            </div>
          </div>

          <div className="flex gap-2">
            {[
              { id: "zip", label: "1. Upload .ZIP Archive", icon: UploadCloud },
              { id: "files", label: "2. Upload Source Files", icon: UploadCloud },
              { id: "folder", label: "3. Browse Local Folder", icon: FolderOpen },
              { id: "git", label: "4. Clone Git Repo Link", icon: GitBranch },
            ].map((tab) => {
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setIntakeTab(tab.id as any)}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg font-semibold transition-colors ${
                    intakeTab === tab.id
                      ? "bg-sky-600 text-white"
                      : "bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800"
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-slate-400 mb-1">
              Project Display Name
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder="e.g., E-Commerce Checkout Service"
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
            />
          </div>
          <div>
            <label className="block text-slate-400 mb-1">Audit Scope</label>
            <select
              value={auditScope}
              onChange={(e) => setAuditScope(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
            >
              <option value="FULL">FULL (All 9 Specialized Agent Phases)</option>
              <option value="SECURITY">SECURITY (Secrets + SAST + Injection)</option>
              <option value="BACKEND">BACKEND (Server Boot + API Probes + DB)</option>
              <option value="FRONTEND">FRONTEND (Playwright Headless Browser)</option>
              <option value="CODE">CODE (AST Complexity + Dead Code + Architecture)</option>
              <option value="PERFORMANCE">PERFORMANCE (Latency p50/p95/p99 + RPS)</option>
              <option value="E2E">E2E (Full-Stack Business Workflows)</option>
            </select>
          </div>
          <div>
            <label className="block text-slate-400 mb-1">
              Execution Isolation Mode
            </label>
            <select
              value={runnerMode}
              onChange={(e) => setRunnerMode(e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
            >
              <option value="LOCAL">LOCAL (Isolated Process &amp; Workspace Copy)</option>
              <option value="DOCKER">DOCKER (Disposable Container Sandbox)</option>
            </select>
          </div>
        </div>

        {/* Dynamic Tab Input Area */}
        {intakeTab === "zip" && (
          <div className="p-6 rounded-xl bg-slate-950 border-2 border-dashed border-slate-700 text-center space-y-3">
            <div className="text-sm font-semibold text-slate-200">
              Upload Project `.zip` Archive
            </div>
            <p className="text-slate-400">
              Compress your software repository into a `.zip` file and select it below. The platform will safely extract it into `.qc_storage/uploaded_projects/`.
            </p>
            <input
              type="file"
              accept=".zip"
              onChange={(e) => setZipFile(e.target.files?.[0] || null)}
              className="block mx-auto text-xs text-slate-300 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-sky-600 file:text-white hover:file:bg-sky-500"
            />
            {zipFile && (
              <div className="text-emerald-400 font-mono">
                Selected ZIP: {zipFile.name} ({Math.round(zipFile.size / 1024)} KB)
              </div>
            )}
          </div>
        )}

        {intakeTab === "files" && (
          <div className="p-6 rounded-xl bg-slate-950 border-2 border-dashed border-slate-700 text-center space-y-3">
            <div className="text-sm font-semibold text-slate-200">
              Upload Multiple Source Files
            </div>
            <p className="text-slate-400">
              Select multiple source code files, manifests (`package.json`, `requirements.txt`), and configuration files to assemble a project workspace.
            </p>
            <input
              type="file"
              multiple
              onChange={(e) => setMultiFiles(e.target.files)}
              className="block mx-auto text-xs text-slate-300 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-sky-600 file:text-white hover:file:bg-sky-500"
            />
            {multiFiles && multiFiles.length > 0 && (
              <div className="text-emerald-400 font-mono">
                Selected {multiFiles.length} file(s) for upload
              </div>
            )}
          </div>
        )}

        {intakeTab === "folder" && (
          <div className="p-5 rounded-xl bg-slate-950 border border-slate-800 space-y-3">
            <label className="block text-slate-300 font-semibold">
              Select or Paste Local Project Directory Path
            </label>
            <div className="flex gap-3">
              <input
                type="text"
                value={localFolderPath}
                onChange={(e) => setLocalFolderPath(e.target.value)}
                placeholder="C:\path\to\your\project"
                className="flex-1 px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 font-mono"
              />
              <button
                type="button"
                onClick={handlePickNativeFolder}
                className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white flex items-center gap-2 shrink-0"
              >
                <FolderOpen className="w-4 h-4" />
                <span>Browse Local Folder...</span>
              </button>
            </div>
          </div>
        )}

        {intakeTab === "git" && (
          <div className="p-5 rounded-xl bg-slate-950 border border-slate-800 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="md:col-span-2">
              <label className="block text-slate-300 font-semibold mb-1">
                Git Repository URL (GitHub / GitLab / Bitbucket)
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
              <label className="block text-slate-300 font-semibold mb-1">
                Branch Name
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
              <label className="block text-slate-400 mb-1">
                Private Repository Access Token (Optional — leave blank for public repos)
              </label>
              <input
                type="password"
                value={gitPrivateToken}
                onChange={(e) => setGitPrivateToken(e.target.value)}
                placeholder="ghp_... or glpat-..."
                className="w-full px-3 py-2 rounded-lg bg-slate-900 border border-slate-700 font-mono"
              />
            </div>
          </div>
        )}

        {/* Optional Target Project .env Configuration */}
        <div>
          <label className="block text-slate-400 mb-1">
            Optional: Target Project `.env` Variables (If the project being audited requires specific environment variables or API keys to boot up)
          </label>
          <textarea
            rows={3}
            value={targetEnvContent}
            onChange={(e) => setTargetEnvContent(e.target.value)}
            placeholder={"# Optional key=value pairs written to <target_project>/.env\nDATABASE_URL=sqlite:///./app.db\nSTRIPE_TEST_KEY=sk_test_..."}
            className="w-full p-3 rounded-lg bg-slate-950 border border-slate-800 font-mono text-[11px]"
          />
        </div>

        <div className="flex flex-wrap items-center justify-end gap-3 pt-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => handleProjectIntake(false)}
            className="px-4 py-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 font-semibold text-slate-200 border border-slate-700 disabled:opacity-50"
          >
            {busy ? "Processing..." : "1. Upload & Check Project Readiness First"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => handleProjectIntake(true)}
            className="px-5 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-bold text-white flex items-center gap-2 disabled:opacity-50"
          >
            <Play className="w-4 h-4" />
            <span>
              {busy
                ? "Uploading & Executing Audit..."
                : "2. Upload, Discover & Launch Full Audit Now →"}
            </span>
          </button>
        </div>
      </div>

      {/* SECTION 4: TAILORED PROJECT READINESS & MANUAL SETUP ADVISOR */}
      <div className="p-6 rounded-xl bg-slate-900 border border-slate-800 space-y-4 text-xs">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Terminal className="w-5 h-5 text-emerald-400" />
            <div>
              <h3 className="text-sm font-bold text-slate-100">
                Step 3: Project-Specific Audit Readiness &amp; Manual Setup Instructions
              </h3>
              <p className="text-slate-400">
                Automatically inspects the selected project and tells you whether any manual package installation or `.env` configuration is needed
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <select
              value={selectedReadinessProjectId}
              onChange={(e) => setSelectedReadinessProjectId(e.target.value)}
              className="px-3 py-2 rounded-lg bg-slate-950 border border-slate-700"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.root_path})
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={busy || !selectedReadinessProjectId}
              onClick={handleLaunchAuditForSelected}
              className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-bold text-white"
            >
              Run Audit on Selected Project →
            </button>
          </div>
        </div>

        {readinessData ? (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-3">
              {(readinessData.checklist || []).map((item: any, idx: number) => (
                <div
                  key={idx}
                  className="p-4 rounded-lg bg-slate-950 border border-slate-800 space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <div className="font-bold text-slate-200">
                      [{item.category}] {item.title}
                    </div>
                    <span
                      className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                        item.manual_action_needed
                          ? "bg-amber-500/15 text-amber-300"
                          : "bg-emerald-500/15 text-emerald-300"
                      }`}
                    >
                      {item.status}
                    </span>
                  </div>
                  <p className="text-slate-300">{item.instruction}</p>
                  {item.command && (
                    <div className="p-2 rounded bg-slate-900 border border-slate-800 font-mono text-[11px] text-sky-300">
                      $ {item.command}
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="p-4 rounded-lg bg-slate-950 border border-slate-800 space-y-3 flex flex-col justify-between">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-slate-200">
                    Target Project `.env` Editor
                  </span>
                  <span className="text-[11px] text-slate-400">
                    {readinessData.has_env_file ? ".env present" : "No .env yet"}
                  </span>
                </div>
                <p className="text-[11px] text-slate-400">
                  Edit or add environment variables required by{" "}
                  <strong>{readinessData.project_name}</strong> and save directly to its folder:
                </p>
                <textarea
                  rows={10}
                  value={editableProjectEnv}
                  onChange={(e) => setEditableProjectEnv(e.target.value)}
                  className="w-full p-2.5 rounded bg-slate-900 border border-slate-800 font-mono text-[11px] text-slate-200"
                />
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={handleSaveTargetProjectEnv}
                className="w-full px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 font-semibold text-white flex items-center justify-center gap-1.5"
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>Save `.env` to Target Project</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="text-slate-500">
            Select or upload a project above to view its tailored readiness instructions.
          </div>
        )}
      </div>
    </div>
  );
};

