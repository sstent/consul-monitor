# Consul Service Monitor - Design Document

## Overview

A web-based dashboard application that monitors and visualizes the health status of services registered in HashiCorp Consul. The application provides real-time monitoring with historical health tracking capabilities.

## Architecture

### High-Level Components

1. **Web Frontend** - Interactive dashboard displaying service status
2. **Backend API** - REST API for data retrieval and configuration
3. **Data Collection Service** - Background service polling Consul for health data
4. **SQLite Database** - Historical health check data storage
5. **Consul Integration** - Service discovery and health check monitoring

### Technology Stack

- **Frontend**: HTML5, CSS3, JavaScript (with Chart.js for visualizations)
- **Backend**: Python 3.9+ with Flask
- **Database**: SQLite (ephemeral storage)
- **Service Discovery**: HashiCorp Consul (consul.service.dc1.consul)
- **Updates**: Periodic polling (no WebSockets needed)

## Functional Requirements

### Core Features

#### 1. Service List Display
- Display all services registered in Consul
- Show service name, ID, and tags
- Provide clickable links to service URLs
- Support sorting and filtering

#### 2. Health Status Visualization
- **Current Status Indicator**
  - Green icon: All health checks passing
  - Red icon: One or more health checks failing
  - Yellow icon: Warning state (if supported)
- **Historical Status Chart**
  - Mini bar chart showing 24-hour health history
  - Time-based visualization (hourly aggregation)
  - Color-coded status representation

#### 3. Auto-refresh Functionality
- Toggle switch to enable/disable auto-refresh
- Configurable refresh interval (30s, 1m, 2m, 5m, 10m)
- Visual indicator when auto-refresh is active
- Manual refresh button

#### 4. Configuration Management
- Session-based storage of user preferences (no persistence needed)
- Configurable history granularity (5m, 15m, 30m, 1h) - default: 15 minutes

## Database Schema

### Tables

```sql
-- Services table
CREATE TABLE services (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT,
    port INTEGER,
    tags TEXT, -- JSON array
    meta TEXT, -- JSON object
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Health checks table
CREATE TABLE health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL,
    check_id TEXT NOT NULL,
    check_name TEXT,
    status TEXT NOT NULL, -- 'passing', 'warning', 'critical'
    output TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (service_id) REFERENCES services (id)
);

-- Configuration table (session-based, optional for defaults)
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Service URLs are generated using pattern: http://{service_name}.service.dc1.consul:{port}

-- Indexes for performance
CREATE INDEX idx_health_checks_service_timestamp ON health_checks (service_id, timestamp);
CREATE INDEX idx_health_checks_timestamp ON health_checks (timestamp);
```

## API Design

### REST Endpoints

```python
# Flask routes
GET /
- Serves main dashboard HTML page

GET /api/services
- Returns list of all services with current health status
- Generated URLs: http://{service_name}.service.dc1.consul:{port}
- Response: Array of service objects with health summary

GET /api/services/<service_id>/history
- Returns historical health data for charts
- Query params: ?granularity=15 (minutes: 5,15,30,60)
- Response: Time-series data for Chart.js

POST /api/config
- Updates session configuration
- Body: { "autoRefresh": true, "refreshInterval": 60, "historyGranularity": 15 }

GET /api/config
- Returns current session configuration
```

## Data Collection Service

### Polling Strategy

```yaml
Consul Polling:
  - Interval: 60 seconds
  - Consul Address: consul.service.dc1.consul:8500
  - Endpoints:
    - /v1/agent/services (service discovery)
    - /v1/health/service/{service} (health checks)
  - No authentication required
  - Error handling: Log errors, continue polling
  - Expected services: 30-40 services

Data Retention:
  - Keep detailed data for 24 hours only (ephemeral storage)
  - No long-term aggregation needed
  - Database recreated on container restart
```

### Health Check Processing

1. **Data Collection**
   - Poll Consul API for service list
   - For each service, fetch health check status
   - Store raw health check data with timestamps

2. **Status Aggregation**
   - Service-level status: Worst status among all checks
   - Historical aggregation: Count of passing/warning/critical per time window

3. **Change Detection**
   - Compare current status with previous poll
   - Trigger notifications/updates on status changes
   - Maintain service registration/deregistration events

## Frontend Design

### Main Dashboard Layout

```
┌─────────────────────────────────────────────────┐
│ Consul Service Monitor              [⚙️] [🔄]   │
├─────────────────────────────────────────────────┤
│ Auto-refresh: [ON/OFF] Interval: [1m ▼]           │
│ History granularity: [15m ▼]                      │
├─────────────────────────────────────────────────┤
│ Service Name    │ Status │ URL      │ History   │
├─────────────────┼────────┼──────────┼───────────┤
│ web-api         │ 🟢     │ [link]   │ ▆▆█▆█▆▆  │
│ database        │ 🔴     │ [link]   │ █▆▆▄▂▂▄  │
│ cache-service   │ 🟢     │ [link]   │ ████████  │
└─────────────────────────────────────────────────┘
```

### Interactive Elements

- **Status Icons**: Visual indicators only (no detailed popup needed)
- **History Charts**: Chart.js mini bar charts with 24-hour data
- **Service Links**: URLs generated as http://{service_name}.service.dc1.consul:{port}
- **Desktop-optimized**: No mobile responsive design required

### Updates

- Periodic AJAX polling for updates
- Configurable refresh intervals (30s, 1m, 2m, 5m, 10m)
- Visual loading indicators during refresh

## Configuration Management

### User Settings (Session-based)

```json
{
  "autoRefresh": {
    "enabled": false,
    "interval": 60,
    "options": [30, 60, 120, 300, 600]
  },
  "display": {
    "historyGranularity": 15,
    "granularityOptions": [5, 15, 30, 60]
  }
}
```

### System Configuration

```python
# Flask configuration
CONSUL_HOST = "consul.service.dc1.consul"
CONSUL_PORT = 8500
DATABASE_PATH = ":memory:"  # Ephemeral SQLite
POLL_INTERVAL = 60  # seconds
MAX_SERVICES = 50  # Safety limit
```

## Deployment Considerations

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 5000

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV CONSUL_HOST=consul.service.dc1.consul
ENV CONSUL_PORT=8500

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:5000/health || exit 1

CMD ["python", "-m", "flask", "run", "--host=0.0.0.0"]
```

### Python Dependencies (requirements.txt)

```
Flask==2.3.3
requests==2.31.0
sqlite3  # Built-in
APScheduler==3.10.4  # For background polling
```

### Environment Variables

- `CONSUL_HOST`: Consul server hostname (default: consul.service.dc1.consul)
- `CONSUL_PORT`: Consul server port (default: 8500)
- `FLASK_PORT`: Web server port (default: 5000)
- `POLL_INTERVAL`: Health check polling interval in seconds (default: 60)

### Health Checks

The application should expose its own health endpoint:
- `GET /health`: Returns application health status
- `GET /metrics`: Prometheus-style metrics (optional)

## Security Considerations

1. **Consul Access**: No authentication required for your setup
2. **Database**: Ephemeral SQLite in container memory
3. **Web Interface**: Open dashboard, no authentication needed
4. **Input Validation**: Sanitize service names and configuration inputs
5. **Container Security**: Run as non-root user in container

## Future Enhancements

- **Alerting**: Email/Slack notifications on service failures (mentioned as future feature)
- **Service Filtering**: Search and filter capabilities for larger service lists
- **Service Details**: Detailed health check information popup/modal
- **Themes**: Dark/light mode toggle
- **Export**: Export health data as CSV/JSON
- **Custom Time Ranges**: Configurable history periods beyond 24 hours

## Development Phases

### Phase 1: Core Functionality
- Basic Consul integration
- SQLite database setup
- Simple web interface
- Manual refresh capability

### Phase 2: Real-time Features
- Auto-refresh functionality
- WebSocket integration
- Historical data visualization
- Configuration persistence

### Phase 3: Enhanced UX
- Responsive design
- Advanced filtering
- Performance optimizations
- Error handling improvements

### Phase 4: Production Ready
- Docker deployment
- Security hardening
- Monitoring and logging
- Documentation and testing