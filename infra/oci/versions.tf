# Providers. OCI reads your API key from ~/.oci/config (the profile in var.oci_profile): the console's
# "Profile → API keys → Add API key" gives you the file's contents, or run `oci setup config`.

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 6.0.0, < 9.0.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }
}

provider "oci" {
  region              = var.region
  config_file_profile = var.oci_profile
}
