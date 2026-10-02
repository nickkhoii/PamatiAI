# Database

MySQL 8.4, InnoDB and utf8mb4. The initial Alembic revision creates only the migration baseline, with no student-data schema. Run migrations explicitly; never call metadata.create_all during application startup. Future migrations require reviewed consent, ownership, foreign keys, indexes, retention and audit behavior. Back up and test restoration before production migrations.

Compose deliberately does not expose MySQL on the host. Local Python readiness requires your own accessible MySQL instance; use Compose for the integrated database.
