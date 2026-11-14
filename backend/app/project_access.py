"""
Who sees which project. Two layers:
1. Salesforce decides which projects are in the app at all (its projects endpoint / visibility field).
2. An admin can then limit a project to selected brokers. By default a project is visible to every broker.
"""

from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AdminUser, AuditLog, ProjectAccess, ProjectBroker
from app.salesforce.base import Record


@dataclass
class Access:
    restricted: bool = False
    broker_ids: set[str] = field(default_factory=set)

    def allows(self, account_id: str) -> bool:
        return not self.restricted or account_id in self.broker_ids

    def as_json(self) -> dict:
        return {"restricted": self.restricted, "brokerIds": sorted(self.broker_ids)}


def access_by_project(db: Session) -> dict[str, Access]:
    """Every restricted project's allow-list. Projects missing here are open to all brokers."""
    result: dict[str, Access] = {}
    for row in db.scalars(select(ProjectAccess).where(ProjectAccess.restricted.is_(True))):
        result[row.sf_project_id] = Access(restricted=True)
    if result:
        for link in db.scalars(select(ProjectBroker).where(ProjectBroker.sf_project_id.in_(result))):
            result[link.sf_project_id].broker_ids.add(link.sf_account_id)
    return result


def access_for(db: Session, project_id: str) -> Access:
    return access_by_project(db).get(project_id, Access())


def visible_to(db: Session, projects: list[Record], account_id: str) -> list[Record]:
    access = access_by_project(db)
    return [p for p in projects if access.get(p["Id"], Access()).allows(account_id)]


def can_see(db: Session, project: Record, account_id: str) -> bool:
    return access_for(db, project["Id"]).allows(account_id)


def set_access(db: Session, project: Record, restricted: bool, broker_ids: set[str], admin: AdminUser) -> Access:
    """Replaces the project's setting. Caller commits."""
    project_id = project["Id"]
    row = db.get(ProjectAccess, project_id) or ProjectAccess(sf_project_id=project_id)
    row.restricted = restricted
    row.updated_by = admin.id
    db.add(row)
    db.flush()
    db.execute(delete(ProjectBroker).where(ProjectBroker.sf_project_id == project_id))
    if restricted:
        db.add_all(ProjectBroker(sf_project_id=project_id, sf_account_id=b) for b in sorted(broker_ids))
    detail = f"{project.get('Name')}: " + (f"{len(broker_ids)} selected broker(s)" if restricted else "all brokers")
    db.add(AuditLog(admin_id=admin.id, action="project_access", detail=detail))
    return Access(restricted, set(broker_ids) if restricted else set())
