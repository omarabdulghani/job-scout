export function boardDefaults(payload = {}) {
  return {
    boards: payload.job_boards || {},
    behavior: payload.application_behavior || {},
    limits: payload.limits || {},
    defaults: payload.dashboard_defaults || {},
  };
}

export function providerStatus(provider = {}) {
  return {
    configured: Boolean(provider.configured),
    label: provider.configured ? "Configured" : "Not configured",
  };
}
