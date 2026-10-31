terraform {
  required_version = ">= 1.9.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.9"
    }
  }
  # Local state, single operator, the same as the site's infra/. The state holds
  # resource names and ids only: no secret value ever enters it (secrets.tf).
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Budgets are billing-account resources. The API needs a quota project, so this
# alias bills the calls to the DealFinder project itself.
provider "google" {
  alias                 = "billing"
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}
