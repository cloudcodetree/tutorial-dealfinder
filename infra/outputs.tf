output "database_url" {
  description = "Connection string for the local pgvector Postgres."
  value       = "postgresql://${var.db_user}:${var.db_password}@localhost:${var.db_port}/${var.db_name}"
  sensitive   = true
}

output "container" {
  value = docker_container.db.name
}

output "app_url" {
  description = "DealFinder web app once the stack is up."
  value       = "http://localhost:${var.app_port}"
}
