variable "db_user" {
  type    = string
  default = "dealfinder"
}

variable "db_password" {
  type      = string
  sensitive = true
  # Local-dev default; the DB is bound to loopback only (see main.tf). For
  # anything shared, override via TF_VAR_db_password and use a managed DB.
  default = "dealfinder"
}

variable "db_name" {
  type    = string
  default = "dealfinder"
}

variable "db_port" {
  type        = number
  default     = 5433 # host port (avoids clashing with a local 5432)
  description = "Host port to expose Postgres on."
}

variable "app_port" {
  type        = number
  default     = 8000
  description = "Host port to expose the DealFinder app on (loopback)."
}

# Live-source credentials passed to the app container. Provide via TF_VAR_* env
# or a gitignored terraform.tfvars; empty = that source stays off.
variable "apify_token" {
  type      = string
  sensitive = true
  default   = ""
}

variable "apify_actor" {
  type    = string
  default = "automation-lab~google-shopping-scraper"
}

variable "rapidapi_key" {
  type      = string
  sensitive = true
  default   = ""
}
