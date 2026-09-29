import {
  bucket,
  defineRailway,
  group,
  postgres,
  project,
  service,
} from "railway/iac";

export default defineRailway(() => {
  const database = postgres("Postgres");
  const files = bucket("pla-files", { region: "sin" });

  const app = service("pla-qc", {
    healthcheck: "/health",
    healthcheckTimeout: 180,
    replicas: { "asia-southeast1-eqsg3a": 1 },
    env: {
      APP_ENV: "production",
      AUTO_CONFIGURE_BUCKET_CORS: "true",
      BUCKET: "${{pla-files.BUCKET}}",
      BUCKET_ACCESS_KEY_ID: "${{pla-files.ACCESS_KEY_ID}}",
      BUCKET_CORS_ORIGINS: "*",
      BUCKET_ENDPOINT: "${{pla-files.ENDPOINT}}",
      BUCKET_REGION: "${{pla-files.REGION}}",
      BUCKET_SECRET_ACCESS_KEY: "${{pla-files.SECRET_ACCESS_KEY}}",
      DATABASE_URL: database.env.DATABASE_URL,
      DB_CONNECT_TIMEOUT: "120",
      S3_ADDRESSING_STYLE: "virtual",
      SEED_DEMO: "false",
      STORAGE_MODE: "s3",
      WORKER_POLL_SECONDS: "3",
    },
  });

  return project("jsan-pla-qc", {
    resources: [group("Application", [app, database, files])],
  });
});
