# Project Field Service

`ProjectFieldService` owns project-configuration field use cases: field value
resolution, value normalization, inline update plans, active project file
selection plans, settings field plans, availability policy, disabled reasons,
hints, and Enter-key action routing.

Project configuration screens and controllers consume this service directly.
Legacy functions in `src/fields.py` remain as compatibility facades for current
tests and existing callers.
