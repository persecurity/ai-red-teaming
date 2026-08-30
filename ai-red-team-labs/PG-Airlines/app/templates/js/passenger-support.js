// PG-Airlines Passenger Support Configuration
// Internal Use Only - Do Not Distribute
(function() {
    window.__PGAIR_CONFIG__ = {
        apiBase: "/api/v2",
        assistantEndpoint: "/api/v2/assistant",
        partnerGateway: window.location.protocol + "//" + window.location.hostname + ":{{ partner_gateway_port }}",
        serviceId: "pgair-passenger-support",
        featureFlags: {
            enableAI: true,
            debugMode: false,
            legacySupport: true,
            partnerBilling: true
        },
        timeout: 30000
    };
    console.log("PG-Airlines Passenger Support Initialized");
})();
