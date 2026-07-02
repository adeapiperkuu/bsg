import { apiFetch } from "../api";
import type {
  AnnotatorRead,
  AnnotatorSkillCreatePayload,
  AnnotatorSkillRead,
  AnnotatorSkillUpdatePayload,
  CapabilityGapDetectionResponse,
  CapabilityGapRead,
  CapabilityGapUpdatePayload,
  CertificationRead,
  EmployeeCertificationCreatePayload,
  EmployeeCertificationRead,
  EmployeeCertificationUpdatePayload,
  ProjectUtilizationFilters,
  ProjectSkillRequirementCreatePayload,
  ProjectSkillRequirementRead,
  ProjectSkillRequirementUpdatePayload,
  ProjectWorkforceSummaryRead,
  SkillMatrixRead,
  SkillRead,
  TeamRead,
  TrainingGapSummaryRead,
  TrainingProgramRead,
  TrainingRecordCreatePayload,
  TrainingRecordRead,
  TrainingRecordUpdatePayload,
  UtilizationSnapshotCreatePayload,
  UtilizationSnapshotRead,
  UtilizationSnapshotUpdatePayload,
  WorkforceRecommendationGenerateResponse,
} from "@/types/workforce";

export async function listProjectTeams(projectId: string): Promise<TeamRead[]> {
  const body = await apiFetch<{ data: TeamRead[] }>(`/projects/${projectId}/teams?limit=100`);
  return body.data;
}

export async function getProjectWorkforceSummary(
  projectId: string,
): Promise<ProjectWorkforceSummaryRead> {
  const body = await apiFetch<{ data: ProjectWorkforceSummaryRead }>(
    `/projects/${projectId}/workforce-summary`,
  );
  return body.data;
}

export async function listTeamAnnotators(teamId: string): Promise<AnnotatorRead[]> {
  const body = await apiFetch<{ data: AnnotatorRead[] }>(`/teams/${teamId}/annotators?limit=100`);
  return body.data;
}

export async function listProjectUtilization(
  projectId: string,
  filters: ProjectUtilizationFilters = {},
): Promise<UtilizationSnapshotRead[]> {
  const params = new URLSearchParams();
  if (filters.team_id) params.set("team_id", filters.team_id);
  if (filters.annotator_id) params.set("annotator_id", filters.annotator_id);
  if (filters.from_date) params.set("from_date", filters.from_date);
  if (filters.to_date) params.set("to_date", filters.to_date);
  params.set("limit", String(filters.limit ?? 100));
  const query = params.toString();
  const body = await apiFetch<{ data: UtilizationSnapshotRead[] }>(
    `/projects/${projectId}/utilization?${query}`,
  );
  return body.data;
}

export async function createUtilizationSnapshot(
  projectId: string,
  payload: UtilizationSnapshotCreatePayload,
): Promise<UtilizationSnapshotRead> {
  const body = await apiFetch<{ data: UtilizationSnapshotRead }>(
    `/projects/${projectId}/utilization`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  return body.data;
}

export async function updateUtilizationSnapshot(
  snapshotId: string,
  payload: UtilizationSnapshotUpdatePayload,
): Promise<UtilizationSnapshotRead> {
  const body = await apiFetch<{ data: UtilizationSnapshotRead }>(`/utilization/${snapshotId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function deleteUtilizationSnapshot(snapshotId: string): Promise<void> {
  await apiFetch<void>(`/utilization/${snapshotId}`, { method: "DELETE" });
}

export async function listWorkforceSkills(): Promise<SkillRead[]> {
  const body = await apiFetch<{ data: SkillRead[] }>("/workforce/skills?limit=100");
  return body.data;
}

export async function listWorkforceCertifications(): Promise<CertificationRead[]> {
  const body = await apiFetch<{ data: CertificationRead[] }>("/workforce/certifications?limit=100");
  return body.data;
}

export async function listWorkforceTrainingPrograms(): Promise<TrainingProgramRead[]> {
  const body = await apiFetch<{ data: TrainingProgramRead[] }>(
    "/workforce/training-programs?limit=100",
  );
  return body.data;
}

export async function listAnnotatorSkills(annotatorId: string): Promise<AnnotatorSkillRead[]> {
  const body = await apiFetch<{ data: AnnotatorSkillRead[] }>(
    `/annotators/${annotatorId}/skills?limit=100`,
  );
  return body.data;
}

export async function createAnnotatorSkill(
  annotatorId: string,
  payload: AnnotatorSkillCreatePayload,
): Promise<AnnotatorSkillRead> {
  const body = await apiFetch<{ data: AnnotatorSkillRead }>(`/annotators/${annotatorId}/skills`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function updateAnnotatorSkill(
  annotatorSkillId: string,
  payload: AnnotatorSkillUpdatePayload,
): Promise<AnnotatorSkillRead> {
  const body = await apiFetch<{ data: AnnotatorSkillRead }>(
    `/annotator-skills/${annotatorSkillId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
  return body.data;
}

export async function deleteAnnotatorSkill(annotatorSkillId: string): Promise<void> {
  await apiFetch<void>(`/annotator-skills/${annotatorSkillId}`, { method: "DELETE" });
}

export async function listAnnotatorCertifications(
  annotatorId: string,
): Promise<EmployeeCertificationRead[]> {
  const body = await apiFetch<{ data: EmployeeCertificationRead[] }>(
    `/annotators/${annotatorId}/certifications?limit=100`,
  );
  return body.data;
}

export async function createEmployeeCertification(
  annotatorId: string,
  payload: EmployeeCertificationCreatePayload,
): Promise<EmployeeCertificationRead> {
  const body = await apiFetch<{ data: EmployeeCertificationRead }>(
    `/annotators/${annotatorId}/certifications`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  return body.data;
}

export async function updateEmployeeCertification(
  employeeCertificationId: string,
  payload: EmployeeCertificationUpdatePayload,
): Promise<EmployeeCertificationRead> {
  const body = await apiFetch<{ data: EmployeeCertificationRead }>(
    `/employee-certifications/${employeeCertificationId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
  return body.data;
}

export async function deleteEmployeeCertification(employeeCertificationId: string): Promise<void> {
  await apiFetch<void>(`/employee-certifications/${employeeCertificationId}`, {
    method: "DELETE",
  });
}

export async function listAnnotatorTrainingRecords(
  annotatorId: string,
): Promise<TrainingRecordRead[]> {
  const body = await apiFetch<{ data: TrainingRecordRead[] }>(
    `/annotators/${annotatorId}/training-records?limit=100`,
  );
  return body.data;
}

export async function createTrainingRecord(
  annotatorId: string,
  payload: TrainingRecordCreatePayload,
): Promise<TrainingRecordRead> {
  const body = await apiFetch<{ data: TrainingRecordRead }>(
    `/annotators/${annotatorId}/training-records`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  return body.data;
}

export async function updateTrainingRecord(
  trainingRecordId: string,
  payload: TrainingRecordUpdatePayload,
): Promise<TrainingRecordRead> {
  const body = await apiFetch<{ data: TrainingRecordRead }>(
    `/training-records/${trainingRecordId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
  return body.data;
}

export async function deleteTrainingRecord(trainingRecordId: string): Promise<void> {
  await apiFetch<void>(`/training-records/${trainingRecordId}`, { method: "DELETE" });
}

export async function listProjectSkillRequirements(
  projectId: string,
): Promise<ProjectSkillRequirementRead[]> {
  const body = await apiFetch<{ data: ProjectSkillRequirementRead[] }>(
    `/projects/${projectId}/skill-requirements?limit=100`,
  );
  return body.data;
}

export async function createProjectSkillRequirement(
  projectId: string,
  payload: ProjectSkillRequirementCreatePayload,
): Promise<ProjectSkillRequirementRead> {
  const body = await apiFetch<{ data: ProjectSkillRequirementRead }>(
    `/projects/${projectId}/skill-requirements`,
    { method: "POST", body: JSON.stringify(payload) },
  );
  return body.data;
}

export async function updateProjectSkillRequirement(
  requirementId: string,
  payload: ProjectSkillRequirementUpdatePayload,
): Promise<ProjectSkillRequirementRead> {
  const body = await apiFetch<{ data: ProjectSkillRequirementRead }>(
    `/skill-requirements/${requirementId}`,
    { method: "PATCH", body: JSON.stringify(payload) },
  );
  return body.data;
}

export async function deleteProjectSkillRequirement(requirementId: string): Promise<void> {
  await apiFetch<void>(`/skill-requirements/${requirementId}`, { method: "DELETE" });
}

export async function getProjectSkillMatrix(projectId: string): Promise<SkillMatrixRead> {
  const body = await apiFetch<{ data: SkillMatrixRead }>(`/projects/${projectId}/skill-matrix`);
  return body.data;
}

export async function getProjectTrainingGaps(projectId: string): Promise<TrainingGapSummaryRead> {
  const body = await apiFetch<{ data: TrainingGapSummaryRead }>(
    `/projects/${projectId}/training-gaps`,
  );
  return body.data;
}

export async function listProjectCapabilityGaps(projectId: string): Promise<CapabilityGapRead[]> {
  const body = await apiFetch<{ data: CapabilityGapRead[] }>(
    `/projects/${projectId}/capability-gaps?limit=100`,
  );
  return body.data;
}

export async function detectProjectCapabilityGaps(
  projectId: string,
): Promise<CapabilityGapDetectionResponse> {
  const body = await apiFetch<{ data: CapabilityGapDetectionResponse }>(
    `/projects/${projectId}/capability-gaps/detect`,
    { method: "POST" },
  );
  return body.data;
}

export async function updateCapabilityGap(
  gapId: string,
  payload: CapabilityGapUpdatePayload,
): Promise<CapabilityGapRead> {
  const body = await apiFetch<{ data: CapabilityGapRead }>(`/capability-gaps/${gapId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return body.data;
}

export async function deleteCapabilityGap(gapId: string): Promise<void> {
  await apiFetch<void>(`/capability-gaps/${gapId}`, { method: "DELETE" });
}

export async function generateWorkforceRecommendations(
  projectId: string,
): Promise<WorkforceRecommendationGenerateResponse> {
  const body = await apiFetch<{ data: WorkforceRecommendationGenerateResponse }>(
    `/projects/${projectId}/workforce-recommendations/generate`,
    { method: "POST" },
  );
  return body.data;
}
