# Application State

`AppStateController` owns application-level state workflows that combine
configuration, Moulin manifest data, mapping selection state, and UI profiling.
`ClientApp` keeps compatibility methods for existing UI and job components, but
delegates the orchestration here.
