import requests
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Consul configuration
CONSUL_HOST = "consul.service.dc1.consul"
CONSUL_PORT = 8500
CONSUL_BASE_URL = f"http://{CONSUL_HOST}:{CONSUL_PORT}"

def get_consul_services():
    """Fetch all registered services from Consul"""
    url = f"{CONSUL_BASE_URL}/v1/agent/services"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Consul services: {e}")
        raise

def get_service_health(service_name):
    """Fetch health checks for a specific service"""
    url = f"{CONSUL_BASE_URL}/v1/health/service/{service_name}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        # Process health checks
        health_checks = []
        for entry in data:
            for check in entry.get('Checks', []):
                health_checks.append({
                    'check_name': check.get('Name', ''),
                    'status': check.get('Status', '')
                })
        return health_checks
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch health for service {service_name}: {e}")
        raise

def is_consul_available():
    """Check if Consul is reachable"""
    try:
        response = requests.get(f"{CONSUL_BASE_URL}/v1/agent/self", timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def calculate_composite_health(services):
    """Calculate overall health status for a group of services"""
    status_priority = {'critical': 3, 'warning': 2, 'passing': 1}
    worst_status = 'passing'
    
    for service in services:
        for check in service['health_checks']:
            if status_priority[check['status']] > status_priority[worst_status]:
                worst_status = check['status']
    return worst_status

def group_services_by_instance(services):
    """Group services by their instance address"""
    instances = {}
    for service in services.values():
        address = service['address']
        if address not in instances:
            instances[address] = {
                'address': address,
                'services': [],
                'health_status': 'passing'
            }
        instances[address]['services'].append(service)
    
    # Calculate composite health for each instance
    for instance in instances.values():
        instance['health_status'] = calculate_composite_health(instance['services'])
    
    return instances

def fetch_all_service_data():
    """Fetch service data and health status for all services, grouped by instance"""
    try:
        services = get_consul_services()
        service_data = {}
        
        for service_id, service_info in services.items():
            service_name = service_info.get('Service', '')
            health_checks = []
            
            try:
                health_checks = get_service_health(service_name)
            except requests.exceptions.RequestException:
                # Log but continue with other services
                logger.warning(f"Skipping health checks for service {service_name}")
            
            service_data[service_id] = {
                'id': service_id,
                'name': service_info.get('Service', ''),
                'address': service_info.get('Address', ''),
                'port': service_info.get('Port', None),
                'tags': service_info.get('Tags', []),
                'meta': service_info.get('Meta', {}),
                'health_checks': health_checks
            }
        
        # Return both individual services and grouped instances
        return {
            'services': service_data,
            'instances': group_services_by_instance(service_data)
        }
    except requests.exceptions.RequestException:
        logger.error("Failed to fetch service data from Consul")
        return {}
