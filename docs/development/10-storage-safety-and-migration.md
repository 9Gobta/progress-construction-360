# Storage Safety and External Drive Migration

## Current state (24 August 2026)

- Project repository: about 2.71 GB on drive D
- Docker MinIO objects: about 21.6 GB in `progress-construction_minio_data`
- Drive C free: about 33.38 GB
- Drive D free: about 9.53 GB
- New uploads are blocked when the processing drive has less than 50 GB plus
  two times the selected video size. This prevents an 8K job from filling the
  drive midway through extraction or localization.

The source video, web proxy, 360 stills and localization outputs are objects in
MinIO. Python processing workspaces are temporary and are deleted automatically
after their context exits, including failed jobs that return normally through
the worker error handler.

## Configuration prepared for a new drive

After attaching a drive, use one permanent directory for MinIO and another for
processing workspaces. Example for drive E:

```env
MINIO_DATA_PATH=E:/progress-construction-minio
STORAGE_GUARD_PATH=E:\progress-construction-minio
PROCESSING_TEMP_DIR=E:\progress-construction-temp
STORAGE_MIN_FREE_GB=50
PROCESSING_WORKSPACE_FACTOR=2.0
```

`MINIO_DATA_PATH` is consumed by `infra/compose.yaml`. The other settings are
read by the API and worker. Cloud S3-compatible storage can leave
`STORAGE_GUARD_PATH` unset, but the worker still needs a local
`PROCESSING_TEMP_DIR` with sufficient free space.

## Safe migration procedure

Do not point an empty directory at MinIO before copying the existing volume;
the application would appear to have lost its videos even though the database
still references them.

1. Stop API and worker so no object is being uploaded or generated.
2. Stop MinIO.
3. Create the destination directories on the verified external drive.
4. Copy all objects from the existing `progress-construction_minio_data` volume
   to the destination and verify object count and total bytes.
5. Set the environment values above.
6. Start MinIO and verify existing Capture proxy/keyframe URLs.
7. Start API and worker, then upload one short disposable test video.
8. Keep the old volume unchanged until the existing Captures and the test upload
   have both been verified. Removal is a separate, explicitly approved action.

## Capacity policy

For roughly 180 days at 4.7-6 GB of source video per day, raw video alone is
about 0.84-1.08 TB. Plan for 2-3 times raw size while retaining derived evidence
and a backup. Four terabytes is the minimum practical capacity; eight terabytes
provides room for other construction activities and future captures.

