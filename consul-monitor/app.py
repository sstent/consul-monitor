from flask import Flask, render_template, jsonify, g, session, request
import sqlite3
import json
from datetime import datetime, timedelta
import database
import consul_client
import background_poller

app = Flask(__name__)
app.secret_key = 'consul-monitor-secret-key-change-in-production'

def get_db():
    """Get a thread-local database connection"""
    if 'db_conn' not in g:
        g.db_conn = database.init_database()
    return g.db_conn

@app.teardown_appcontext
def close_db(e=None):
    """Close database connection at end of request"""
    db_conn = g.pop('db_conn', None)
    if db_conn is not None:
        db_conn.close()

# Initialize background services on first request
first_request = True

@app.before_request
def initialize_background_services():
    global first_request
    if first_request:
        background_poller.start_background_polling()
        first_request = False

# Cleanup when app shuts down
@app.teardown_appcontext
def cleanup_background_services(e=None):
    pass  # Cleanup handled by atexit in poller

@app.route('/')
def index():
    """Render the main dashboard"""
    # Get thread-local database connection
    db_conn = get_db()
    
    try:
        # Get services grouped by name
        services = database.get_all_services_grouped(db_conn)
        consul_available = consul_client.is_consul_available()
        
        # Generate URLs for each instance in each service
        for service in services:
            # Create a set of unique ports for this service
            unique_ports = set()
            for instance in service['instances']:
                if instance['port']:
                    unique_ports.add(instance['port'])
            
            # Create port-based URLs
            service['port_urls'] = [
                f"http://{service['name']}.service.dc1.consul:{port}"
                for port in unique_ports
            ]
            
            # Keep instance URLs for other display purposes
            for instance in service['instances']:
                if instance['port']:
                    instance['url'] = f"http://{service['name']}.service.dc1.consul:{instance['port']}"
                else:
                    instance['url'] = None
                    
        return render_template('index.html', services=services, consul_available=consul_available)
    except Exception as e:
        # Fallback in case of errors
        return render_template('index.html', services=[], consul_available=False, error=str(e))

@app.route('/api/services')
def get_services():
    """API endpoint to get service data"""
    # Get thread-local database connection
    db_conn = get_db()
    
    try:
        # Get services grouped by name
        services = database.get_all_services_grouped(db_conn)
        consul_available = consul_client.is_consul_available()
        
        # Generate URLs for each instance in each service
        # Generate URLs for each service and its instances
        for service in services:
            # Create a set of unique ports for port-based URLs
            unique_ports = set()
            for instance in service['instances']:
                if instance['port']:
                    unique_ports.add(instance['port'])
                    instance['url'] = f"http://{service['name']}.service.dc1.consul:{instance['port']}"
                else:
                    instance['url'] = None
            
            # Add port-based URLs to service object
            service['port_urls'] = [
                f"http://{service['name']}.service.dc1.consul:{port}"
                for port in unique_ports
            ]
        
        response = {
            'status': 'success',
            'consul_available': consul_available,
            'services': services
        }
        
    except Exception as e:
        response = {
            'status': 'error',
            'consul_available': False,
            'services': [],
            'error': str(e)
        }
    
    return jsonify(response)

@app.route('/favicon.ico')
def favicon():
    return '', 204

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

@app.route('/api/services/<service_name>/history')
def get_service_history(service_name):
    """Get historical health data for charts"""
    # Get thread-local database connection
    db_conn = get_db()
    
    # Get granularity from query params or session
    granularity = int(request.args.get('granularity', 
                     session.get('history_granularity', 15)))
    
    # Get instance address from query params
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

def aggregate_health_data(raw_history, granularity_minutes):
    """Aggregate raw health data into time windows for charts"""
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
    window_checks = {slot: [] for slot in time_slots}
    
    for status, timestamp_str in raw_history:
        try:
            # Parse timestamp (adjust format as needed)
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            # Find the correct time window
            for slot in time_slots:
                if slot <= timestamp < slot + window_size:
                    window_checks[slot].append(status)
                    break
        except ValueError:
            continue
    
    # Calculate percentage of time in each status per window
    for slot in time_slots:
        checks = window_checks[slot]
        if checks:
            passing_count = sum(1 for s in checks if s == 'passing')
            warning_count = sum(1 for s in checks if s == 'warning')
            critical_count = sum(1 for s in checks if s == 'critical')
            total = len(checks)
            
            passing_pct = round((passing_count / total) * 100, 1)
            warning_pct = round((warning_count / total) * 100, 1)
            critical_pct = round((critical_count / total) * 100, 1)
        else:
            passing_pct = warning_pct = critical_pct = 0
        
        chart_data.append({
            'timestamp': slot.isoformat(),
            'passing': passing_pct,
            'warning': warning_pct, 
            'critical': critical_pct
        })
    
    return chart_data

@app.route('/api/debug/db')
def debug_db():
    """Debug endpoint to inspect database contents"""
    db_conn = get_db()
    cursor = db_conn.cursor()
    
    # Get services
    cursor.execute("SELECT * FROM services")
    services = cursor.fetchall()
    services = [dict(id=row[0], name=row[1], address=row[2], port=row[3], 
                    tags=json.loads(row[4]), meta=json.loads(row[5]),
                    first_seen=row[6], last_seen=row[7]) for row in services]
    
    # Get health checks
    cursor.execute("SELECT * FROM health_checks")
    health_checks = cursor.fetchall()
    health_checks = [dict(id=row[0], service_id=row[1], check_name=row[2],
                         status=row[3], timestamp=row[4]) for row in health_checks]
    
    return jsonify({
        'services': services,
        'health_checks': health_checks
    })

@app.route('/health')
def health_check():
    """Health check endpoint"""
    # Get thread-local database connection
    db_conn = get_db()
    
    db_available = database.is_database_available(db_conn)
    consul_available = consul_client.is_consul_available()
    polling_active = background_poller.poller is not None and background_poller.poller.running
    
    status = 'healthy' if db_available and consul_available and polling_active else 'unhealthy'
    
    return jsonify({
        'status': status,
        'consul': 'connected' if consul_available else 'disconnected',
        'database': 'available' if db_available else 'unavailable',
        'polling': 'active' if polling_active else 'inactive',
        'timestamp': datetime.utcnow().isoformat()
    })

# Log 404 errors
@app.after_request
def log_404(response):
    if response.status_code == 404:
        app.logger.warning(f"404 for {request.path} from {request.remote_addr}")
    return response

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
