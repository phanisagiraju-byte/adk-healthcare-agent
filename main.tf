# 1. Enable Required Google Cloud APIs
locals {
  required_apis = [
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtrace.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "sts.googleapis.com",
  ]
}

resource "google_project_service" "enabled_apis" {
  for_each           = toset(local.required_apis)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# 2. Artifact Registry Repository for Container Images
resource "google_artifact_registry_repository" "agent_repo" {
  location      = var.region
  repository_id = "adk-healthcare-repo"
  description   = "Docker repository for the ADK Healthcare Scheduling Agent"
  format        = "DOCKER"

  depends_on = [google_project_service.enabled_apis]
}

# 3. Google Cloud Firestore Database for Persistent Session State
resource "google_firestore_database" "session_db" {
  project     = var.project_id
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  depends_on = [google_project_service.enabled_apis]
}

# 4. Least-Privilege Service Account & IAM Bindings
resource "google_service_account" "agent_sa" {
  account_id   = "adk-healthcare-agent-sa"
  display_name = "ADK Healthcare Scheduling Agent Service Account"
  project      = var.project_id
}

locals {
  agent_iam_roles = [
    "roles/aiplatform.user",
    "roles/artifactregistry.admin",
    "roles/cloudbuild.builds.editor",
    "roles/cloudtrace.agent",
    "roles/datastore.owner",
    "roles/datastore.user",
    "roles/iam.serviceAccountUser",
    "roles/logging.logWriter",
    "roles/run.admin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/storage.admin",
  ]
}

resource "google_project_iam_member" "agent_sa_roles" {
  for_each = toset(local.agent_iam_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.agent_sa.email}"
}

# 5. Workload Identity Federation (WIF) for GitHub Actions (Keyless OIDC Auth)
resource "google_iam_workload_identity_pool" "github_pool" {
  project                   = var.project_id
  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions Pool"
  description               = "Workload Identity Pool for keyless GitHub Actions CI/CD"

  depends_on = [google_project_service.enabled_apis]
}

resource "google_iam_workload_identity_pool_provider" "github_provider" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc-provider"
  display_name                       = "GitHub OIDC Provider"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  attribute_condition = "assertion.repository == '${var.github_repo}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "wif_impersonation" {
  service_account_id = google_service_account.agent_sa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github_pool.name}/attribute.repository/${var.github_repo}"
}

# 6. Google Cloud Run v2 Service
resource "google_cloud_run_v2_service" "healthcare_agent" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.agent_sa.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.container_image

      ports {
        container_port = 8080
      }

      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.vertex_location
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "1Gi"
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 5
        period_seconds        = 10
        failure_threshold     = 3
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        period_seconds = 30
      }
    }
  }

  depends_on = [
    google_project_service.enabled_apis,
    google_project_iam_member.agent_sa_roles,
    google_firestore_database.session_db,
  ]
}
