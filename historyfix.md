# Consul Monitor - History Endpoint Fix

## Problem Description

The application is experiencing 404 errors when requesting service history data:
```
GET /api/service_history/nomad-client HTTP/1.1" 404 -
GET /api/service_history/traefik-ui HTTP/1.1" 404 -
```

## Root Cause Analysis

1. **Frontend-Backend Mismatch**: The frontend JavaScript is calling history endpoints that don't match the backend route definitions
2. **Service Name Encoding**: Service names with special characters (hyphens, etc.) aren't properly URL-encoded
3. **Database Query Logic**: The history query function doesn't properly handle the service grouping structure
4. **Error Handling**: Missing graceful handling of services without history data

## Solution Overview

Fix the endpoint routing, database queries, and frontend calls to properly handle service history requests by service name.

## Files to Modify

### 1. app.py - Backend History Endpoint

**Location**: Line ~95 (after the config routes)

**Add/Replace the history endpoint:**

```python
@app.route('/api/services/<service_name>/history')
def get_service_history(service_name):
    """Get historical health data for charts"""
    # Get thread-local database connection
    db_conn = get_db()
    
    # Get granularity from query params or session
    granularity = int(request.args.get('granularity', 
                     session.get('history_granularity', 15)))
    
    # Get instance address from query params (optional - for specific instance)
    instance_address = request.args.get('instance', '')
    
    try:
        # Get raw history data (24 hours)
        history = database.get_service_history(db_conn, service_name, instance_address, 24)
        
        # Aggregate data by granularity for Chart.js
        chart_data = aggregate_health_data(history, granularity)
        
        return jsonify({
            'service_name': service_name,
            'instance_address': instance_address,
            'granularity': granularity,
            'data': chart_data
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'service_name': service_name,
            'instance_address': instance_address,
            'data': []
        }), 500
```

### 2. database.py - Fix History Query Function

**Location**: Replace the existing `get_service_history` function

**Updated function:**

```python
def get_service_history(conn, service_name, instance_address='', hours=24):
    """Get service history by service name with optional instance filtering"""
    cursor = conn.cursor()
    
    if instance_address:
        # Get history for specific service instance
        cursor.execute('''
            SELECT hc.status, hc.timestamp
            FROM health_checks hc
            JOIN services s ON hc.service_id = s.id
            WHERE s.name = ? 
              AND s.address = ?
              AND hc.timestamp >= datetime('now', ?)
            ORDER BY hc.timestamp ASC
        ''', (service_name, instance_address, f'-{hours} hours'))
    else:
        # Get history for all instances of the service
        cursor.execute('''
            SELECT hc.status, hc.timestamp
            FROM health_checks hc
            JOIN services s ON hc.service_id = s.id
            WHERE s.name = ? 
              AND hc.timestamp >= datetime('now', ?)
            ORDER BY hc.timestamp ASC
        ''', (service_name, f'-{hours} hours'))
    
    return cursor.fetchall()
```

### 3. templates/index.html - Fix Frontend History Calls

**Location**: In the JavaScript `loadHistoryChart` function

**Replace the fetch call:**

```javascript
async loadHistoryChart(serviceName) {
    // Destroy existing chart if present
    if (this.charts[serviceName]) {
        this.charts[serviceName].destroy();
        delete this.charts[serviceName];
    }
    
    try {
        // Get granularity from config
        const granularity = this.config.display.historyGranularity;
        
        // FIXED: Use correct endpoint with proper URL encoding
        const response = await fetch(`/api/services/${encodeURIComponent(serviceName)}/history?granularity=${granularity}`);
        
        // Check for HTTP errors
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const historyData = await response.json();
        
        // Handle error response from API
        if (historyData.error) {
            console.warn(`No history data for ${serviceName}: ${historyData.error}`);
            return;
        }
        
        // Process data for Chart.js
        const timestamps = historyData.data.map(item => item.timestamp);
        const values = historyData.data.map(item => {
            // Calculate composite health score: 
            // passing=1.0, warning=0.5, critical=0.0
            return (item.passing + item.warning * 0.5) / 100;
        });
        
        const ctx = document.getElementById(`chart-${serviceName}`);
        if (!ctx) return;
        
        // Create and store new chart
        this.charts[serviceName] = new Chart(ctx, {
            type: 'line',
            data: {
                labels: timestamps,
                datasets: [{
                    label: 'Health Score',
                    data: values,
                    borderColor: 'rgb(75, 192, 192)',
                    tension: 0.1,
                    fill: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    y: {
                        min: 0,
                        max: 1
                    }
                }
            }
        });
    } catch (error) {
        console.error(`Error loading history for ${serviceName}:`, error);
    }
},
```

## Implementation Steps

1. **Update app.py**:
   - Ensure the history endpoint matches the pattern `/api/services/<service_name>/history`
   - Add proper error handling and response structure
   - Verify the `aggregate_health_data` function exists

2. **Update database.py**:
   - Replace the `get_service_history` function with the fixed version
   - Ensure it queries by service name, not service ID
   - Add support for optional instance filtering

3. **Update templates/index.html**:
   - Fix the fetch URL to use proper encoding with `encodeURIComponent`
   - Add error handling for missing history data
   - Ensure chart creation handles empty data gracefully

4. **Test the fix**:
   - Restart the application
   - Check browser console for JavaScript errors
   - Verify history endpoints return 200 responses
   - Confirm charts display when history data is available

## Verification Commands

**Test the endpoint directly:**
```bash
curl http://localhost:5000/api/services/nomad-client/history
curl http://localhost:5000/api/services/traefik-ui/history
```

**Check Flask logs:**
```bash
# Should see 200 responses instead of 404
docker logs consul-monitor
```

**Browser console:**
```javascript
// Should not see 404 errors for history endpoints
// Charts should appear after background poller collects data
```

## Expected Behavior After Fix

1. **History endpoints respond with 200**: `/api/services/<service_name>/history` returns JSON data
2. **Charts display**: Mini line charts appear in the History column after data collection
3. **No 404 errors**: Browser console and Flask logs show no missing endpoint errors
4. **Graceful handling**: Services without history data don't break the interface

## Notes

- History data will only be available after the background poller has run for some time
- Charts may be empty initially until health check data accumulates
- Service names with special characters are now properly URL-encoded
- The fix maintains backward compatibility with existing functionality

## Troubleshooting

**If endpoints still return 404:**
- Verify the route decorator exactly matches: `@app.route('/api/services/<service_name>/history')`
- Check that Flask is importing the updated app.py
- Restart the application completely

**If charts don't appear:**
- Check that Chart.js is loaded before the Alpine.js script
- Verify canvas elements have unique IDs
- Check browser console for JavaScript errors

**If database queries fail:**
- Ensure services table has a 'name' column
- Verify the health_checks table is populated by the background poller
- Check that services are grouped correctly in the main API response