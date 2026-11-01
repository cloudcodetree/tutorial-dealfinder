resource "google_cloud_run_v2_service" "api" {
  name                = "dealfinder-api"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  # Public without an allUsers grant, which the organization's domain-restricted-
  # sharing policy refuses. The Worker cannot mint Google ID tokens cheaply, so the
  # backend's edge guard (EDGE_SHARED_SECRET) is the access control instead.
  invoker_iam_disabled = true

  template {
    service_account                  = google_service_account.run.email
    max_instance_request_concurrency = 10
    timeout                          = "30s"

    # Scale to zero, and never past 2, so a traffic spike cannot create a bill.
    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.bootstrap_image

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle          = true # request-based billing: CPU only while serving
        startup_cpu_boost = true
      }

      env {
        name  = "DEALFINDER_ENV"
        value = "production"
      }
      # No BESTBUY_API_KEY at launch, so this source is off until a key arrives.
      env {
        name  = "DEALFINDER_SOURCES"
        value = "BestBuy"
      }
      env {
        name  = "DEALFINDER_VERDICT_MODE"
        value = var.verdict_mode
      }
      env {
        name  = "SUPABASE_URL"
        value = var.supabase_url
      }
      env {
        name  = "SUPABASE_PUBLISHABLE_KEY"
        value = var.supabase_publishable_key
      }
      env {
        name  = "DEALFINDER_BESTBUY_LOGO"
        value = var.bestbuy_logo ? "1" : "0"
      }
      env {
        name = "DEALFINDER_SECRETS_JSON"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.env.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  # CI deploys the real image. OpenTofu must not roll it back to the bootstrap one.
  lifecycle {
    ignore_changes = [template[0].containers[0].image, client, client_version]
  }

  depends_on = [google_project_service.apis, google_secret_manager_secret_iam_member.run_reads_env]
}
