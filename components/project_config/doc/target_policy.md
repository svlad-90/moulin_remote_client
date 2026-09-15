# Target Selection Policy Service

`TargetSelectionPolicyService` owns build-target and board-artifact selection
rules: selected-target parsing, action construction, ordered text generation,
display text, toggle state transitions, and action labels/descriptions.

`TargetSelectionController` consumes this service and keeps responsibility for
terminal rendering, key handling, saving, and runtime reload side effects.
