# OpenMetadata Audit Log Collector

A lightweight Python-based collector for retrieving audit logs from **OpenMetadata**, storing them as structured JSON files, and forwarding them to **Elasticsearch** for centralized monitoring, analysis, and visualization in Kibana.

## Overview

OpenMetadata Audit Log Collector is designed to collect historical and newly generated audit events from the OpenMetadata REST API.

The collector periodically communicates with the OpenMetadata Audit Logs API, retrieves audit events, handles pagination, and stores the collected records in JSON files.

These files can then be processed by Filebeat and forwarded to Elasticsearch, where they can be queried and visualized through Kibana.

## Architecture

```text
             OpenMetadata Server
                      |
                      |
                Audit Logs API
                      |
                      v
          Python Audit Log Collector
                      |
             Historical Backfill
                      |
             Incremental Collection
                      |
                Pagination
                      |
                      v
              JSON Log Files
                      |
                Shared PVC
                      |
                      v
                  Filebeat
                      |
                      v
                Elasticsearch
                      |
                      v
                   Kibana
```

## Features

- **Historical Backfill:** Retrieves previously generated audit events from OpenMetadata.
- **Incremental Collection:** Periodically retrieves newly generated audit events.
- **Pagination Support:** Uses the API pagination mechanism to retrieve large volumes of audit records.
- **Duplicate Prevention:** Uses audit event IDs to avoid processing duplicate records.
- **Timestamp-Based Collection:** Uses event timestamps to manage collection windows.
- **Daily Log Files:** Stores audit records in date-based JSON files.
- **Configurable Polling Interval:** Supports periodic execution, with a target interval of 300 seconds.
- **Retention Management:** Automatically removes old log files according to the configured retention period.
- **Event Filtering:** Supports excluding selected entity types from collection.
- **Persistent Storage:** Supports Kubernetes Persistent Volume Claims (PVCs) for storing collected logs.

## Technologies

| Component | Technology |
|---|---|
| Programming Language | Python 3.11 |
| Containerization | Docker |
| Orchestration | Kubernetes |
| Source | OpenMetadata REST API |
| Log Collection | Python Collector |
| Log Forwarding | Filebeat |
| Storage and Search | Elasticsearch |
| Visualization | Kibana |
| Persistent Storage | Kubernetes PVC |

## Repository Structure

```text
OpenmetadataAuditLog/
│
├── Dockerfile
├── .gitlab-ci.yml
├── README.md
└── omd_audit_to_es.py
```

### File Description

| File | Description |
|---|---|
| `Dockerfile` | Defines the Docker image build process. |
| `.gitlab-ci.yml` | Contains GitLab CI/CD pipeline configuration. |
| `README.md` | Project documentation. |
| `omd_audit_to_es.py` | Main Python collector implementation. |

## OpenMetadata API

The collector retrieves audit records through the OpenMetadata REST API.

**API Endpoint:**

```http
GET /api/v1/audit/logs/
```

**Supported Query Parameters:**

| Parameter | Description |
|---|---|
| `startTs` | Starting timestamp in milliseconds. |
| `endTs` | Ending timestamp in milliseconds. |
| `limit` | Maximum number of records per request. |
| `after` | Pagination cursor for retrieving subsequent records. |

The API response contains audit event records and pagination information.

Example response structure:

```json
{
  "data": [
    {
      "id": 148527,
      "eventTs": 1792309740541,
      "eventType": "entityUpdated",
      "userName": "admin",
      "entityType": "user",
      "entityId": "example-id",
      "summary": "Entity updated"
    }
  ],
  "paging": {
    "after": "next-page-token"
  }
}
```

The collector uses the pagination cursor to retrieve subsequent pages.

## Audit Event Fields

Collected audit events may contain the following fields:

| Field | Description |
|---|---|
| `id` | Unique audit event identifier. |
| `changeEventId` | Change event identifier. |
| `eventTs` | Event timestamp in milliseconds. |
| `eventType` | Type of audit event. |
| `userName` | User responsible for the event. |
| `actorType` | Type of event actor. |
| `serviceName` | Name of the associated service. |
| `entityType` | Type of affected entity. |
| `entityId` | Unique entity identifier. |
| `entityFQN` | Fully qualified entity name. |
| `createdAt` | Event creation timestamp. |
| `changeEvent` | Change event details. |
| `summary` | Human-readable event description. |
| `rawEventJson` | Original raw event payload, when retained. |

## Configuration

The collector supports configuration through environment variables.

The following settings are used in the deployment configuration:

| Variable | Description | Example |
|---|---|---|
| `OMD_TOKEN` | OpenMetadata API authentication token. | Bearer token |
| `TZ_OFFSET_MIN` | Local timezone offset in minutes. | `210` |
| `RETENTION_DAYS` | Number of days to retain log files. | `30` |
| `SKIP_ENTITY_TYPES` | Entity types excluded from collection. | `ingestionPipeline,pipeline` |
| `DROP_FIELDS` | Fields excluded from output records. | `rawEventJson` |

**Additional configuration:** API URL, polling interval, pagination limits, and collection timestamps should be configured according to the implementation in `omd_audit_to_es.py`.

Never store authentication tokens or passwords directly in source code or public repository files. Use Kubernetes Secrets or another secure secret-management mechanism.

## Log Storage

The collector stores audit records in date-based JSON files.

Example:

```text
/data/
│
├── audit-2026-10-17.json
├── audit-2026-10-18.json
├── audit-2026-10-19.json
├── audit-2026-10-20.json
│
└── .audit_state.json
```

### State Management

The state file maintains collection progress, allowing the collector to continue retrieving audit events from the appropriate point.

The collector also uses an overlap window to reduce the risk of missing events around polling boundaries.

Example deployment settings:

- Polling interval: 300 seconds
- Overlap window: 600,000 milliseconds
- File retention: 30 days
- Storage location: `/data`

Duplicate event IDs are used to prevent repeated records from being written.

## Docker

### Build the Docker Image

```bash
docker build -t omd-audit-collector:1.0.0 .
```

### Verify the Image

```bash
docker images
```

### Run the Container

The container requires the OpenMetadata API configuration and authentication token.

Example:

```bash
docker run -d \
  --name omd-audit-collector \
  -e OMD_TOKEN="YOUR_TOKEN" \
  -e TZ_OFFSET_MIN=210 \
  -e RETENTION_DAYS=30 \
  -v omd-audit-data:/data \
  omd-audit-collector:1.0.0
```

Configure any additional required variables according to the Python implementation.

### View Container Logs

```bash
docker logs -f omd-audit-collector
```

## Kubernetes Deployment

The collector is designed to run as a long-running Kubernetes Deployment rather than creating a new Pod for every collection cycle.

### Deployment Components

- **Deployment:** Runs the collector continuously.
- **PersistentVolumeClaim:** Stores audit log files and collection state.
- **Secret:** Stores the OpenMetadata API token.
- **Environment Variables:** Define collector configuration.
- **Filebeat:** Reads generated JSON files and forwards them to Elasticsearch.

### Storage

The collector uses a persistent storage mount:

```yaml
volumeMounts:
  - name: audit-data
    mountPath: /data
```

The PersistentVolumeClaim should be mounted at `/data` to ensure that log files and collection state remain available across Pod restarts.

### Deployment Workflow

1. Build the Docker image.
2. Push the image to the container registry.
3. Configure the Kubernetes Secret.
4. Create or update the PersistentVolumeClaim.
5. Deploy the collector.
6. Verify the collector logs.
7. Verify generated JSON files.
8. Configure Filebeat to read the generated files.

## Filebeat Integration

Filebeat is responsible for reading the JSON audit files generated by the collector and forwarding them to Elasticsearch.

Example input configuration:

```yaml
filebeat.inputs:
  - type: filestream
    id: omd-audit-logs
    enabled: true

    paths:
      - /data/audit-*.json

    fields:
      serviceName: OMD(OpenmetadataUAT)
      logType: openmetadata_audit
      environment: uat
```

Filebeat should have access to the same persistent storage containing the collector output.

## Elasticsearch and Kibana

After Filebeat forwards the records to Elasticsearch, audit events can be searched and analyzed using Kibana.

Suggested fields for monitoring:

- `@timestamp`
- `eventType`
- `userName`
- `actorType`
- `entityType`
- `entityFQN`
- `summary`
- `environment`

### Example Monitoring Use Cases

- Tracking user login and logout events.
- Monitoring entity creation, modification, and deletion.
- Identifying users responsible for changes.
- Investigating audit events within a specific time range.
- Comparing audit activity between UAT and Production environments.

Note: The actual availability of each event type depends on the events exposed by the OpenMetadata API.

## Troubleshooting

| Problem | Recommended Check |
|---|---|
| API authentication failure | Verify the API token and permissions. |
| No audit records collected | Check API connectivity and timestamp parameters. |
| Pagination issues | Verify the `after` cursor handling. |
| Duplicate records | Check event ID deduplication and collection state. |
| Missing JSON files | Verify the `/data` mount and file permissions. |
| Filebeat not forwarding records | Check input paths and Filebeat logs. |
| Elasticsearch indexing issues | Verify Elasticsearch connectivity and indexing configuration. |
| Lost collection progress | Check whether `.audit_state.json` persists across Pod restarts. |

## Security Considerations

- Store API credentials in Kubernetes Secrets.
- Avoid committing tokens and passwords to Git.
- Restrict access to audit logs.
- Use secure communication between services where supported.
- Apply appropriate Elasticsearch access controls.
- Configure log retention according to organizational policies.

## License

Specify the applicable project license before distributing this repository.

---

**Project:** OpenMetadata Audit Log Collector  
**Language:** Python  
**Container Runtime:** Docker  
**Orchestration:** Kubernetes  
**Log Platform:** Elasticsearch / Kibana
