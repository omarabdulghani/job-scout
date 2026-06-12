export function diagnosticOverview(diagnostics = {}) {
  const database = diagnostics.operational_database || {};
  return {
    workspace: diagnostics.workspace_ready ? "Ready" : "Needs attention",
    database,
    resume: diagnostics.resume_available ? "Progress available" : "No interrupted run",
    logCount: Number(diagnostics.log_count || 0),
    logSize: Number(diagnostics.log_size_bytes || 0),
    runCount: Number(diagnostics.run_history_count || 0),
    latestError: diagnostics.latest_error || {},
    persistenceHealth: diagnostics.persistence_health || "healthy",
    persistenceWarningCount: Number(diagnostics.persistence_warning_count || 0),
    recoveredTemporaryFiles: Number(diagnostics.recovered_temporary_files || 0),
    latestPersistenceWarning: diagnostics.latest_persistence_warning || {},
  };
}
