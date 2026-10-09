# Private networking for Cloud SQL (spec section 4/5, README's "Service Networking" API):
# without this, `database.tf`'s `private_ip_address` is never populated (it needs a VPC
# peered to Google's service-producer network) and Cloud Run has nothing to reach it through.
# A dedicated, custom-mode VPC with one subnet in `var.gcp_region` -- not the project's
# implicit `default` network -- so this module stays self-contained: everything it needs is
# something it created and can `terraform destroy` itself, nothing it only half-manages.

resource "google_compute_network" "demo" {
  name                    = "${var.demo_name}-network"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "demo" {
  name          = "${var.demo_name}-subnet"
  network       = google_compute_network.demo.id
  region        = var.gcp_region
  ip_cidr_range = "10.10.0.0/24" # Cloud Run's direct VPC egress needs a subnet in the region.
}

# A separate, reserved range for Google's own service producers (Cloud SQL's private IP lives
# in this range, not in the subnet above) -- Service Networking's own required shape.
resource "google_compute_global_address" "private_services_range" {
  name          = "${var.demo_name}-private-services"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.demo.id
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.demo.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services_range.name]
}
