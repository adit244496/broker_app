import { useMemo, useState } from 'react';
import { brokerApi, projectApi } from '@/api/services';
import { BrokerStatusBadge, Card, EmptyState, ErrorState, Loading, PageHeader } from '@/components/ui';
import { useAsync } from '@/hooks/useAsync';
import type { BrokerWithStats, ProjectAccess, ProjectMedia, ProjectWithAccess } from '@/types';
import { ProjectMediaEditor } from './ProjectMediaEditor';

/** "All brokers", "3 brokers", "Hidden from all brokers". */
export function accessLabel(access: ProjectAccess) {
  if (!access.restricted) return 'All brokers';
  const n = access.brokerIds.length;
  if (!n) return 'Hidden from all brokers';
  return `${n} selected broker${n === 1 ? '' : 's'}`;
}

function AccessBadge({ access }: { access: ProjectAccess }) {
  const kind = !access.restricted ? 'all' : access.brokerIds.length ? 'some' : 'none';
  return <span className={`badge access-${kind}`}>{accessLabel(access)}</span>;
}

/** "Icon · Cover · 2 videos", or a nudge when nothing is added yet. */
function mediaSummary(m: ProjectMedia) {
  const parts = [
    m.iconUrl ? 'Icon' : '',
    m.coverUrl || m.salesforceImageUrl ? 'Cover' : '',
    m.videos.length ? `${m.videos.length} video${m.videos.length === 1 ? '' : 's'}` : '',
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : <span className="muted">Nothing added</span>;
}

// Brokers worth offering in the picker: those who can (or soon will) use the app.
const PICKABLE = new Set(['Active', 'Approved']);

export function ProjectsPage() {
  const projects = useAsync(() => projectApi.listWithAccess());
  const brokers = useAsync(() => brokerApi.list());
  const [saved, setSaved] = useState<Record<string, ProjectAccess>>({});
  const [savedMedia, setSavedMedia] = useState<Record<string, ProjectMedia>>({});
  // "access:<id>" or "media:<id>": which editor is open, for which project.
  const [editing, setEditing] = useState<string>();
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string }>();

  const rows = (projects.data ?? []).map((p) => ({ ...p, access: saved[p.id] ?? p.access, media: savedMedia[p.id] ?? p.media }));
  const current = rows.find((p) => editing === `access:${p.id}`);
  const mediaProject = rows.find((p) => editing === `media:${p.id}`);
  const open = (what: 'access' | 'media', id: string) => {
    setNotice(undefined);
    setEditing(`${what}:${id}`);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <>
      <PageHeader
        title="Projects"
        subtitle="Choose which brokers see each project, and add a logo, cover image and videos so it looks good in the app. Projects come from Salesforce; only the ones Salesforce makes available to the app are listed."
      />

      {notice ? (
        <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>
          {notice.text}
        </div>
      ) : null}

      {current ? (
        <AccessEditor
          key={current.id}
          project={current}
          brokers={brokers.data}
          brokersError={brokers.error}
          onCancel={() => setEditing(undefined)}
          onSaved={(access) => {
            setSaved((s) => ({ ...s, [current.id]: access }));
            setEditing(undefined);
            setNotice({ kind: 'success', text: `${current.name}: now visible to ${accessLabel(access).toLowerCase()}.` });
          }}
        />
      ) : null}

      {mediaProject ? (
        <ProjectMediaEditor
          key={mediaProject.id}
          project={mediaProject}
          onClose={() => setEditing(undefined)}
          onChange={(media) => setSavedMedia((m) => ({ ...m, [mediaProject.id]: media }))}
        />
      ) : null}

      <Card>
        {projects.error && !projects.data ? (
          <ErrorState message={projects.error} onRetry={projects.reload} />
        ) : !projects.data ? (
          <Loading />
        ) : rows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Look &amp; media</th>
                  <th>Visible to</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <div className="project-cell">
                        <span className="project-logo" aria-hidden="true">
                          {p.media.iconUrl ? <img src={p.media.iconUrl} alt="" /> : p.name.slice(0, 1)}
                        </span>
                        <span>
                          {p.name}
                          {p.location ? <span className="sub">{p.location}</span> : null}
                        </span>
                      </div>
                    </td>
                    <td className="media-summary">{mediaSummary(p.media)}</td>
                    <td>
                      <AccessBadge access={p.access} />
                    </td>
                    <td className="num">
                      <div className="row-actions">
                        <button className="btn btn-secondary" disabled={editing === `media:${p.id}`} onClick={() => open('media', p.id)}>
                          Media
                        </button>
                        <button className="btn btn-secondary" disabled={editing === `access:${p.id}`} onClick={() => open('access', p.id)}>
                          Visibility
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No projects in the app yet"
            message="Salesforce isn't making any project available to the broker app. Ask the Salesforce team to mark the projects brokers should see."
          />
        )}
      </Card>
    </>
  );
}

function AccessEditor({
  project,
  brokers,
  brokersError,
  onCancel,
  onSaved,
}: {
  project: ProjectWithAccess;
  brokers?: BrokerWithStats[];
  brokersError?: string;
  onCancel: () => void;
  onSaved: (access: ProjectAccess) => void;
}) {
  const [restricted, setRestricted] = useState(project.access.restricted);
  const [selected, setSelected] = useState(() => new Set(project.access.brokerIds));
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  // Active/approved brokers, plus anyone selected when the editor opened (whatever their status now), so
  // unticking someone doesn't make them vanish from the list.
  const [initiallySelected] = useState(() => new Set(project.access.brokerIds));
  const options = useMemo(
    () =>
      (brokers ?? [])
        .filter((b) => PICKABLE.has(b.status) || initiallySelected.has(b.id))
        .sort((a, b) => a.accountName.localeCompare(b.accountName)),
    [brokers, initiallySelected],
  );
  const needle = search.trim().toLowerCase();
  const shown = needle
    ? options.filter((b) => [b.accountName, b.cpMobile, b.cpEmail].some((x) => (x ?? '').toLowerCase().includes(needle)))
    : options;

  const toggle = (id: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const setMany = (ids: string[], on: boolean) =>
    setSelected((s) => {
      const next = new Set(s);
      ids.forEach((id) => (on ? next.add(id) : next.delete(id)));
      return next;
    });

  const save = async () => {
    if (restricted && !selected.size && !window.confirm(`No brokers selected. Hide ${project.name} from every broker?`)) return;
    setBusy(true);
    setError(undefined);
    try {
      onSaved(await projectApi.setAccess(project.id, { restricted, brokerIds: restricted ? [...selected] : [] }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title={`Who can see ${project.name}?`} className="access-editor">
      <div className="settings-form">
        {error ? (
          <div className="alert alert-error" role="alert" style={{ margin: 0 }}>
            {error}
          </div>
        ) : null}

        <fieldset className="choice-group">
          <legend className="visually-hidden">Visibility</legend>
          <label className={`choice ${!restricted ? 'checked' : ''}`}>
            <input type="radio" name="visibility" checked={!restricted} onChange={() => setRestricted(false)} />
            <span>
              <strong>All brokers</strong>
              <span className="choice-help">Every broker who can log in sees this project, including new ones.</span>
            </span>
          </label>
          <label className={`choice ${restricted ? 'checked' : ''}`}>
            <input type="radio" name="visibility" checked={restricted} onChange={() => setRestricted(true)} />
            <span>
              <strong>Only selected brokers</strong>
              <span className="choice-help">Everyone else can't see it, open its brochures or submit leads for it.</span>
            </span>
          </label>
        </fieldset>

        {restricted ? (
          brokersError && !brokers ? (
            <div className="alert alert-error" role="alert" style={{ margin: 0 }}>
              Couldn't load brokers: {brokersError}
            </div>
          ) : !brokers ? (
            <Loading />
          ) : (
            <div className="picker">
              <div className="picker-bar">
                <input
                  className="input search"
                  placeholder="Search broker, mobile or email"
                  aria-label="Search brokers"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
                <button className="btn btn-ghost" type="button" onClick={() => setMany(shown.map((b) => b.id), true)}>
                  Select {needle ? 'shown' : 'all'}
                </button>
                <button className="btn btn-ghost" type="button" onClick={() => setMany(shown.map((b) => b.id), false)}>
                  Clear {needle ? 'shown' : 'all'}
                </button>
              </div>
              <p className="field-help" style={{ margin: 0 }}>
                {selected.size} of {options.length} selected
              </p>
              <ul className="checklist" aria-label="Brokers">
                {shown.map((b) => (
                  <li key={b.id}>
                    <label>
                      <input type="checkbox" checked={selected.has(b.id)} onChange={() => toggle(b.id)} />
                      <span className="checklist-name">
                        {b.accountName}
                        <span className="sub">{b.cpMobile}</span>
                      </span>
                      {b.status !== 'Active' ? <BrokerStatusBadge status={b.status} /> : null}
                    </label>
                  </li>
                ))}
                {!shown.length ? <li className="checklist-empty">No brokers match “{search}”.</li> : null}
              </ul>
            </div>
          )
        ) : null}

        <div className="settings-actions">
          <button className="btn btn-primary" disabled={busy} onClick={save}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button className="btn btn-ghost" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
        </div>
      </div>
    </Card>
  );
}
