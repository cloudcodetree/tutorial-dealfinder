# Cloud Run's automatic request log records each request's full URL, query included,
# so a check's product name and price would sit in Cloud Logging for 30 days. The app
# writes its own JSON request log with no query text (dealfinder/observability.py),
# and uvicorn runs with --no-access-log. Exclusions are free.
resource "google_logging_project_exclusion" "run_request_urls" {
  project     = var.project_id
  name        = "dealfinder-run-request-urls"
  description = "Drop Cloud Run's automatic request log: it records full URLs, query text included."
  filter      = "resource.type=\"cloud_run_revision\" AND log_name:\"run.googleapis.com%2Frequests\""
}
