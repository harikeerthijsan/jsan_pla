# Research Notes — why v3 uses synchronized views

## Delivery workflow reference

TerraScan's **View Tower Spans** workflow explicitly supports span top, span profile and section-style views and automatically updates them while traversing tower/span records. This is the strongest analogue to the Delivery team's MicroStation/TerraScan review method.

Reference:
- https://terrasolid.com/guides/tscan/toolviewtowerspans.html

## Potree capability and limitation

Potree remains suitable for browser 3D, measurements, clipping volumes and multiple point clouds. Its repository includes examples for **Elevation Profile**, **Measurements**, **Clipping Volume** and **Multiple Point Clouds**.

References:
- https://github.com/potree/potree
- https://github.com/potree/potree/blob/develop/examples/clipping_volume.html

However, there are open Potree issues reporting that the native height/elevation profile does not display points correctly when the source is COPC. Therefore v3 does not make the native Potree profile tool a critical QC dependency.

References:
- https://github.com/potree/potree/issues/1396
- https://github.com/potree/potree/issues/1553

## PDAL section strategy

PDAL's `readers.copc` supports:

- local and remote COPC files
- `bounds` spatial selection
- `resolution` to limit the pyramid levels / point resolution read

This makes it appropriate for server-generated profile samples without reading an entire LiDAR block. `writers.text` supports CSV output and explicit dimension ordering, which the worker uses as the interchange step before span-coordinate filtering.

References:
- https://pdal.io/en/2.9.0/stages/readers.copc.html
- https://pdal.io/en/2.6.3/stages/writers.text.html

## Railway object storage

Railway Storage Buckets are private S3-compatible buckets supporting presigned URLs and multipart uploads. The architecture uses direct browser-to-bucket uploads for large LAS/LAZ/COPC and presigned GET URLs for 3D COPC so large binary traffic is not proxied through the API.

References:
- https://docs.railway.com/storage-buckets
- https://docs.railway.com/storage-buckets/uploading-serving

## Vercel

The frontend is a client-side static application. Vercel supports static deployments with no build step when the framework preset is `Other`, and `vercel.json` can control static deployment behavior.

References:
- https://vercel.com/docs/builds
- https://vercel.com/docs/project-configuration/vercel-json
