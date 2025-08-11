# Phase 2 Implementation Plan - Background Polling & Auto-refresh

## Overview
Implement background Consul polling using APScheduler, add auto-refresh functionality with configurable intervals, integrate Chart.js for historical health visualization, and add session-based configuration persistence.

## Current Phase 1 Foundation
✅ **Existing Components Ready for Extension:**
- Flask app with proper database integration
- Consul client with comprehensive error handling  
- Alpine.js frontend with manual refresh
- SQLite database with health_checks table
- Service URL generation and status display

## New Dependencies Required

### Update requirements.txt
```
Flask==2.3.3
requests==2.31.0
APScheduler==3.10.4
```

## Phase 2 Implementation Tasks

### Task 1: Background Consul Polling Service

#### File: `background_poller.py` (NEW FILE)
Create a dedicated background service for Consul polling:

```python
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
import logging
import threading
import consul_client
import database
import sqlite3
import atexit

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ConsulPoller:
    def __init__(self, database_connection_factory):
        self.scheduler = BackgroundScheduler(
            executors={'default': ThreadPoolExecutor(1)},
            job_defaults={'coalesce': True, 'max_instances': 1}
        )
        self.get_db_conn = database_connection_factory
        self.running = False
        
    def start(self):
        """Start the background polling"""
        if not self.running:
            logger.info("Starting Consul background polling...")
            
            # Initial poll on startup
            self.poll_consul()
            
            # Schedule recurring polls every 60 seconds
            self.scheduler.add_job(
                func=self.poll_consul,
                trigger="interval", 
                seconds=60,
                id='consul_poll',
                name='Poll Consul for service health'
            )
            
            self.scheduler.start()
            self.running = True
            logger.info("Background polling started")
            
            # Ensure cleanup on exit
            atexit.register(lambda: self.stop())
    
    def stop(self):
        """Stop the background polling"""
        if self.running:
            logger.info("Stopping Consul background polling...")
            self.scheduler.shutdown(wait=False)
            self.running = False
            logger.info("Background polling stopped")
    
    def poll_consul(self):
        """Poll Consul and update database - runs every minute"""
        try:
            logger.info("Polling Consul for service data...")
            
            if not consul_client.is_consul_available():
                logger.warning("Consul unavailable during background poll")
                return
            
            # Get fresh data from Consul
            service_data = consul_client.fetch_all_service_data()
            
            if not service_data:
                logger.warning("No service data received from Consul")
                return
            
            # Get database connection
            conn = self.get_db_conn()
            
            # Update database with fresh data
            services_updated = 0
            health_checks_inserted = 0
            
            for service_id, data in service_data.items():
                # Upsert service
                database.upsert_service(conn, {
                    'id': service_id,
                    'name': data['name'],
                    'address': data['address'],
                    'port': data['port'],
                    'tags': data['tags'],
                    'meta': data['meta']
                })
                services_updated += 1
                
                # Insert health checks - raw data points every minute
                for check in data['health_checks']:
                    database.insert_health_check(
                        conn, service_id, 
                        check['check_name'], 
                        check['status']
                    )
                    health_checks_inserted += 1
            
            conn.close()
            
            logger.info(f"Poll complete: {services_updated} services updated, "
                       f"{health_checks_inserted} health checks recorded")
                
        except Exception as e:
            logger.error(f"Error during Consul polling: {e}")

# Global poller instance
poller = None

def get_database_connection():
    """Factory function for database connections in background thread"""
    return database.init_database()

def start_background_polling():
    """Start the background polling service"""
    global poller
    if poller is None:
        poller = ConsulPoller(get_database_connection)
        poller.start()
    return poller

def stop_background_polling():
    """Stop the background polling service"""
    global poller
    if poller:
        poller.stop()
        poller = None
```

#### Update `app.py`: Integrate Background Polling

**Add these imports at the top:**
```python
import background_poller
from flask import session
```

**Add after the Flask app creation:**
```python
# Start background polling when app starts
@app.before_first_request
def initialize_background_services():
    background_poller.start_background_polling()

# Cleanup when app shuts down
@app.teardown_appcontext
def cleanup_background_services(e=None):
    pass  # Cleanup handled by atexit in poller
```

### Task 2: Session-based Configuration Management

#### Add Configuration Routes to `app.py`

**Add these new routes:**
```python
@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current session configuration"""
    config = {
        'autoRefresh': {
            'enabled': session.get('auto_refresh_enabled', False),
            'interval': session.get('auto_refresh_interval', 60),
            'options': [30, 60, 120, 300, 600]
        },
        'display': {
            'historyGranularity': session.get('history_granularity', 15),
            'granularityOptions': [5, 15, 30, 60]
        }
    }
    return jsonify(config)

@app.route('/api/config', methods=['POST'])
def update_config():
    """Update session configuration"""
    data = request.get_json()
    
    if 'autoRefresh' in data:
        auto_refresh = data['autoRefresh']
        if 'enabled' in auto_refresh:
            session['auto_refresh_enabled'] = bool(auto_refresh['enabled'])
        if 'interval' in auto_refresh:
            interval = int(auto_refresh['interval'])
            if interval in [30, 60, 120, 300, 600]:  # Validate interval
                session['auto_refresh_interval'] = interval
    
    if 'display' in data:
        display = data['display']
        if 'historyGranularity' in display:
            granularity = int(display['historyGranularity'])
            if granularity in [5, 15, 30, 60]:  # Validate granularity
                session['history_granularity'] = granularity
    
    session.permanent = True
    return jsonify({'status': 'success'})

# Add secret key for sessions
app.secret_key = 'consul-monitor-secret-key-change-in-production'
```

**Add import for request:**
```python
from flask import Flask, render_template, jsonify, g, session, request
```

### Task 3: Historical Data API Endpoint

#### Add History Endpoint to `app.py`

```python
@app.route('/api/services/<service_id>/history')
def get_service_history(service_id):
    """Get historical health data for charts"""
    # Get thread-local database connection
    db_conn = get_db()
    
    # Get granularity from query params or session
    granularity = int(request.args.get('granularity', 
                     session.get('history_granularity', 15)))
    
    try:
        # Get raw history data (24 hours)
        history = database.get_service_history(db_conn, service_id, 24)
        
        # Aggregate data by granularity for Chart.js
        chart_data = aggregate_health_data(history, granularity)
        
        return jsonify({
            'service_id': service_id,
            'granularity': granularity,
            'data': chart_data
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'service_id': service_id,
            'data': []
        }), 500

def aggregate_health_data(raw_history, granularity_minutes):
    """Aggregate raw health data into time windows for charts"""
    from datetime import datetime, timedelta
    import collections
    
    if not raw_history:
        return []
    
    # Create time windows for the last 24 hours
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(hours=24)
    window_size = timedelta(minutes=granularity_minutes)
    
    # Generate time slots
    time_slots = []
    current_time = start_time
    while current_time < end_time:
        time_slots.append(current_time)
        current_time += window_size
    
    # Group health checks by time windows
    chart_data = []
    
    for slot_start in time_slots:
        slot_end = slot_start + window_size
        
        # Find health checks in this time window
        window_checks = []
        for status, timestamp_str in raw_history:
            try:
                # Parse timestamp (adjust format as needed)
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                if slot_start <= timestamp < slot_end:
                    window_checks.append(status)
            except ValueError:
                continue
        
        # Calculate percentage of time in each status
        if window_checks:
            status_counts = collections.Counter(window_checks)
            total = len(window_checks)
            
            passing_pct = round((status_counts.get('passing', 0) / total) * 100, 1)
            warning_pct = round((status_counts.get('warning', 0) / total) * 100, 1) 
            critical_pct = round((status_counts.get('critical', 0) / total) * 100, 1)
        else:
            # No data for this time window
            passing_pct = warning_pct = critical_pct = 0
        
        chart_data.append({
            'timestamp': slot_start.isoformat(),
            'passing': passing_pct,
            'warning': warning_pct, 
            'critical': critical_pct
        })
    
    return chart_data
```

### Task 4: Enhanced Frontend with Auto-refresh and Charts

#### Update `templates/index.html`: Add Configuration Panel and History Column

**Replace the controls section:**
```html
<div class="controls">
    <!-- Auto-refresh controls -->
    <div class="control-group">
        <label class="toggle">
            <input type="checkbox" x-model="config.autoRefresh.enabled" 
                   @change="updateConfig()">
            <span class="toggle-slider"></span>
            Auto-refresh
        </label>
        <select x-model="config.autoRefresh.interval" @change="updateConfig()"
                :disabled="!config.autoRefresh.enabled">
            <template x-for="option in config.autoRefresh.options" :key="option">
                <option :value="option" x-text="formatInterval(option)"></option>
            </template>
        </select>
    </div>
    
    <!-- History granularity -->
    <div class="control-group">
        <label>History:</label>
        <select x-model="config.display.historyGranularity" @change="updateConfig()">
            <template x-for="option in config.display.granularityOptions" :key="option">
                <option :value="option" x-text="option + 'm'"></option>
            </template>
        </select>
    </div>
    
    <!-- Manual refresh -->
    <button @click="refreshServices" :disabled="loading">
        <span x-show="!loading">🔄 Refresh</span>
        <span x-show="loading">Loading...</span>
    </button>
</div>
```

**Update the table to include History column:**
```html
<table class="services-table">
    <thead>
        <tr>
            <th>Service Name</th>
            <th>Status</th> 
            <th>URL</th>
            <th>Tags</th>
            <th>24h History</th>
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
                <td>
                    <div class="chart-container">
                        <canvas :id="'chart-' + service.id" 
                                width="200" height="50"></canvas>
                    </div>
                </td>
            </tr>
        </template>
    </tbody>
</table>
```

#### Update Alpine.js Component: Add Auto-refresh and Chart Logic

**Replace the Alpine.js script section in `index.html`:**
```html
<script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
    document.addEventListener('alpine:init', () => {
        Alpine.data('serviceMonitor', () => ({
            services: [],
            loading: false,
            error: null,
            consulAvailable: true,
            config: {
                autoRefresh: {
                    enabled: false,
                    interval: 60,
                    options: [30, 60, 120, 300, 600]
                },
                display: {
                    historyGranularity: 15,
                    granularityOptions: [5, 15, 30, 60]
                }
            },
            autoRefreshTimer: null,
            charts: {},
            
            async init() {
                await this.loadConfig();
                await this.refreshServices();
                this.startAutoRefresh();
            },
            
            async loadConfig() {
                try {
                    const response = await fetch('/api/config');
                    const data = await response.json();
                    this.config = data;
                } catch (err) {
                    console.error('Failed to load config:', err);
                }
            },
            
            async updateConfig() {
                try {
                    await fetch('/api/config', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(this.config)
                    });
                    
                    // Restart auto-refresh with new interval
                    this.startAutoRefresh();
                    
                    // Refresh charts if granularity changed
                    this.loadHistoryCharts();
                    
                } catch (err) {
                    console.error('Failed to update config:', err);
                }
            },
            
            startAutoRefresh() {
                // Clear existing timer
                if (this.autoRefreshTimer) {
                    clearInterval(this.autoRefreshTimer);
                    this.autoRefreshTimer = null;
                }
                
                // Start new timer if enabled
                if (this.config.autoRefresh.enabled) {
                    this.autoRefreshTimer = setInterval(
                        () => this.refreshServices(),
                        this.config.autoRefresh.interval * 1000
                    );
                }
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
                        
                        // Load history charts after services update
                        this.$nextTick(() => this.loadHistoryCharts());
                        
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
            
            async loadHistoryCharts() {
                for (const service of this.services) {
                    await this.createChart(service.id);
                }
            },
            
            async createChart(serviceId) {
                try {
                    const response = await fetch(`/api/services/${serviceId}/history?granularity=${this.config.display.historyGranularity}`);
                    const data = await response.json();
                    
                    const canvas = document.getElementById(`chart-${serviceId}`);
                    if (!canvas) return;
                    
                    // Destroy existing chart
                    if (this.charts[serviceId]) {
                        this.charts[serviceId].destroy();
                    }
                    
                    const ctx = canvas.getContext('2d');
                    
                    this.charts[serviceId] = new Chart(ctx, {
                        type: 'bar',
                        data: {
                            labels: data.data.map(d => new Date(d.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})),
                            datasets: [
                                {
                                    label: 'Passing',
                                    data: data.data.map(d => d.passing),
                                    backgroundColor: '#28a745',
                                    stack: 'health'
                                },
                                {
                                    label: 'Warning', 
                                    data: data.data.map(d => d.warning),
                                    backgroundColor: '#ffc107',
                                    stack: 'health'
                                },
                                {
                                    label: 'Critical',
                                    data: data.data.map(d => d.critical),
                                    backgroundColor: '#dc3545',
                                    stack: 'health'
                                }
                            ]
                        },
                        options: {
                            responsive: false,
                            maintainAspectRatio: false,
                            plugins: {
                                legend: { display: false },
                                tooltip: {
                                    callbacks: {
                                        title: function(context) {
                                            return new Date(data.data[context[0].dataIndex].timestamp).toLocaleString();
                                        },
                                        label: function(context) {
                                            return context.dataset.label + ': ' + context.parsed.y + '%';
                                        }
                                    }
                                }
                            },
                            scales: {
                                x: { display: false },
                                y: { 
                                    display: false,
                                    max: 100,
                                    stacked: true
                                }
                            }
                        }
                    });
                } catch (err) {
                    console.error(`Failed to load chart for service ${serviceId}:`, err);
                }
            },
            
            formatInterval(seconds) {
                if (seconds < 60) return `${seconds}s`;
                return `${seconds / 60}m`;
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
        }));
    });
</script>
```

### Task 5: Enhanced CSS Styling

#### Update `static/css/style.css`: Add New Styles

**Add these new styles:**
```css
/* Control groups */
.controls {
    display: flex;
    gap: 2rem;
    align-items: center;
    flex-wrap: wrap;
}

.control-group {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

/* Toggle switch styling */
.toggle {
    position: relative;
    display: inline-flex;
    align-items: center;
    cursor: pointer;
    gap: 0.5rem;
}

.toggle input[type="checkbox"] {
    display: none;
}

.toggle-slider {
    position: relative;
    width: 44px;
    height: 24px;
    background-color: #ccc;
    border-radius: 24px;
    transition: background-color 0.2s;
}

.toggle-slider:before {
    content: "";
    position: absolute;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background-color: white;
    top: 2px;
    left: 2px;
    transition: transform 0.2s;
}

.toggle input:checked + .toggle-slider {
    background-color: #007bff;
}

.toggle input:checked + .toggle-slider:before {
    transform: translateX(20px);
}

/* Select styling */
select {
    padding: 0.5rem;
    border: 1px solid #ddd;
    border-radius: 4px;
    background: white;
    font-size: 1rem;
}

select:disabled {
    background: #f5f5f5;
    color: #999;
    cursor: not-allowed;
}

/* Chart containers */
.chart-container {
    width: 200px;
    height: 50px;
    position: relative;
}

.chart-container canvas {
    width: 100% !important;
    height: 100% !important;
}

/* Table adjustments for history column */
.services-table th:last-child,
.services-table td:last-child {
    width: 220px;
    text-align: center;
}
```

### Task 6: Database Enhancement

#### Update `database.py`: Add Better History Query

**Add this improved function:**
```python
def get_service_history_detailed(conn, service_id, hours=24):
    """Get detailed service history with proper timestamp handling"""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT status, timestamp
        FROM health_checks
        WHERE service_id = ? 
          AND timestamp >= datetime('now', ?)
        ORDER BY timestamp ASC
    ''', (service_id, f'-{hours} hours'))
    
    results = cursor.fetchall()
    return [(status, timestamp) for status, timestamp in results]
```

## Task 7: Update Requirements and Dockerfile

#### Update `requirements.txt`
```
Flask==2.3.3
requests==2.31.0
APScheduler==3.10.4
```

#### No Dockerfile changes needed
The existing Dockerfile will work with the new requirements.

## Implementation Order

**Follow this exact sequence:**

1. **Update dependencies** (5 minutes)
   - Update requirements.txt
   - Install APScheduler: `pip install APScheduler==3.10.4`

2. **Implement background polling** (30 minutes)
   - Create `background_poller.py`
   - Test background service independently
   - Verify database gets updated every minute

3. **Add configuration management** (20 minutes)
   - Add config routes to `app.py`
   - Add session support and secret key
   - Test config persistence across page reloads

4. **Implement history API** (25 minutes)
   - Add history endpoint to `app.py` 
   - Add aggregation function
   - Test with sample data

5. **Update frontend** (45 minutes)
   - Update HTML template with controls and history column
   - Update Alpine.js component with auto-refresh logic
   - Add Chart.js integration for mini bar charts

6. **Add CSS styling** (15 minutes)
   - Add toggle switch styles
   - Add chart container styles
   - Test responsive layout

7. **Integration and testing** (30 minutes)
   - Start background polling service
   - Test auto-refresh functionality
   - Verify charts display correctly
   - Test configuration persistence

## Success Criteria

Phase 2 is complete when:

### Background Polling ✅
- [ ] APScheduler polls Consul every 60 seconds
- [ ] Health data is stored as raw data points
- [ ] Background service handles errors gracefully
- [ ] Database accumulates history over time

### Auto-refresh Functionality ✅  
- [ ] Toggle switch enables/disables auto-refresh
- [ ] Refresh interval is configurable (30s, 1m, 2m, 5m, 10m)
- [ ] Auto-refresh timer restarts when interval changes
- [ ] Manual refresh button works independently

### Configuration Persistence ✅
- [ ] Settings persist across browser sessions
- [ ] Configuration API endpoints work correctly
- [ ] Invalid config values are rejected
- [ ] Default values load on first visit

### Historical Visualization ✅
- [ ] Mini bar charts display 24-hour history
- [ ] Charts show percentage time in each status
- [ ] Granularity is configurable (5m, 15m, 30m, 1h)
- [ ] Charts update when auto-refresh runs
- [ ] Hover tooltips show exact timestamps and percentages

### Integration ✅
- [ ] All Phase 1 functionality continues to work
- [ ] Background polling doesn't interfere with API requests
- [ ] Charts load correctly for all services
- [ ] Error states are handled gracefully
- [ ] Performance is acceptable with 30-40 services

## Testing Checklist

### Functional Testing
- [ ] Background service starts automatically with Flask app
- [ ] Consul data is polled and stored every minute
- [ ] Auto-refresh toggles work correctly
- [ ] Interval changes take effect immediately
- [ ] History granularity changes update charts
- [ ] Charts display meaningful data
- [ ] Configuration persists across page reloads

### Error Scenarios
- [ ] App handles Consul downtime during background polling
- [ ] Charts handle services with no history data
- [ ] Invalid configuration values are rejected
- [ ] Background service recovers from database errors

### Performance Testing
- [ ] Background polling completes within reasonable time
- [ ] Charts render efficiently for all services
- [ ] Auto-refresh doesn't cause memory leaks
- [ ] Database queries perform well with growing data

## Estimated Implementation Time
**Total: 3-4 hours for complete Phase 2 implementation**

Individual components can be implemented and tested incrementally, with the background polling service being the foundation for all other features.