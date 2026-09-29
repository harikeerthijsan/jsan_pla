# Deployment architecture

```text
Browser / Vercel
  |-- metadata, authentication, review decisions --> Railway API
  |-- large source uploads ------------------------> Railway Bucket (presigned)
  |-- COPC HTTP reads -----------------------------> Railway Bucket (presigned)

Railway API --> PostgreSQL
Railway Worker --> PostgreSQL
Railway Worker --> Railway Bucket
Railway Worker --> PDAL 2.10.2
```

The API does not act as a point-cloud proxy. This keeps application-service memory and egress away from multi-hundred-MB LiDAR objects.
