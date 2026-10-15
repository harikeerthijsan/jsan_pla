import {
  bucket,
  defineRailway,
  group,
  postgres,
  project,
  service,
} from "railway/iac";

// Each Railway environment gets its own Postgres, bucket and secrets; references like
// ${{pla-files.BUCKET}} resolve inside the environment being deployed, never across environments.
// APP_ENV follows the Railway environment so a staging or PR environment can never claim to be production.
function appEnvFor(environment: string): string {
  if (environment === "production") return "production";
  if (environment === "staging") return "staging";
  return "preview";
}

export default defineRailway((ctx) => {
  const database = postgres("Postgres");
  const files = bucket("pla-files", { region: "sin" });

  // Settings both services need: same database, bucket and environment. Secrets (JWT_SECRET, ADMIN_EMAIL,
  // ADMIN_PASSWORD) are set on BOTH services in the dashboard; startup refuses to run without them.
  const shared = {
    APP_ENV: appEnvFor(ctx.environment),
    APP_VERSION: "3.4.1-operational",
    AUTO_CONFIGURE_BUCKET_CORS: "true",
    BUCKET: "${{pla-files.BUCKET}}",
    BUCKET_ACCESS_KEY_ID: "${{pla-files.ACCESS_KEY_ID}}",
    BUCKET_ENDPOINT: "${{pla-files.ENDPOINT}}",
    BUCKET_REGION: "${{pla-files.REGION}}",
    BUCKET_SECRET_ACCESS_KEY: "${{pla-files.SECRET_ACCESS_KEY}}",
    DATABASE_URL: database.env.DATABASE_URL,
    DB_CONNECT_TIMEOUT: "120",
    S3_ADDRESSING_STYLE: "virtual",
    SEED_DEMO: "false",
    STORAGE_MODE: "s3",
    WORKER_POLL_SECONDS: "3",
    WORKER_LEASE_SECONDS: "1800",
    WORKER_HEARTBEAT_SECONDS: "30",
    WORKER_MAX_ATTEMPTS: "3",
  };

  // Website + API only. Several uvicorn processes per replica; past WEB_LIMIT_CONCURRENCY open requests a process
  // answers 503 at once instead of hanging. Postgres connections: replicas x WEB_CONCURRENCY x (DB_POOL_SIZE +
  // DB_MAX_OVERFLOW) + the worker must stay under the database limit (Railway Postgres default: 100).
  const app = service("pla-qc", {
    // /health/ready checks the database and storage configuration before Railway switches traffic.
    healthcheck: "/health/ready",
    healthcheckTimeout: 180,
    replicas: { "asia-southeast1-eqsg3a": 1 },
    env: {
      ...shared,
      PROCESS_ROLE: "web",
      WEB_CONCURRENCY: "2",
      WEB_LIMIT_CONCURRENCY: "200",
      DB_POOL_SIZE: "5",
      DB_MAX_OVERFLOW: "10",
      DB_POOL_TIMEOUT: "15",
      WORKBOOK_BUILD_CONCURRENCY: "2",
    },
  });

  // LiDAR processing (PDAL) in its own service, so conversions never slow down or crash the website. No public
  // domain and no healthcheck: it only talks to Postgres and the bucket.
  const worker = service("pla-qc-worker", {
    replicas: { "asia-southeast1-eqsg3a": 1 },
    env: {
      ...shared,
      PROCESS_ROLE: "worker",
      DB_POOL_SIZE: "2",
      DB_MAX_OVERFLOW: "2",
    },
  });

  return project("jsan-pla-qc", {
    resources: [group("Application", [app, worker, database, files])],
  });
});
