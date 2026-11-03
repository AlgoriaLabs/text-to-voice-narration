# The server: one Ampere A1 (arm64) VM on Oracle Cloud's Always Free tier, in its own network, open on 80 and 443
# (Caddy, HTTPS) and 22 (SSH, for Terraform's deploys). cloud-init installs Docker; deploy.tf ships the app.

locals {
  compartment_id = var.compartment_ocid != "" ? var.compartment_ocid : var.tenancy_ocid
  ad             = data.oci_identity_availability_domains.all.availability_domains[var.availability_domain_index].name
  image_id       = var.image_ocid != "" ? var.image_ocid : data.oci_core_images.ubuntu.images[0].id
}

data "oci_identity_availability_domains" "all" {
  compartment_id = var.tenancy_ocid
}

data "oci_core_images" "ubuntu" {
  compartment_id           = local.compartment_id
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"

  # The full image, not the Minimal one.
  filter {
    name   = "display_name"
    values = ["^Canonical-Ubuntu-24\\.04-aarch64-.*"]
    regex  = true
  }
}

# --- Network ----------------------------------------------------------------------------------------------------

resource "oci_core_vcn" "main" {
  compartment_id = local.compartment_id
  cidr_blocks    = ["10.42.0.0/16"]
  display_name   = "${var.name}-vcn"
  dns_label      = "narration"
}

resource "oci_core_internet_gateway" "main" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.name}-igw"
  enabled        = true
}

resource "oci_core_route_table" "public" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.name}-public"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.main.id
  }
}

resource "oci_core_security_list" "public" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "${var.name}-public"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  ingress_security_rules {
    description = "SSH"
    protocol    = "6"
    source      = var.ssh_allowed_cidr
    tcp_options {
      min = 22
      max = 22
    }
  }

  dynamic "ingress_security_rules" {
    for_each = { http = 80, https = 443 }
    content {
      description = ingress_security_rules.key
      protocol    = "6"
      source      = "0.0.0.0/0"
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }

  ingress_security_rules {
    description = "HTTP/3"
    protocol    = "17"
    source      = "0.0.0.0/0"
    udp_options {
      min = 443
      max = 443
    }
  }

  # Path MTU discovery.
  ingress_security_rules {
    protocol = "1"
    source   = "0.0.0.0/0"
    icmp_options {
      type = 3
      code = 4
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id             = local.compartment_id
  vcn_id                     = oci_core_vcn.main.id
  cidr_block                 = "10.42.1.0/24"
  display_name               = "${var.name}-public"
  dns_label                  = "public"
  route_table_id             = oci_core_route_table.public.id
  security_list_ids          = [oci_core_security_list.public.id]
  prohibit_public_ip_on_vnic = false
}

# --- The server -------------------------------------------------------------------------------------------------

resource "oci_core_instance" "server" {
  compartment_id      = local.compartment_id
  availability_domain = local.ad
  display_name        = var.name
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_gb
  }

  source_details {
    source_type             = "image"
    source_id               = local.image_id
    boot_volume_size_in_gbs = var.boot_volume_gb
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = !var.assign_reserved_ip
    hostname_label   = var.name
  }

  metadata = {
    ssh_authorized_keys = trimspace(file(pathexpand(var.ssh_public_key_path)))
    user_data           = base64encode(file("${path.module}/cloud-init.yaml"))
  }

  preserve_boot_volume = false

  lifecycle {
    # A newer Ubuntu image or an edited cloud-init must not replace a running server (and its address and data).
    ignore_changes = [source_details[0].source_id, metadata]
  }
}

data "oci_core_vnic_attachments" "server" {
  compartment_id = local.compartment_id
  instance_id    = oci_core_instance.server.id
}

data "oci_core_private_ips" "server" {
  vnic_id = data.oci_core_vnic_attachments.server.vnic_attachments[0].vnic_id
}

resource "oci_core_public_ip" "reserved" {
  count          = var.assign_reserved_ip ? 1 : 0
  compartment_id = local.compartment_id
  lifetime       = "RESERVED"
  display_name   = "${var.name}-ip"
  private_ip_id  = data.oci_core_private_ips.server.private_ips[0].id
}

locals {
  public_ip   = var.assign_reserved_ip ? oci_core_public_ip.reserved[0].ip_address : oci_core_instance.server.public_ip
  site        = var.domain != "" ? var.domain : "${replace(local.public_ip, ".", "-")}.sslip.io"
  origin      = "https://${local.site}"
  ssh_command = "ssh ubuntu@${local.public_ip}"
}
