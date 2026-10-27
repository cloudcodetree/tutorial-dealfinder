variable "project_id" {
  type        = string
  description = "The GCP project that holds DealFinder, e.g. dealfinder-prod-<suffix>."
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "billing_account" {
  type        = string
  description = "Billing account id (XXXXXX-XXXXXX-XXXXXX), for the $1 budget."
}

variable "github_repo" {
  type    = string
  default = "cloudcodetree/tutorial-dealfinder"
}

# CI owns the real image (lifecycle.ignore_changes). The first apply needs any image
# that serves on $PORT, so it starts from Google's sample.
variable "bootstrap_image" {
  type    = string
  default = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "supabase_url" {
  type = string
}

variable "supabase_publishable_key" {
  type        = string
  description = "Public by design: the browser uses it. Not a secret."
}

# Launch without Best Buy (2026-10-27): only Check a deal rates. Set "live" once a
# Best Buy key is in dealfinder-env.
variable "verdict_mode" {
  type    = string
  default = "check"
}

variable "bestbuy_logo" {
  type    = bool
  default = false
}
