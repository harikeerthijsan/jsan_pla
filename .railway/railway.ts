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

  const app = service("pla-qc", {
    // /health/ready checks the database and storage configuration before Railway switches traffic.
    healthcheck: "/health/ready",
    healthcheckTimeout: 180,
    replicas: { "asia-southeast1-eqsg3a": 1 },
    env: {
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
    },
  });

  return project("jsan-pla-qc", {
    resources: [group("Application", [app, database, files])],
  });
});
