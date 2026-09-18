type RuntimeEnvironment = Record<string, string | undefined>;

/**
 * Demo data is the safe default for an unconfigured frontend deployment.
 * Live mode must be selected explicitly because it requires both the API and
 * authentication services to be configured.
 */
export function isDemoMode(environment: RuntimeEnvironment = process.env) {
  return environment.DASHBOARD_DEMO_MODE !== "false";
}
