# One secret holds every key as a JSON object (deploy/secrets.py writes it, keeping
# one active version inside the free 6). There is deliberately no secret version
# resource: values never enter OpenTofu state.
resource "google_secret_manager_secret" "env" {
  secret_id = "dealfinder-env"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}
