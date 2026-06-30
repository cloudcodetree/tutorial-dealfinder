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
