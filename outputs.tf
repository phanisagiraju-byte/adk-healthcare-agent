output "cloud_run_service_url" {
  description = "Public URL of the deployed ADK Healthcare Scheduling Agent Cloud Run service"
  value       = google_cloud_run_v2_service.healthcare_agent.uri
}

output "service_account_email" {
  description = "Email of the least-privilege service account running the agent"
  value       = google_service_account.agent_sa.email
}

output "workload_identity_provider" {
  description = "Full Workload Identity Provider resource name for GitHub Actions"
  value       = google_iam_workload_identity_pool_provider.github_provider.name
}

output "artifact_registry_repository" {
  description = "Artifact Registry Docker repository ID"
  value       = google_artifact_registry_repository.agent_repo.repository_id
}

output "firestore_database_name" {
  description = "Firestore Native database name used for session state persistence"
  value       = google_firestore_database.session_db.name
}
