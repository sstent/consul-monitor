from flask import Flask, render_template, jsonify, g
import sqlite3
import json
from datetime import datetime
import database
import consul_client

app = Flask(__name__)

def get_db():
    """Get a thread-local database connection"""
    if 'db_conn' not in g:
        g.db_conn = database.init_database()
        database.create_tables(g.db_conn)
    return g.db_conn

@app.teardown_appcontext
def close_db(e=None):
    """Close database connection at end of request"""
    db_conn = g.pop('db_conn', None)
    if db_conn is not None:
        db_conn.close()

@app.route('/')
def index():
    """Render the main dashboard"""
    # Get thread-local database connection
    db_conn = get_db()
    
    # Get initial service data
    services = database.get_all_services_with_health(db_conn)
    consul_available = consul_client.is_consul_available()
    
    # Generate URLs for services
    for service in services:
        if service['port']:
            service['url'] = f"http://{service['name']}.service.dc1.consul:{service['port']}"
        else:
            service['url'] = None
            
    return render_template('index.html', services=services, consul_available=consul_available)

@app.route('/api/services')
def get_services():
    """API endpoint to get service data"""
    # Get thread-local database connection
    db_conn = get_db()
    
    try:
        # Try to get fresh data from Consul
        if consul_client.is_consul_available():
            service_data = consul_client.fetch_all_service_data()
            
            # Update database with fresh data
            for service_id, data in service_data.items():
                # Upsert service
                database.upsert_service(db_conn, {
                    'id': service_id,
                    'name': data['name'],
                    'address': data['address'],
                    'port': data['port'],
                    'tags': data['tags'],
                    'meta': data['meta']
                })
                
                # Insert health checks
                for check in data['health_checks']:
                    database.insert_health_check(db_conn, service_id, 
                                               check['check_name'], check['status'])
            
            # Retrieve services from DB with updated data
            services = database.get_all_services_with_health(db_conn)
            consul_available = True
        else:
            raise Exception("Consul unavailable")
            
    except Exception as e:
        # Fallback to cached data
        services = database.get_all_services_with_health(db_conn)
        consul_available = False
        error_message = str(e)
    
    # Generate URLs for services
    for service in services:
        if service['port']:
            service['url'] = f"http://{service['name']}.service.dc1.consul:{service['port']}"
        else:
            service['url'] = None
    
    # Prepare response
    if consul_available:
        response = {
            'status': 'success',
            'consul_available': True,
            'services': services
        }
    else:
        response = {
            'status': 'error',
            'consul_available': False,
            'services': services,
            'error': error_message
        }
    
    return jsonify(response)

@app.route('/favicon.ico')
def favicon():
    return '', 204

@app.route('/health')
def health_check():
    """Health check endpoint"""
    # Get thread-local database connection
    db_conn = get_db()
    
    db_available = database.is_database_available(db_conn)
    consul_available = consul_client.is_consul_available()
    
    status = 'healthy' if db_available and consul_available else 'unhealthy'
    
    return jsonify({
        'status': status,
        'consul': 'connected' if consul_available else 'disconnected',
        'database': 'available' if db_available else 'unavailable',
        'timestamp': datetime.utcnow().isoformat()
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
