variable "project_id" {
  description = "Google Cloud Project ID"
  type        = string
  default     = "agenticsetup-510220"
}

variable "region" {
  description = "Google Cloud deployment region for Cloud Run and Artifact Registry"
  type        = string
  default     = "us-central1"
}

variable "vertex_location" {
  description = "Vertex AI location for Gemini models (global or us)"
  type        = string
  default     = "global"
}

variable "service_name" {
  description = "Name of the Cloud Run service"
  type        = string
  default     = "adk-healthcare-agent"
}

variable "github_repo" {
  description = "GitHub repository (owner/repo) allowed to authenticate via Workload Identity Federation"
  type        = string
  default     = "phanisagiraju-byte/adk-healthcare-agent"
}

variable "container_image" {
  description = "Full Artifact Registry container image URI to deploy"
  type        = string
  default     = "us-central1-docker.pkg.dev/agenticsetup-510220/adk-healthcare-repo/adk-healthcare-agent:latest"
}

variable "min_instances" {
  description = "Minimum number of Cloud Run container instances"
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum number of Cloud Run container instances"
  type        = number
  default     = 5
}
