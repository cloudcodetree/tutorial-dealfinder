# One Docker repo. The cleanup policies keep the two newest images and delete the
# rest, so storage stays inside Artifact Registry's free 0.5 GB.
resource "google_artifact_registry_repository" "dealfinder" {
  location      = var.region
  repository_id = "dealfinder"
  format        = "DOCKER"

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-2"
    action = "KEEP"
    most_recent_versions {
      keep_count = 2
    }
  }

  cleanup_policies {
    id     = "delete-rest"
    action = "DELETE"
    condition {
      tag_state = "ANY"
    }
  }

  depends_on = [google_project_service.apis]
}
