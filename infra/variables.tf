variable "db_user" {
  type    = string
  default = "dealfinder"
}

variable "db_password" {
  type    = string
  default = "dealfinder" # local dev only; override for anything shared
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
