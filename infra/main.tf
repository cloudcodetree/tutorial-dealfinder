# DealFinder infrastructure as code (Terraform / OpenTofu).
#
#   tofu init      # one-time: download the docker provider
#   tofu apply     # bring the whole stack up
#   tofu destroy   # tear it all down
#
# This default stack runs a real Postgres + pgvector locally via the Docker
# provider (free, instant, IPv4). Point DATABASE_URL at a managed Postgres
# (e.g. Supabase pooler) to use the same schema in the cloud — same code.

terraform {
  required_version = ">= 1.6"
  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

resource "docker_network" "net" {
  name = "dealfinder-net"
}

resource "docker_volume" "db" {
  name = "dealfinder-db-data"
}

resource "docker_image" "pgvector" {
  name = "pgvector/pgvector:pg16"
}

resource "docker_container" "db" {
  name    = "dealfinder-db"
  image   = docker_image.pgvector.image_id
  restart = "unless-stopped"

  env = [
    "POSTGRES_USER=${var.db_user}",
    "POSTGRES_PASSWORD=${var.db_password}",
    "POSTGRES_DB=${var.db_name}",
  ]

  ports {
    internal = 5432
    external = var.db_port
  }

  networks_advanced {
    name = docker_network.net.name
  }

  volumes {
    volume_name    = docker_volume.db.name
    container_path = "/var/lib/postgresql/data"
  }

  healthcheck {
    test     = ["CMD-SHELL", "pg_isready -U ${var.db_user} -d ${var.db_name}"]
    interval = "5s"
    timeout  = "3s"
    retries  = 12
  }
}
