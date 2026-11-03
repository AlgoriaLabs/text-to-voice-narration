# What you set in terraform.tfvars (copy terraform.tfvars.example). Only tenancy_ocid and region are required.

variable "tenancy_ocid" {
  description = "Your tenancy's OCID (ocid1.tenancy.oc1..), from ~/.oci/config or the console's Tenancy details."
  type        = string
}

variable "region" {
  description = "Your home region, such as eu-frankfurt-1: Always Free resources are only free there."
  type        = string
}

variable "oci_profile" {
  description = "The profile in ~/.oci/config to sign API calls with."
  type        = string
  default     = "DEFAULT"
}

variable "compartment_ocid" {
  description = "Where to create everything. Empty: the tenancy's root compartment."
  type        = string
  default     = ""
}

variable "name" {
  description = "Prefix for resource names, and the server's hostname."
  type        = string
  default     = "narration"
}

# --- The server -------------------------------------------------------------------------------------------------

variable "ocpus" {
  description = "Ampere A1 cores. Always Free covers 2 OCPUs and 12 GB in total (1,500 OCPU hours a month)."
  type        = number
  default     = 2
}

variable "memory_gb" {
  description = "Memory in GB. 6 GB per OCPU keeps it inside Always Free."
  type        = number
  default     = 12
}

variable "boot_volume_gb" {
  description = "Boot volume size. Always Free covers 200 GB of block storage in total."
  type        = number
  default     = 50
}

variable "availability_domain_index" {
  description = "Which availability domain to use (0, 1 or 2). Try another one on \"Out of host capacity\"."
  type        = number
  default     = 0
}

variable "image_ocid" {
  description = "An Ubuntu aarch64 image OCID. Empty: the newest Canonical Ubuntu 24.04 for Ampere A1."
  type        = string
  default     = ""
}

variable "assign_reserved_ip" {
  description = "Use a reserved public IP, which outlives the server. Off: an ephemeral IP, kept for the server's life."
  type        = bool
  default     = false
}

# --- Access -----------------------------------------------------------------------------------------------------

variable "ssh_public_key_path" {
  description = "Your SSH public key, for the ubuntu user."
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "ssh_private_key_path" {
  description = "The matching private key: Terraform uses it to upload releases. It never leaves your computer."
  type        = string
  default     = "~/.ssh/id_ed25519"
}

variable "ssh_use_agent" {
  description = "Sign SSH with ssh-agent instead of reading ssh_private_key_path: for a key with a passphrase."
  type        = bool
  default     = false
}

variable "ssh_allowed_cidr" {
  description = "Who may reach SSH (port 22). Narrow it to your own address, such as 203.0.113.7/32."
  type        = string
  default     = "0.0.0.0/0"
}

# --- The service ------------------------------------------------------------------------------------------------

variable "domain" {
  description = "Your own domain for the service, with an A record pointing at the server's IP. Empty: <ip>.sslip.io."
  type        = string
  default     = ""
}

variable "env_file" {
  description = "The project's .env: PAY_TO, AGENT_ID, FACILITATOR_AUTH and SOROBAN_RPC_URL are read from it."
  type        = string
  default     = "../../.env"
}

variable "kokoro_model" {
  description = "kokoro-v1.0.onnx (full precision) or kokoro-v1.0.int8.onnx (smaller, slightly lower quality)."
  type        = string
  default     = "kokoro-v1.0.onnx"
}

variable "tts_workers" {
  description = "Text chunks read in parallel. 0: one per OCPU."
  type        = number
  default     = 0
}
