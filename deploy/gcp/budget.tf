data "google_project" "this" {
  project_id = var.project_id
}

# Alerts by email at 50%, 90% and 100% of $1, and when the forecast reaches $1.
# A budget alerts. It does not stop spending: the $0 design is what keeps it at $0.
resource "google_billing_budget" "one_dollar" {
  provider        = google.billing
  billing_account = var.billing_account
  display_name    = "dealfinder: $1"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = "1"
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  depends_on = [google_project_service.apis]
}
