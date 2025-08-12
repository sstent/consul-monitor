import requests
import logging
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Consul configuration
CONSUL_HOST = "consul.service.dc1.consul"
CONSUL_PORT = 8500
CONSUL_BASE_URL = f"http://{CONSUL_HOST}:{CONSUL_PORT}"

def get_all_service_names():
    """Fetch all service names from Consul catalog"""
    url = f"{CONSUL_BASE_URL}/v1/catalog/services"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        services = response.json()
        # Filter out consul service and return service names
        return [name for name in services.keys() if name != 'consul']
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch Consul services: {e}")
        return []

def get_service_instances(service_name):
    """Fetch instances of a service from Consul catalog"""
    url = f"{CONSUL_BASE_URL}/v1/catalog/service/{service_name}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch instances for service {service_name}: {e}")
        return []

def get_service_health(service_name):
    """Fetch health checks for a specific service"""
    url = f"{CONSUL_BASE_URL}/v1/health/service/{service_name}"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch health for service {service_name}: {e}")
        return []

def is_consul_available():
    """Check if Consul is reachable"""
    try:
        response = requests.get(f"{CONSUL_BASE_URL}/v1/agent/self", timeout=2)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False

def fetch_all_service_data():
    """Fetch service data and health status for all services, grouped by instance"""
    try:
        # Get all service names
        service_names = get_all_service_names()
        if not service_names:
            logger.warning("No services found in Consul catalog")
            return {}
        
        logger.info(f"Received {len(service_names)} services from Consul")
        
        # Initialize data structures
        service_data = {}
        instances = defaultdict(lambda: {
            'address': '',
            'health_status': 'passing',
            'services': []
        })
        
        # Process each service
        for service_name in service_names:
            # Get service instances from catalog
            catalog_instances = get_service_instances(service_name)
            if not catalog_instances:
                continue
                
            # Get health information
            health_data = get_service_health(service_name)
            
            # Create a mapping of Node+ServiceID to health checks
            health_map = {}
            for entry in health_data:
                node = entry['Node']['Node']
                service_id = entry['Service']['ID']
                health_map[(node, service_id)] = entry['Checks']
            
            # Process each instance
            for instance in catalog_instances:
                node = instance['Node']
                service_id = instance['ServiceID']
                address = instance['ServiceAddress'] or instance['Address']
                port = instance['ServicePort']
                
                # Get health checks for this instance
                checks = health_map.get((node, service_id), [])
                health_checks = [
                    {'check_name': c.get('Name', ''), 'status': c.get('Status', '')} 
                    for c in checks
                ]
                
                # Create service object
                service_obj = {
                    'id': service_id,
                    'name': service_name,
                    'address': address,
                    'port': port,
                    'tags': instance.get('ServiceTags', []),
                    'meta': instance.get('ServiceMeta', {}),
                    'health_checks': health_checks
                }
                
                # Add to service data
                service_data[service_id] = service_obj
                
                # Add to instance grouping
                if address not in instances:
                    instances[address]['address'] = address
                instances[address]['services'].append(service_obj)
        
        # Calculate composite health for each instance
        for instance in instances.values():
            status_priority = {'critical': 3, 'warning': 2, 'passing': 1}
            worst_status = 'passing'
            for service in instance['services']:
                for check in service['health_checks']:
                    if status_priority.get(check['status'], 0) > status_priority.get(worst_status, 0):
                        worst_status = check['status']
            instance['health_status'] = worst_status
        
        return {
            'services': service_data,
            'instances': dict(instances)
        }
        
    except Exception as e:
        logger.error(f"Error fetching service data: {e}")
        return {}
