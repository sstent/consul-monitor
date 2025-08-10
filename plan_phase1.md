# Phase 1 Implementation Plan - Consul Service Monitor

## Overview
Implement the core functionality for a Flask-based Consul service monitoring dashboard. This phase focuses on basic Consul integration, SQLite database setup, and a simple web interface with manual refresh capability.

## Project Structure
Create the following directory structure:
```
consul-monitor/
├── app.py                 # Main Flask application
├── consul_client.py       # Consul API integration
├── database.py           # SQLite database operations
├── requirements.txt      # Python dependencies
├── templates/
│   └── index.html        # Main dashboard template
├── static/
│   ├── css/
│   │   └── style.css     # Dashboard styles
│   └── js/
│       └── app.js        # Frontend JavaScript with Alpine.js
└── Dockerfile            # Container configuration
```

## Dependencies (requirements.txt)
```
Flask==2.3.3
requests==2.31.0
```

## Database Implementation (database.py)

### Database Schema
Implement exactly these SQLite tables:

```sql
-- Services table
CREATE TABLE IF NOT EXISTS services (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT,
    port INTEGER,
    tags TEXT,  -- Store as JSON string
    meta TEXT,  -- Store as JSON string
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Health checks table  
CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id TEXT NOT NULL,
    check_name TEXT,
    status TEXT NOT NULL,  -- 'passing', 'warning', 'critical'
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (service_id) REFERENCES services (id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_health_checks_service_timestamp 
ON health_checks (service_id, timestamp);
```

### Database Functions
Create these specific functions in database.py:

1. **`init_database()`**: Initialize SQLite database with the above schema
2. **`upsert_service(service_data)`**: Insert or update service record
   - Parameters: dictionary with id, name, address, port, tags (as JSON string), meta (as JSON string)
   - Update last_seen timestamp on existing records
3. **`insert_health_check(service_id, check_name, status)`**: Insert health check record
4. **`get_all_services_with_health()`**: Return all services with their latest health status
   - Join services table with latest health_checks record per service
   - Return list of dictionaries with service details + current health status
5. **`get_service_history(service_id, hours=24)`**: Get health history for specific service
6. **`is_database_available()`**: Test database connectivity

## Consul Client Implementation (consul_client.py)

### Configuration
Set these constants:
```python
CONSUL_HOST = "consul.service.dc1.consul"
CONSUL_PORT = 8500
CONSUL_BASE_URL = f"http://{CONSUL_HOST}:{CONSUL_PORT}"
```

### Consul Functions
Implement these specific functions:

1. **`get_consul_services()`**: 
   - Call `/v1/agent/services` endpoint
   - Return dictionary of services or raise exception on failure
   - Handle HTTP errors and connection timeouts

2. **`get_service_health(service_name)`**:
   - Call `/v1/health/service/{service_name}` endpoint
   - Parse health check results
   - Return list of health checks with check_name and status
   - Handle cases where service has no health checks

3. **`is_consul_available()`**:
   - Test connection to Consul
   - Return True/False boolean

4. **`fetch_all_service_data()`**:
   - Orchestrate calls to get_consul_services() and get_service_health()
   - Return combined service and health data
   - Handle partial failures gracefully

## Flask Application (app.py)

### Application Configuration
```python
from flask import Flask, render_template, jsonify
import sqlite3
import json
from datetime import datetime
```

### Flask Routes
Implement exactly these routes:

1. **`GET /`**: 
   - Render main dashboard using index.html template
   - Pass initial service data to template
   - Handle database/consul errors gracefully

2. **`GET /api/services`**:
   - Return JSON array of all services with current health status
   - Include generated URLs using pattern: `http://{service_name}.service.dc1.consul:{port}`
   - Response format:
   ```json
   {
     "status": "success|error", 
     "consul_available": true|false,
     "services": [
       {
         "id": "service-id",
         "name": "service-name", 
         "address": "10.0.0.1",
         "port": 8080,
         "url": "http://service-name.service.dc1.consul:8080",
         "tags": ["tag1", "tag2"],
         "current_status": "passing|warning|critical|unknown",
         "last_check": "2024-01-01T12:00:00"
       }
     ],
     "error": "error message if any"
   }
   ```

3. **`GET /health`**:
   - Return application health status
   - Test both database and Consul connectivity
   - Response format:
   ```json
   {
     "status": "healthy|unhealthy",
     "consul": "connected|disconnected", 
     "database": "available|unavailable",
     "timestamp": "2024-01-01T12:00:00"
   }
   ```

### Data Flow Logic
Implement this exact flow in the `/api/services` endpoint:

1. Try to fetch fresh data from Consul using `fetch_all_service_data()`
2. If successful:
   - Update database with new service and health data
   - Return fresh data with `consul_available: true`
3. If Consul fails:
   - Retrieve cached data from database using `get_all_services_with_health()`
   - Return cached data with `consul_available: false` and error message
4. If both fail:
   - Return error response with empty services array

## Frontend Implementation

### HTML Template (templates/index.html)
Create dashboard with this structure:
```html
<!DOCTYPE html>
<html>
<head>
    <title>Consul Service Monitor</title>
    <link rel="stylesheet" href="{{ url_for('static', filename='css/style.css') }}">
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</head>
<body x-data="serviceMonitor()">
    <div class="header">
        <h1>Consul Service Monitor</h1>
        <div class="controls">
            <button @click="refreshServices()" :disabled="loading">
                <span x-show="!loading">🔄 Refresh</span>
                <span x-show="loading">Loading...</span>
            </button>
        </div>
    </div>
    
    <div x-show="error" class="error-banner" x-text="error"></div>
    <div x-show="!consulAvailable" class="warning-banner">
        ⚠️ Consul connection failed - showing cached data
    </div>
    
    <div class="services-container">
        <table class="services-table">
            <thead>
                <tr>
                    <th>Service Name</th>
                    <th>Status</th> 
                    <th>URL</th>
                    <th>Tags</th>
                </tr>
            </thead>
            <tbody>
                <template x-for="service in services" :key="service.id">
                    <tr>
                        <td x-text="service.name"></td>
                        <td>
                            <span class="status-icon" 
                                  :class="getStatusClass(service.current_status)"
                                  x-text="getStatusEmoji(service.current_status)">
                            </span>
                        </td>
                        <td>
                            <a :href="service.url" target="_blank" x-text="service.url"></a>
                        </td>
                        <td>
                            <template x-for="tag in service.tags">
                                <span class="tag" x-text="tag"></span>
                            </template>
                        </td>
                    </tr>
                </template>
            </tbody>
        </table>
        
        <div x-show="services.length === 0 && !loading" class="no-services">
            No services found
        </div>
    </div>
</body>
</html>
```

### Alpine.js JavaScript (static/js/app.js)
```javascript
function serviceMonitor() {
    return {
        services: [],
        loading: false,
        error: null,
        consulAvailable: true,
        
        init() {
            this.refreshServices();
        },
        
        async refreshServices() {
            this.loading = true;
            this.error = null;
            
            try {
                const response = await fetch('/api/services');
                const data = await response.json();
                
                if (data.status === 'success') {
                    this.services = data.services;
                    this.consulAvailable = data.consul_available;
                } else {
                    this.error = data.error || 'Failed to fetch services';
                    this.services = data.services || [];
                    this.consulAvailable = data.consul_available;
                }
            } catch (err) {
                this.error = 'Network error: ' + err.message;
                this.services = [];
                this.consulAvailable = false;
            } finally {
                this.loading = false;
            }
        },
        
        getStatusClass(status) {
            return {
                'status-passing': status === 'passing',
                'status-warning': status === 'warning', 
                'status-critical': status === 'critical',
                'status-unknown': !status || status === 'unknown'
            };
        },
        
        getStatusEmoji(status) {
            switch(status) {
                case 'passing': return '🟢';
                case 'warning': return '🟡';
                case 'critical': return '🔴';
                default: return '⚪';
            }
        }
    }
}
```

### CSS Styling (static/css/style.css)
Implement these specific styles:
```css
/* Basic reset and layout */
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: Arial, sans-serif; background: #f5f5f5; }

/* Header */
.header {
    background: white;
    padding: 1rem 2rem;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

/* Alert banners */
.error-banner, .warning-banner {
    padding: 0.75rem 2rem;
    margin: 0;
    font-weight: bold;
}
.error-banner { background: #fee; color: #c33; }
.warning-banner { background: #fff3cd; color: #856404; }

/* Services table */
.services-container { padding: 2rem; }
.services-table {
    width: 100%;
    background: white;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    border-collapse: collapse;
}
.services-table th, .services-table td {
    padding: 1rem;
    text-align: left;
    border-bottom: 1px solid #eee;
}
.services-table th { background: #f8f9fa; font-weight: bold; }

/* Status indicators */
.status-icon { font-size: 1.2rem; }
.status-passing { color: #28a745; }
.status-warning { color: #ffc107; }
.status-critical { color: #dc3545; }
.status-unknown { color: #6c757d; }

/* Tags */
.tag {
    display: inline-block;
    background: #e9ecef;
    padding: 0.25rem 0.5rem;
    border-radius: 4px;
    font-size: 0.875rem;
    margin-right: 0.5rem;
}

/* Buttons */
button {
    background: #007bff;
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 4px;
    cursor: pointer;
}
button:hover { background: #0056b3; }
button:disabled { background: #6c757d; cursor: not-allowed; }
```

## Error Handling Requirements

### Consul Connection Errors
- Catch `requests.exceptions.ConnectionError` and `requests.exceptions.Timeout`
- Log errors but continue serving cached data
- Display connection status in UI

### Database Errors  
- Handle SQLite database lock errors
- Graceful degradation when database is unavailable
- Return appropriate HTTP status codes

### Data Validation
- Validate service data structure from Consul API
- Handle missing or malformed service records
- Default to 'unknown' status for services without health checks

## Testing Checklist
Before considering Phase 1 complete, verify:

1. **Database Operations**:
   - [ ] Database tables created correctly
   - [ ] Services can be inserted/updated
   - [ ] Health checks are stored with timestamps
   - [ ] Queries return expected data structure

2. **Consul Integration**:
   - [ ] Can fetch service list from Consul
   - [ ] Can fetch health status for each service  
   - [ ] Handles Consul connection failures gracefully
   - [ ] Service URLs generated correctly

3. **Web Interface**:
   - [ ] Dashboard loads without errors
   - [ ] Services displayed in table format
   - [ ] Status icons show correct colors
   - [ ] Refresh button updates data via AJAX
   - [ ] Error messages display when appropriate

4. **Error Scenarios**:
   - [ ] App starts when Consul is unavailable
   - [ ] Shows cached data when Consul fails
   - [ ] Displays appropriate error messages
   - [ ] Recovers when Consul comes back online

## Docker Configuration (Dockerfile)
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 5000

# Environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:5000/health', timeout=5)" || exit 1

CMD ["python", "-m", "flask", "run", "--host=0.0.0.0"]
```

## Implementation Order
Follow this exact sequence:

1. Create project structure and requirements.txt
2. Implement database.py with all functions and test database operations
3. Implement consul_client.py and test Consul connectivity
4. Create basic Flask app.py with health endpoint
5. Add /api/services endpoint with full error handling
6. Create HTML template with Alpine.js integration
7. Add CSS styling for professional appearance
8. Test complete workflow: Consul → Database → API → Frontend
9. Create Dockerfile and test containerized deployment
10. Verify all error scenarios work as expected

## Success Criteria
Phase 1 is complete when:
- Application starts successfully in Docker container
- Dashboard displays list of services from Consul
- Manual refresh button updates service data
- Application gracefully handles Consul outages
- All services show correct health status with colored indicators
- Generated service URLs follow the specified pattern
- Error messages display appropriately in the UI