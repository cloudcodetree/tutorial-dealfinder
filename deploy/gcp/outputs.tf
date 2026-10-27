output "api_url" {
  description = "The run.app URL. The Worker's BACKEND_ORIGIN."
  value       = google_cloud_run_v2_service.api.uri
}

output "wif_provider" {
  description = "Repo variable GCP_WIF_PROVIDER."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deploy_service_account" {
  description = "Repo variable GCP_DEPLOY_SA."
  value       = google_service_account.deploy.email
}

output "registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.dealfinder.repository_id}"
}
