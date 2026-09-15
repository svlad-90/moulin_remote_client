# Project Settings Policy Service

`ProjectSettingsPolicyService` owns project-settings action policy that is not
terminal-specific: menu labels, action descriptions, and Moulin parameter value
cycling.

`ProjectSettingsActionController` consumes this service and keeps
responsibility for dispatching actions, prompting, saving runtime settings, and
triggering UI side effects.
