# What `terraform output` shows, and what npm run launch reads (public_origin).

output "public_ip" {
  description = "The server's public IPv4 address."
  value       = local.public_ip
}

output "public_origin" {
  description = "The service's HTTPS address: register this one (npm run launch)."
  value       = local.origin
}

output "manifest_url" {
  description = "Where agents read the services, prices and schemas."
  value       = "${local.origin}/.well-known/stellar-agent-services.json"
}

output "ssh" {
  description = "Log in to the server."
  value       = local.ssh_command
}

output "next" {
  description = "What to do now."
  value = local.ready ? (
    "Deployed ${local.origin}. Check it: npm run status. Logs: ${local.ssh_command} 'cd /opt/narration/app/deploy && sudo docker compose logs -f'"
    ) : (
    "The server is up at ${local.origin}, waiting for the app. Put FACILITATOR_AUTH in .env, run npm run launch (your wallet registers ${local.origin} and saves PAY_TO and AGENT_ID), then terraform apply again."
  )
}
