# Ships the app: zips this project (without node_modules, models, .env, data or Terraform's own files), uploads it
# over SSH with your settings, and runs deploy/install.sh on the server, which builds the image there and starts
# Caddy and the service. Every `terraform apply` after a change to the code, provider.config.json or .env ships
# again; nothing changes when nothing did.
#
# It waits until .env has PAY_TO and FACILITATOR_AUTH: the service can't take payments without them. The first
# apply makes the server and its address; `npm run launch` then registers that address and saves PAY_TO and
# AGENT_ID; the next apply deploys.

locals {
  env_text = fileexists(var.env_file) ? file(var.env_file) : ""
  # KEY=value lines; the last one wins when a key repeats, as in Node's --env-file.
  dotenv_all = {
    for line in split("\n", local.env_text) :
    trimspace(split("=", line)[0]) => trim(trimspace(join("=", slice(split("=", line), 1, length(split("=", line))))), "\"'")...
    if length(regexall("^\\s*[A-Z][A-Z0-9_]*\\s*=", line)) > 0
  }
  dotenv = { for key, values in local.dotenv_all : key => values[length(values) - 1] }
  pay_to           = lookup(local.dotenv, "PAY_TO", "")
  agent_id         = lookup(local.dotenv, "AGENT_ID", "")
  facilitator_auth = lookup(local.dotenv, "FACILITATOR_AUTH", "")
  soroban_rpc_url  = lookup(local.dotenv, "SOROBAN_RPC_URL", "") != "" ? lookup(local.dotenv, "SOROBAN_RPC_URL", "") : "https://mainnet.sorobanrpc.com"
  ready            = local.pay_to != "" && local.facilitator_auth != ""

  # deploy/.env on the server. Single quotes: Docker Compose takes such values literally (no $ expansion).
  server_values = {
    SITE_ADDRESS     = local.site
    PUBLIC_ORIGIN    = local.origin
    PAY_TO           = local.pay_to
    AGENT_ID         = local.agent_id
    FACILITATOR_AUTH = local.facilitator_auth
    SOROBAN_RPC_URL  = local.soroban_rpc_url
    KOKORO_MODEL     = var.kokoro_model
    TTS_WORKERS      = tostring(var.tts_workers > 0 ? var.tts_workers : var.ocpus)
  }
  server_env = join("\n", concat(
    ["# Written by Terraform from ${var.env_file}. No Stellar secret key: PAY_TO is a public address."],
    [for key, value in local.server_values : "${key}='${replace(value, "'", "")}'"],
    [""],
  ))
}

data "archive_file" "release" {
  type        = "zip"
  source_dir  = "${path.module}/../.."
  output_path = "${path.module}/.build/release.zip"
  excludes = [
    ".git/**", "node_modules/**", ".venv/**", "models/**", "data/**", "**/__pycache__/**", ".pytest_cache/**",
    ".env", ".env.*", "deploy/.env", "jobs.sqlite*", "infra/**",
  ]
}

resource "terraform_data" "deploy" {
  count = local.ready ? 1 : 0

  triggers_replace = [
    oci_core_instance.server.id,
    data.archive_file.release.output_sha256,
    sha256(local.server_env),
  ]

  connection {
    type        = "ssh"
    host        = local.public_ip
    user        = "ubuntu"
    agent       = var.ssh_use_agent
    private_key = var.ssh_use_agent ? null : file(pathexpand(var.ssh_private_key_path))
    timeout     = "10m"
  }

  # First boot installs Docker: wait for it.
  provisioner "remote-exec" {
    inline = [
      "cloud-init status --wait >/dev/null 2>&1 || true",
      "test -f /opt/narration/.ready && command -v docker >/dev/null || { echo 'Docker is not installed: see /var/log/cloud-init-output.log on the server'; exit 1; }",
    ]
  }

  provisioner "file" {
    source      = data.archive_file.release.output_path
    destination = "/opt/narration/release.zip"
  }

  provisioner "file" {
    content     = local.server_env
    destination = "/opt/narration/narration.env"
  }

  provisioner "remote-exec" {
    inline = [
      "chmod 600 /opt/narration/narration.env",
      "rm -rf /opt/narration/release && unzip -q /opt/narration/release.zip -d /opt/narration/release",
      "sudo sh /opt/narration/release/deploy/install.sh",
    ]
  }
}
