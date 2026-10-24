# Configuration store

`ConfigStore` is the application-owned boundary for configuration operations
that cross component ownership. Built-in components and plugins implement the
same `ConfigContributor` contract. Plugin discovery is only one source of
contributors; it does not have a separate dependency API.

A contributor registers:

- entity adapters that enumerate and delete one owned entity type;
- optional entity create and update handlers owned by that component;
- reference adapters that enumerate outgoing GUID references;
- optional reference writers that replace one source entity's targets;
- an explicit `RESTRICT` or `DETACH` policy for each reference;
- optional `on_reference_issues` and `on_config_changed` callbacks.

Initialization has a registration phase followed by one audit. The audit runs
only after every contributor has registered, so references may target entities
owned by a component initialized later in the contributor list.

Deletion is two-phase. `prepare_delete()` returns a stable `DeletionPlan` for
the target, its owned entities, and every incoming reference. The target UI
renders this plan before asking for confirmation. `execute_delete()` rejects a
stale plan, blocks `RESTRICT` references, applies `DETACH` handlers to a copied
configuration, deletes the target, audits the result, and commits and saves the
configuration once. Post-commit subscribers cannot participate in reference
cleanup.

Reference selection is also transactional. `replace_references()` validates the
source and every target against the complete registry, applies the contributor's
writer to a copied configuration, audits the result, and then saves once. Active
core selections, active CTS/VTS selections, CTS/VTS run profile selectors,
product source selectors, and board-profile membership use this path.

Entity creation and update use the same transaction boundary. `create_entity()`
assigns the immutable GUID itself and verifies that the adapter created exactly
that identity. `update_entity()` rejects GUID changes and verifies that the
adapter preserved the entity registry. Both operations audit references before
saving. Entity adapters may leave either callback unset while their legacy UI
workflow is being migrated; the store then rejects that operation explicitly.

Creation is migrated for core build hosts, board hosts, physical boards, and
projects, plus CTS/VTS runners, board profiles, test profiles, product profiles,
and test runs. Existing domain constructors remain behind the adapters so
defaults and name validation stay component-owned.

Ordinary field editing for those entity types is also migrated through
`update_entity()`. Core host, board, and project field controllers normalize
input before submitting a patch; the entity adapter retains duplicate-name and
profile synchronization rules. CTS/VTS views submit scalar profile changes and
per-device ADB overrides through their adapters. Fields represented by
registered references, including profile membership and run/product selectors,
remain writable only through `replace_references()`.

Entity owners validate create and update payloads inside their adapters before
mutating the staged configuration. Validation covers allowed field names,
value types, required names, registered board/product type ids, host/network
formats, command and parameter mappings, and CTS/VTS-specific suites,
revisions, URLs, Tradefed arguments, recovery limits, runner workspaces, and
ADB serial overrides. UI validation remains useful for immediate feedback but
is not a trust boundary; invalid direct store calls fail before save and leave
the live configuration unchanged.

The legacy profile and plugin models remain the low-level adapters during the
incremental migration. Production deletion workflows must use `ConfigStore`;
adapter delete functions are not application use-case entry points.
