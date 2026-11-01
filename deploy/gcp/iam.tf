# The service runs as dealfinder-run, which can read one secret and nothing else.
resource "google_service_account" "run" {
  account_id   = "dealfinder-run"
  display_name = "DealFinder Cloud Run service"
}

# CI deploys as dealfinder-deploy through Workload Identity Federation (wif.tf).
resource "google_service_account" "deploy" {
  account_id   = "dealfinder-deploy"
  display_name = "DealFinder CI deploy"
}

resource "google_secret_manager_secret_iam_member" "run_reads_env" {
  secret_id = google_secret_manager_secret.env.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.run.email}"
}

resource "google_project_iam_member" "deploy_run_developer" {
  project = var.project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

resource "google_artifact_registry_repository_iam_member" "deploy_pushes" {
  location   = google_artifact_registry_repository.dealfinder.location
  repository = google_artifact_registry_repository.dealfinder.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deploy.email}"
}

# Deploying a revision that runs as dealfinder-run needs actAs on it.
resource "google_service_account_iam_member" "deploy_acts_as_run" {
  service_account_id = google_service_account.run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}
