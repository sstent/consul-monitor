console.log('app.js loading...');

document.addEventListener('alpine:init', () => {
    console.log('Registering serviceMonitor with Alpine.js');
    Alpine.data('serviceMonitor', () => ({
        services: [],
        loading: false,
        error: null,
        consulAvailable: true,
        
        init() {
            console.log('Initializing serviceMonitor component');
            this.refreshServices();
        },
        
        async refreshServices() {
            console.log('Refreshing services');
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
    }));
});

console.log('app.js loaded');
