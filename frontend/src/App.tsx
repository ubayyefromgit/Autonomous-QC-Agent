import React from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { DashboardLayout } from "./layouts/DashboardLayout";
import { LaunchWizardPage } from "./pages/LaunchWizardView";
import { OverviewPage } from "./pages/OverviewViews";
import {
  ProjectDetailsPage,
  ProjectsPage,
  RepositoryExplorerPage,
} from "./pages/ProjectViews";
import {
  AuditSessionsPage,
  LiveAuditMonitorPage,
  TestExecutionPage,
} from "./pages/AuditViews";
import {
  EvidenceExplorerPage,
  FindingDetailsPage,
  FindingsPage,
} from "./pages/FindingViews";
import {
  PerformanceAssessmentPage,
  SecurityAssessmentPage,
} from "./pages/AssessmentViews";
import {
  ApprovalCenterPage,
  RemediationProposalsPage,
} from "./pages/RemediationViews";
import {
  AgentActivityPage,
  ReportsPage,
  SystemSettingsPage,
} from "./pages/SystemViews";

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DashboardLayout />}>
          {/* View 0: Interactive Launch, Upload, API Key & Instructions Hub */}
          <Route index element={<LaunchWizardPage />} />
          <Route path="launch" element={<LaunchWizardPage />} />
          {/* View 1 */}
          <Route path="overview" element={<OverviewPage />} />
          {/* View 2 */}
          <Route path="projects" element={<ProjectsPage />} />
          {/* View 3 */}
          <Route path="projects/:projectId" element={<ProjectDetailsPage />} />
          {/* View 4 */}
          <Route path="repository" element={<RepositoryExplorerPage />} />
          {/* View 5 */}
          <Route path="audits" element={<AuditSessionsPage />} />
          {/* View 6 */}
          <Route path="live-monitor" element={<LiveAuditMonitorPage />} />
          {/* View 7 */}
          <Route path="findings" element={<FindingsPage />} />
          {/* View 8 */}
          <Route path="findings/:findingId" element={<FindingDetailsPage />} />
          {/* View 9 */}
          <Route path="evidence" element={<EvidenceExplorerPage />} />
          {/* View 10 */}
          <Route path="test-results" element={<TestExecutionPage />} />
          {/* View 11 */}
          <Route path="security" element={<SecurityAssessmentPage />} />
          {/* View 12 */}
          <Route path="performance" element={<PerformanceAssessmentPage />} />
          {/* View 13 */}
          <Route path="remediation" element={<RemediationProposalsPage />} />
          {/* View 14 */}
          <Route path="approvals" element={<ApprovalCenterPage />} />
          {/* View 15 */}
          <Route path="reports" element={<ReportsPage />} />
          {/* View 16 */}
          <Route path="agent-activity" element={<AgentActivityPage />} />
          {/* View 17 */}
          <Route path="settings" element={<SystemSettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
};

export default App;

