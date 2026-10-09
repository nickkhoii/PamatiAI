# Database

MySQL 8.4, InnoDB and utf8mb4. Explicit Alembic migrations create 39 normalized domain/authentication tables, consent/provenance/audit triggers and evidence constraints. Run migrations explicitly; never call metadata.create_all during application startup. Back up and test restoration before production migrations. Initialization and seed commands, entity relationships and privacy boundaries are documented in [DATABASE.md](../docs/DATABASE.md).

Compose deliberately does not expose MySQL on the host. Local Python readiness requires your own accessible MySQL instance; use Compose for the integrated database.
