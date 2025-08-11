import sqlite3
import json
from datetime import datetime

def create_tables(conn):
    cursor = conn.cursor()
    # Create instances table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS instances (
            address TEXT PRIMARY KEY,
            health_status TEXT NOT NULL DEFAULT 'unknown',
            first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create services table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS services (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            address TEXT REFERENCES instances(address) ON DELETE CASCADE,
            port INTEGER,
            tags TEXT,
            meta TEXT,
            first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create health checks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS health_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id TEXT NOT NULL,
            check_name TEXT,
            status TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (service_id) REFERENCES services (id)
        )
    ''')
    
    # Create instance health table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS instance_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            address TEXT NOT NULL REFERENCES instances(address) ON DELETE CASCADE,
            health_status TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create indexes
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_health_checks_service_timestamp 
        ON health_checks (service_id, timestamp)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_health_checks_timestamp 
        ON health_checks (timestamp)
    ''')
    
    conn.commit()
    conn.commit()

def init_database():
    """Initialize database, create tables, and return connection"""
    conn = sqlite3.connect('/data/consul-monitor.db')
    create_tables(conn)
    return conn

def upsert_instance(conn, address, health_status):
    """Insert or update an instance record"""
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO instances (address, health_status, last_seen)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(address) DO UPDATE SET
            health_status = excluded.health_status,
            last_seen = excluded.last_seen
    ''', (address, health_status))
    conn.commit()

def upsert_service(conn, service_data, instance_address):
    """Insert or update a service record with instance reference"""
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO services (id, name, address, port, tags, meta)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            address = excluded.address,
            port = excluded.port,
            tags = excluded.tags,
            meta = excluded.meta,
            last_seen = CURRENT_TIMESTAMP
    ''', (
        service_data['id'],
        service_data['name'],
        instance_address,
        service_data.get('port'),
        json.dumps(service_data.get('tags', [])),
        json.dumps(service_data.get('meta', {}))
    ))
    conn.commit()

def insert_instance_health(conn, address, health_status):
    """Insert an instance health record"""
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO instance_health (address, health_status)
        VALUES (?, ?)
    ''', (address, health_status))
    conn.commit()

def insert_health_check(conn, service_id, check_name, status):
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO health_checks (service_id, check_name, status)
        VALUES (?, ?, ?)
    ''', (service_id, check_name, status))
    conn.commit()

def get_all_services_grouped(conn):
    """Get all services grouped by name with composite health status"""
    cursor = conn.cursor()
    cursor.execute('''
        WITH latest_health AS (
            SELECT 
                service_id, 
                status,
                MAX(timestamp) as last_check
            FROM health_checks
            GROUP BY service_id
        )
        SELECT 
            s.name, 
            json_group_array(json_object(
                'address', s.address,
                'port', s.port,
                'id', s.id,
                'tags', s.tags,
                'meta', s.meta,
                'current_status', lh.status,
                'last_check', lh.last_check
            )) AS instances,
            MIN(CASE 
                WHEN lh.status = 'critical' THEN 1
                WHEN lh.status = 'warning' THEN 2
                WHEN lh.status = 'passing' THEN 3
                ELSE 4 END) as composite_status_order
        FROM services s
        LEFT JOIN latest_health lh ON s.id = lh.service_id
        GROUP BY s.name
        ORDER BY s.name
    ''')
    
    services = []
    for row in cursor.fetchall():
        service = {
            'name': row[0],
            'instances': json.loads(row[1]) if row[1] else [],
            'composite_status': 'passing'  # Default
        }
        
        # Determine composite status based on worst status
        if any(inst.get('current_status') == 'critical' for inst in service['instances']):
            service['composite_status'] = 'critical'
        elif any(inst.get('current_status') == 'warning' for inst in service['instances']):
            service['composite_status'] = 'warning'
        elif all(inst.get('current_status') == 'passing' for inst in service['instances']):
            service['composite_status'] = 'passing'
        else:
            service['composite_status'] = 'unknown'
            
        services.append(service)
    return services

def get_service_history(conn, service_name, instance_address, hours=24):
    cursor = conn.cursor()
    cursor.execute('''
        SELECT hc.status, hc.timestamp
        FROM health_checks hc
        JOIN services s ON hc.service_id = s.id
        WHERE s.name = ? 
          AND s.address = ?
          AND hc.timestamp >= datetime('now', ?)
        ORDER BY hc.timestamp ASC
    ''', (service_name, instance_address, f'-{hours} hours'))
    return cursor.fetchall()

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

def is_database_available(conn):
    try:
        conn.execute('SELECT 1')
        return True
    except sqlite3.Error:
        return False

# Keep the old function for now but we'll remove it later
def get_all_instances_with_services(conn):
    """Get all instances with their services and health status"""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT i.address, i.health_status, 
               s.id, s.name, s.port, s.tags, s.meta,
               h.status, MAX(h.timestamp) AS last_check
        FROM instances i
        LEFT JOIN services s ON i.address = s.address
        LEFT JOIN health_checks h ON s.id = h.service_id
        GROUP BY i.address, s.id
    ''')
    
    instances = {}
    for row in cursor.fetchall():
        address = row[0]
        if address not in instances:
            instances[address] = {
                'address': address,
                'health_status': row[1],
                'services': []
            }
        
        # Only add service if it exists
        if row[2]:  # service id
            service = {
                'id': row[2],
                'name': row[3],
                'port': row[4],
                'tags': json.loads(row[5]) if row[5] else [],
                'meta': json.loads(row[6]) if row[6] else {},
                'current_status': row[7] or 'unknown',
                'last_check': row[8]
            }
            instances[address]['services'].append(service)
    
    return list(instances.values())
