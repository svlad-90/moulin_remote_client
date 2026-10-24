"""Transactional configuration entity and reference store."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Iterable, Protocol
from uuid import uuid4


class DeletePolicy(str, Enum):
    """Action applied to a source entity when its target is deleted."""

    DETACH = "detach"
    RESTRICT = "restrict"


@dataclass(frozen=True, order=True)
class EntityRef:
    kind: str
    entity_id: str


@dataclass(frozen=True)
class EntityAdapter:
    kind: str
    records: Callable[[dict[str, Any]], Iterable[dict[str, Any]]]
    delete: Callable[[dict[str, Any], str], None]
    label: Callable[[dict[str, Any]], str] = lambda record: str(record.get("name") or record.get("id") or "")
    owned: Callable[[dict[str, Any], str], Iterable[EntityRef]] = lambda _config, _entity_id: ()
    create: Callable[[dict[str, Any], str, dict[str, Any]], None] | None = None
    update: Callable[[dict[str, Any], str, dict[str, Any]], None] | None = None


@dataclass(frozen=True)
class ReferenceLink:
    source: EntityRef
    target: EntityRef
    description: str


@dataclass(frozen=True)
class ReferenceAdapter:
    name: str
    source_kind: str
    target_kind: str
    policy: DeletePolicy
    links: Callable[[dict[str, Any]], Iterable[ReferenceLink]]
    detach: Callable[[dict[str, Any], ReferenceLink], None] | None = None
    replace: Callable[[dict[str, Any], EntityRef, tuple[EntityRef, ...]], None] | None = None


class ConfigContributor(Protocol):
    """A component-owned declaration of configuration entities and links."""

    def contribute_config(self, registrar: "ConfigRegistrar") -> None:
        """Register entity and reference adapters owned by this component."""


@dataclass(frozen=True)
class ReferenceIssue:
    adapter_name: str
    link: ReferenceLink
    reason: str


@dataclass(frozen=True)
class DeletionImpact:
    adapter_name: str
    policy: DeletePolicy
    link: ReferenceLink


@dataclass(frozen=True)
class DeletionPlan:
    target: EntityRef
    target_label: str
    affected_targets: tuple[EntityRef, ...]
    impacts: tuple[DeletionImpact, ...]
    signature: tuple[tuple[str, str, str, str, str], ...]

    @property
    def blockers(self) -> tuple[DeletionImpact, ...]:
        return tuple(impact for impact in self.impacts if impact.policy is DeletePolicy.RESTRICT)

    @property
    def updates(self) -> tuple[DeletionImpact, ...]:
        return tuple(impact for impact in self.impacts if impact.policy is DeletePolicy.DETACH)


@dataclass(frozen=True)
class ConfigChanged:
    revision: int
    deleted: tuple[EntityRef, ...]
    updated: tuple[EntityRef, ...]
    created: tuple[EntityRef, ...] = ()


@dataclass(frozen=True)
class EntityCreateResult:
    reference: EntityRef
    change: ConfigChanged


class ConfigStoreError(RuntimeError):
    pass


class UnknownEntityError(ConfigStoreError):
    pass


class UnsupportedEntityOperationError(ConfigStoreError):
    pass


class DeletionRestrictedError(ConfigStoreError):
    def __init__(self, plan: DeletionPlan) -> None:
        super().__init__("entity is still referenced")
        self.plan = plan


class StaleDeletionPlanError(ConfigStoreError):
    pass


class ConfigRegistrar:
    """Registration surface shared by built-in components and plugins."""

    def __init__(self) -> None:
        self.entities: dict[str, EntityAdapter] = {}
        self.references: dict[str, ReferenceAdapter] = {}

    def register_entity(self, adapter: EntityAdapter) -> None:
        if adapter.kind in self.entities:
            raise ValueError(f"configuration entity kind already registered: {adapter.kind}")
        self.entities[adapter.kind] = adapter

    def register_reference(self, adapter: ReferenceAdapter) -> None:
        if adapter.name in self.references:
            raise ValueError(f"configuration reference already registered: {adapter.name}")
        if adapter.policy is DeletePolicy.DETACH and adapter.detach is None:
            raise ValueError(f"detach reference has no detach handler: {adapter.name}")
        self.references[adapter.name] = adapter


class ConfigStore:
    """Own configuration mutations that cross component boundaries."""

    def __init__(
        self,
        config: dict[str, Any],
        *,
        save: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self.config = config
        self._save = save
        self._registrar = ConfigRegistrar()
        self._revision = 0
        self._subscribers: list[Callable[[ConfigChanged], None]] = []
        self.notification_errors: list[str] = []

    @property
    def revision(self) -> int:
        return self._revision

    def initialize(self, contributors: Iterable[ConfigContributor]) -> tuple[ReferenceIssue, ...]:
        owners: list[tuple[ConfigContributor, set[str]]] = []
        for contributor in contributors:
            previous_kinds = set(self._registrar.entities)
            contributor.contribute_config(self._registrar)
            owners.append((contributor, set(self._registrar.entities) - previous_kinds))
            changed = getattr(contributor, "on_config_changed", None)
            if callable(changed):
                self.subscribe(changed)
        issues = self.audit()
        for contributor, source_kinds in owners:
            notify = getattr(contributor, "on_reference_issues", None)
            if callable(notify):
                try:
                    notify(tuple(issue for issue in issues if issue.link.source.kind in source_kinds))
                except Exception as exc:
                    self.notification_errors.append(str(exc))
        return issues

    def subscribe(self, callback: Callable[[ConfigChanged], None]) -> None:
        self._subscribers.append(callback)

    def entity(self, reference: EntityRef, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
        adapter = self._registrar.entities.get(reference.kind)
        if adapter is None:
            return None
        values = self.config if config is None else config
        return next(
            (
                record
                for record in adapter.records(values)
                if str(record.get("id") or "") == reference.entity_id
            ),
            None,
        )

    def audit(self, config: dict[str, Any] | None = None) -> tuple[ReferenceIssue, ...]:
        values = self.config if config is None else config
        issues: list[ReferenceIssue] = []
        for adapter in self._registrar.references.values():
            if adapter.source_kind not in self._registrar.entities:
                issues.append(self._adapter_issue(adapter, "source entity kind is not registered"))
                continue
            if adapter.target_kind not in self._registrar.entities:
                issues.append(self._adapter_issue(adapter, "target entity kind is not registered"))
                continue
            for link in adapter.links(values):
                if self.entity(link.source, values) is None:
                    issues.append(ReferenceIssue(adapter.name, link, "source entity is missing"))
                elif self.entity(link.target, values) is None:
                    issues.append(ReferenceIssue(adapter.name, link, "target entity is missing"))
        return tuple(issues)

    def create_entity(self, kind: str, values: dict[str, Any]) -> EntityCreateResult:
        adapter = self._registrar.entities.get(kind)
        if adapter is None:
            raise UnknownEntityError(f"unknown configuration entity kind: {kind}")
        if adapter.create is None:
            raise UnsupportedEntityOperationError(f"configuration entity cannot be created: {kind}")
        if "id" in values:
            raise ConfigStoreError("entity id is assigned by the configuration store")

        staged = deepcopy(self.config)
        baseline_issues = {self._issue_signature(issue) for issue in self.audit(staged)}
        baseline_ids = self._entity_ids(adapter, staged)
        entity_id = str(uuid4())
        while entity_id in baseline_ids:
            entity_id = str(uuid4())
        adapter.create(staged, entity_id, deepcopy(values))
        reference = EntityRef(kind, entity_id)
        if self.entity(reference, staged) is None:
            raise ConfigStoreError(f"entity adapter did not create requested entity: {kind}:{entity_id}")
        if self._entity_ids(adapter, staged) != baseline_ids | {entity_id}:
            raise ConfigStoreError(f"entity adapter changed unexpected identities while creating: {kind}")
        self._assert_no_introduced_issues(staged, baseline_issues, "entity creation")
        change = self._commit(staged, created=(reference,))
        return EntityCreateResult(reference, change)

    def update_entity(self, reference: EntityRef, changes: dict[str, Any]) -> ConfigChanged | None:
        adapter = self._registrar.entities.get(reference.kind)
        if adapter is None or self.entity(reference) is None:
            raise UnknownEntityError(
                f"unknown configuration entity: {reference.kind}:{reference.entity_id}"
            )
        if adapter.update is None:
            raise UnsupportedEntityOperationError(
                f"configuration entity cannot be updated: {reference.kind}"
            )
        if "id" in changes:
            raise ConfigStoreError("entity id is immutable")

        staged = deepcopy(self.config)
        baseline_issues = {self._issue_signature(issue) for issue in self.audit(staged)}
        baseline_ids = self._entity_ids(adapter, staged)
        adapter.update(staged, reference.entity_id, deepcopy(changes))
        if self.entity(reference, staged) is None or self._entity_ids(adapter, staged) != baseline_ids:
            raise ConfigStoreError(
                f"entity adapter changed entity identities while updating: {reference.kind}"
            )
        self._assert_no_introduced_issues(staged, baseline_issues, "entity update")
        if staged == self.config:
            return None
        return self._commit(staged, updated=(reference,))

    def prepare_delete(self, target: EntityRef) -> DeletionPlan:
        record = self.entity(target)
        if record is None:
            raise UnknownEntityError(f"unknown configuration entity: {target.kind}:{target.entity_id}")
        adapter = self._registrar.entities[target.kind]
        affected = self._expand_owned(target)
        affected_set = set(affected)
        impacts: list[DeletionImpact] = []
        for reference in self._registrar.references.values():
            for link in reference.links(self.config):
                if link.target not in affected_set or link.source in affected_set:
                    continue
                impacts.append(DeletionImpact(reference.name, reference.policy, link))
        impacts.sort(key=self._impact_key)
        signature = tuple(self._impact_signature(impact) for impact in impacts)
        return DeletionPlan(
            target=target,
            target_label=adapter.label(record),
            affected_targets=affected,
            impacts=tuple(impacts),
            signature=signature,
        )

    def execute_delete(self, plan: DeletionPlan) -> ConfigChanged:
        current = self.prepare_delete(plan.target)
        if current.affected_targets != plan.affected_targets or current.signature != plan.signature:
            raise StaleDeletionPlanError("configuration dependencies changed; prepare deletion again")
        if current.blockers:
            raise DeletionRestrictedError(current)

        staged = deepcopy(self.config)
        baseline_issues = {self._issue_signature(issue) for issue in self.audit(staged)}
        updated: set[EntityRef] = set()
        for impact in current.updates:
            reference = self._registrar.references[impact.adapter_name]
            if reference.detach is None:
                raise ConfigStoreError(f"reference cannot be detached: {reference.name}")
            reference.detach(staged, impact.link)
            updated.add(impact.link.source)

        self._registrar.entities[current.target.kind].delete(staged, current.target.entity_id)
        introduced = [
            issue
            for issue in self.audit(staged)
            if self._issue_signature(issue) not in baseline_issues
        ]
        if introduced:
            details = ", ".join(f"{issue.adapter_name}:{issue.reason}" for issue in introduced)
            raise ConfigStoreError(f"deletion would create invalid references: {details}")

        return self._commit(staged, deleted=current.affected_targets, updated=tuple(sorted(updated)))

    def replace_references(
        self,
        adapter_name: str,
        source: EntityRef,
        targets: Iterable[EntityRef],
    ) -> ConfigChanged | None:
        """Replace one source's links through its owning reference adapter."""

        adapter = self._registrar.references.get(adapter_name)
        if adapter is None:
            raise ConfigStoreError(f"unknown configuration reference: {adapter_name}")
        if adapter.replace is None:
            raise ConfigStoreError(f"configuration reference is read-only: {adapter_name}")
        if source.kind != adapter.source_kind or self.entity(source) is None:
            raise UnknownEntityError(f"unknown configuration entity: {source.kind}:{source.entity_id}")

        normalized = tuple(dict.fromkeys(targets))
        for target in normalized:
            if target.kind != adapter.target_kind or self.entity(target) is None:
                raise UnknownEntityError(f"unknown configuration entity: {target.kind}:{target.entity_id}")

        staged = deepcopy(self.config)
        baseline_issues = {self._issue_signature(issue) for issue in self.audit(staged)}
        adapter.replace(staged, source, normalized)
        actual_targets = {
            link.target
            for link in adapter.links(staged)
            if link.source == source
        }
        if actual_targets != set(normalized):
            raise ConfigStoreError(f"reference adapter did not apply requested targets: {adapter_name}")
        self._assert_no_introduced_issues(staged, baseline_issues, "reference update")
        if staged == self.config:
            return None
        return self._commit(staged, updated=(source,))

    def describe(self, plan: DeletionPlan) -> tuple[str, ...]:
        return tuple(impact.link.description for impact in plan.impacts)

    def update_config(self, update: Callable[[dict[str, Any]], None]) -> ConfigChanged | None:
        """Atomically update non-entity application or plugin settings."""

        staged = deepcopy(self.config)
        baseline_issues = {self._issue_signature(issue) for issue in self.audit(staged)}
        update(staged)
        self._assert_no_introduced_issues(staged, baseline_issues, "configuration update")
        if staged == self.config:
            return None
        return self._commit(staged)

    def _commit(
        self,
        staged: dict[str, Any],
        *,
        deleted: tuple[EntityRef, ...] = (),
        updated: tuple[EntityRef, ...] = (),
        created: tuple[EntityRef, ...] = (),
    ) -> ConfigChanged:
        original = deepcopy(self.config)
        self.config.clear()
        self.config.update(staged)
        try:
            if self._save is not None:
                self._save(self.config)
        except Exception:
            self.config.clear()
            self.config.update(original)
            raise
        self._revision += 1
        event = ConfigChanged(self._revision, deleted, updated, created)
        for subscriber in tuple(self._subscribers):
            try:
                subscriber(event)
            except Exception as exc:
                self.notification_errors.append(str(exc))
        return event

    @staticmethod
    def _entity_ids(adapter: EntityAdapter, config: dict[str, Any]) -> set[str]:
        return {str(record.get("id") or "") for record in adapter.records(config)}

    def _assert_no_introduced_issues(
        self,
        staged: dict[str, Any],
        baseline_issues: set[tuple[str, str, str, str, str]],
        action: str,
    ) -> None:
        introduced = [
            issue
            for issue in self.audit(staged)
            if self._issue_signature(issue) not in baseline_issues
        ]
        if introduced:
            details = ", ".join(f"{issue.adapter_name}:{issue.reason}" for issue in introduced)
            raise ConfigStoreError(f"{action} would create invalid references: {details}")

    def _expand_owned(self, root: EntityRef) -> tuple[EntityRef, ...]:
        result: list[EntityRef] = []
        pending = [root]
        seen: set[EntityRef] = set()
        while pending:
            current = pending.pop(0)
            if current in seen:
                continue
            seen.add(current)
            result.append(current)
            adapter = self._registrar.entities.get(current.kind)
            if adapter is not None:
                pending.extend(adapter.owned(self.config, current.entity_id))
        return tuple(result)

    @staticmethod
    def _impact_key(impact: DeletionImpact) -> tuple[str, str, str]:
        return impact.adapter_name, impact.link.source.kind, impact.link.source.entity_id

    @staticmethod
    def _impact_signature(impact: DeletionImpact) -> tuple[str, str, str, str, str]:
        return (
            impact.adapter_name,
            impact.policy.value,
            impact.link.source.kind,
            impact.link.source.entity_id,
            impact.link.target.entity_id,
        )

    @staticmethod
    def _issue_signature(issue: ReferenceIssue) -> tuple[str, str, str, str, str]:
        return (
            issue.adapter_name,
            issue.link.source.kind,
            issue.link.source.entity_id,
            issue.link.target.kind,
            issue.link.target.entity_id,
        )

    @staticmethod
    def _adapter_issue(adapter: ReferenceAdapter, reason: str) -> ReferenceIssue:
        return ReferenceIssue(
            adapter.name,
            ReferenceLink(EntityRef(adapter.source_kind, ""), EntityRef(adapter.target_kind, ""), adapter.name),
            reason,
        )


def config_store(
    config: dict[str, Any],
    *,
    save: Callable[[dict[str, Any]], Any] | None = None,
) -> ConfigStore:
    return ConfigStore(config, save=save)
