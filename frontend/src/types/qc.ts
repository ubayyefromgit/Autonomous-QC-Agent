export interface OverviewTelemetry {
  registered_projects: number;
  total_audits: number;
  active_audits: number;
  completed_audits: number;
  failed_audits: number;
  total_findings: number;
  critical_findings: number;
  security_findings: number;
  pending_approvals: number;
  average_audit_duration_seconds: number;
  severity_breakdown: Record<string, number>;
}

export interface ProjectConfig {
  id: string;
  project_id: string;
  execution_mode: string;
  exclusions: string[];
  custom_rules: Record<string, unknown>;
  service_startup_config: Record<string, unknown>;
  quality_gate_policy: Record<string, unknown>;
  llm_config: Record<string, unknown>;
  retention_days: number;
  updated_at: string;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  root_path: string;
  repository_url: string | null;
  default_branch: string;
  detected_stack: {
    languages?: string[];
    frameworks?: string[];
    databases?: string[];
    infrastructure?: string[];
    test_frameworks?: string[];
    coverage?: {
      files_discovered: number;
      files_in_scope: number;
      files_inspected: number;
      files_excluded: number;
      files_failed: number;
      inspection_coverage_percent: number;
    };
  };
  created_at: string;
  updated_at: string;
  configuration: ProjectConfig | null;
  total_audits: number;
  last_audit_status: string | null;
  last_audit_score: number | null;
  last_release_gate: string | null;
  unresolved_findings_count: number;
}

export interface RepositoryFile {
  id: string;
  session_id: string;
  project_id: string;
  relative_path: string;
  file_type: string;
  language: string;
  size_bytes: number;
  line_count: number;
  sha256_hash: string | null;
  inspection_status: string;
  status_reason: string | null;
  is_entrypoint: boolean;
  is_test_file: boolean;
  component_boundary: string;
  imports_dependencies: string[];
  inspected_at: string | null;
}

export interface AuditSession {
  id: string;
  project_id: string;
  project_name?: string | null;
  status: string;
  current_phase: string;
  audit_scope: string;
  runner_mode: string;
  commit_hash: string | null;
  branch_name: string | null;
  manifest_summary: Record<string, any>;
  scorecard: Record<string, any>;
  overall_score: number | null;
  release_gate: string;
  environment_snapshot: Record<string, any>;
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  error_summary: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface AuditTask {
  id: string;
  session_id: string;
  task_key: string;
  agent_type: string;
  phase: string;
  status: string;
  dependencies: string[];
  result_summary: Record<string, any>;
  attempts: number;
  duration_seconds: number | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface ExecutionLog {
  id: string;
  session_id: string;
  task_id: string | null;
  runner_type: string;
  command: string;
  working_dir: string;
  exit_code: number;
  duration_seconds: number;
  timed_out: boolean;
  stdout_preview: string | null;
  stderr_preview: string | null;
  executed_at: string;
}

export interface AuditProgress {
  audit_id: string;
  project_id: string;
  status: string;
  current_phase: string;
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  progress_percent: number;
  active_agents: string[];
  elapsed_seconds: number;
  tasks: AuditTask[];
  recent_logs: ExecutionLog[];
}

export interface Finding {
  id: string;
  project_id: string;
  session_id: string;
  fingerprint: string;
  category: string;
  severity: string;
  title: string;
  description: string;
  file_path: string | null;
  line_start: number | null;
  line_end: number | null;
  agent_name: string;
  reproduction_steps: string[];
  expected_behavior: string | null;
  actual_behavior: string | null;
  root_cause: string | null;
  impact: string | null;
  recommended_fix: string | null;
  confidence: number;
  verification_status: string;
  lifecycle_status: string;
  occurrence_count: number;
  created_at: string;
  updated_at: string;
  evidence_count: number;
}

export interface Evidence {
  id: string;
  session_id: string;
  task_id: string | null;
  finding_id: string | null;
  evidence_type: string;
  storage_uri: string;
  sha256_checksum: string;
  source_tool: string;
  content_excerpt: string | null;
  metadata_json: Record<string, any>;
  created_at: string;
}

export interface TestRun {
  id: string;
  session_id: string;
  task_id: string | null;
  test_suite_type: string;
  tool_name: string;
  command: string;
  status: string;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  skipped_tests: number;
  duration_seconds: number;
  exit_code: number;
  details: Record<string, any>;
  executed_at: string;
}

export interface PatchRecord {
  id: string;
  proposal_id: string;
  sha256_checksum: string;
  target_file_path: string;
  original_code: string;
  proposed_code: string;
  unified_diff: string;
  working_branch: string | null;
  syntax_valid: boolean;
  static_checks_passed: boolean;
  applied_at: string | null;
  created_at: string;
}

export interface ApprovalRecord {
  id: string;
  proposal_id: string;
  reviewer_name: string;
  decision: string;
  approved_patch_checksum: string;
  comments: string | null;
  is_valid: boolean;
  decided_at: string;
}

export interface RegressionRunRecord {
  id: string;
  patch_id: string;
  status: string;
  issue_resolved: boolean;
  regressions_detected: boolean;
  pre_fix_comparison: Record<string, any>;
  post_fix_comparison: Record<string, any>;
  verified_at: string;
}

export interface RemediationProposal {
  id: string;
  finding_id: string;
  session_id: string;
  status: string;
  root_cause_analysis: string;
  explanation: string;
  affected_files: string[];
  expected_behavior: string;
  potential_impact: string;
  safety_check_results: Record<string, any>;
  test_plan: string[];
  rollback_procedure: string;
  active_patch_checksum: string;
  version_id: number;
  created_at: string;
  updated_at: string;
  patches: PatchRecord[];
  approvals: ApprovalRecord[];
  regression_runs: RegressionRunRecord[];
}

export interface ReportRecord {
  id: string;
  session_id: string;
  report_format: string;
  storage_uri: string;
  sha256_checksum: string;
  release_recommendation: string;
  overall_score: number;
  audit_complete: boolean;
  incomplete_checks: string[];
  generated_at: string;
}

