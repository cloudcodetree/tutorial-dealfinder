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
  # Pinned by digest (supply-chain): pgvector/pgvector:pg16 at the time of writing.
  name = "pgvector/pgvector@sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6"
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
    ip       = "127.0.0.1" # loopback only — never expose the DB on the network
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

# --- the DealFinder app (built from the repo Dockerfile) ---

resource "docker_image" "app" {
  name = "dealfinder-app:local"
  build {
    context = abspath("${path.module}/..")
  }
  triggers = {
    dockerfile = filesha1("${path.module}/../Dockerfile")
  }
}

resource "docker_container" "app" {
  name       = "dealfinder-app"
  image      = docker_image.app.image_id
  restart    = "unless-stopped"
  depends_on = [docker_container.db]

  # App talks to the DB over the shared network by container name.
  env = [
    "DATABASE_URL=postgresql://${var.db_user}:${var.db_password}@${docker_container.db.name}:5432/${var.db_name}",
    "APIFY_TOKEN=${var.apify_token}",
    "APIFY_ACTOR=${var.apify_actor}",
    "RAPIDAPI_KEY=${var.rapidapi_key}",
    "FIRECRAWL_API_KEY=${var.firecrawl_api_key}",
    "EBAY_APP_ID=${var.ebay_app_id}",
    "EBAY_CERT_ID=${var.ebay_cert_id}",
    "EBAY_CAMPAIGN_ID=${var.ebay_campaign_id}",
    "OPENROUTER_API_KEY=${var.openrouter_api_key}",
    "SHOPIFY_STORES=${var.shopify_stores}",
    "BESTBUY_API_KEY=${var.bestbuy_api_key}",
  ]

  ports {
    internal = 8000
    external = var.app_port
    ip       = "127.0.0.1"
  }

  networks_advanced {
    name = docker_network.net.name
  }
}
