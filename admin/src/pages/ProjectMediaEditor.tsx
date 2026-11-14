import { useRef, useState } from 'react';
import { projectApi } from '@/api/services';
import { Card } from '@/components/ui';
import type { MediaKind, ProjectMedia, ProjectWithAccess } from '@/types';

const ACCEPT = 'image/png,image/jpeg,image/webp';
const LIMIT_MB: Record<MediaKind, number> = { icon: 1, cover: 5 };
const MAX_VIDEOS = 10;
const YT = /(?:youtube\.com\/(?:watch\?v=|shorts\/|embed\/|live\/)|youtu\.be\/)([A-Za-z0-9_-]{11})/;

type VideoDraft = { key: string; id?: string; title: string; url: string };

const ytThumb = (url: string) => {
  const id = YT.exec(url)?.[1];
  return id ? `https://img.youtube.com/vi/${id}/mqdefault.jpg` : undefined;
};

export function ProjectMediaEditor({
  project,
  onClose,
  onChange,
}: {
  project: ProjectWithAccess;
  onClose: () => void;
  onChange: (media: ProjectMedia) => void;
}) {
  const [media, setMedia] = useState(project.media);
  const [busy, setBusy] = useState<string>();
  const [notice, setNotice] = useState<{ kind: 'success' | 'error'; text: string }>();
  const [videos, setVideos] = useState<VideoDraft[]>(() =>
    project.media.videos.map((v) => ({ key: v.id, id: v.id, title: v.title, url: v.url })),
  );
  const [videosDirty, setVideosDirty] = useState(false);

  const apply = (m: ProjectMedia, text: string) => {
    setMedia(m);
    onChange(m);
    setNotice({ kind: 'success', text });
  };

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setNotice(undefined);
    try {
      await fn();
    } catch (e) {
      setNotice({ kind: 'error', text: (e as Error).message });
    } finally {
      setBusy(undefined);
    }
  };

  const upload = (kind: MediaKind, file: File) =>
    run(kind, async () => {
      if (!ACCEPT.split(',').includes(file.type)) throw new Error('Use a PNG, JPG or WebP image.');
      if (file.size > LIMIT_MB[kind] * 1024 * 1024) throw new Error(`The image is too large. The limit is ${LIMIT_MB[kind]} MB.`);
      apply(await projectApi.uploadImage(project.id, kind, file), kind === 'icon' ? 'Icon updated.' : 'Cover image updated.');
    });

  const remove = (kind: MediaKind) =>
    run(`remove-${kind}`, async () => {
      apply(await projectApi.removeImage(project.id, kind), kind === 'icon' ? 'Icon removed.' : 'Cover image removed.');
    });

  const editVideo = (key: string, patch: Partial<VideoDraft>) => {
    setVideos((vs) => vs.map((v) => (v.key === key ? { ...v, ...patch } : v)));
    setVideosDirty(true);
  };
  const moveVideo = (index: number, by: -1 | 1) => {
    setVideos((vs) => {
      const next = [...vs];
      const [item] = next.splice(index, 1);
      next.splice(index + by, 0, item!);
      return next;
    });
    setVideosDirty(true);
  };

  const saveVideos = () =>
    run('videos', async () => {
      const m = await projectApi.setVideos(
        project.id,
        videos.filter((v) => v.title.trim() || v.url.trim()).map((v) => ({ id: v.id ?? '', title: v.title, url: v.url })),
      );
      setVideos(m.videos.map((v) => ({ key: v.id, id: v.id, title: v.title, url: v.url })));
      setVideosDirty(false);
      apply(m, 'Videos saved.');
    });

  const cover = media.coverUrl ?? media.salesforceImageUrl;

  return (
    <Card title={`Look & media: ${project.name}`} note="What brokers see on the project in the app" className="access-editor">
      {notice ? (
        <div className={`alert alert-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>
          {notice.text}
        </div>
      ) : null}

      <div className="media-layout">
        <div className="media-main">
          <div className="media-slots">
            <ImageSlot
              label="Icon / logo"
              help="Square, at least 256×256. A PNG with a transparent background looks best. Up to 1 MB."
              shape="square"
              url={media.iconUrl}
              busy={busy}
              kind="icon"
              onUpload={(f) => upload('icon', f)}
              onRemove={() => remove('icon')}
            />
            <ImageSlot
              label="Cover image"
              help="Wide photo (16:9), at least 1200×675. Up to 5 MB."
              shape="wide"
              url={media.coverUrl}
              fallbackUrl={media.salesforceImageUrl}
              busy={busy}
              kind="cover"
              onUpload={(f) => upload('cover', f)}
              onRemove={() => remove('cover')}
            />
          </div>

          <div className="media-videos">
            <div className="card-head" style={{ marginBottom: 8 }}>
              <h3 className="media-h">Videos</h3>
              <span>YouTube, Vimeo or any https:// link. Up to {MAX_VIDEOS}.</span>
            </div>
            {videos.length ? (
              <ul className="video-list">
                {videos.map((v, i) => {
                  const thumb = ytThumb(v.url);
                  return (
                    <li key={v.key} className="video-item">
                      <div className="video-thumb" aria-hidden="true">
                        {thumb ? <img src={thumb} alt="" /> : <span>▶</span>}
                      </div>
                      <div className="video-fields">
                        <input
                          className="input"
                          placeholder="Title, e.g. Project walkthrough"
                          aria-label={`Video ${i + 1} title`}
                          maxLength={80}
                          value={v.title}
                          onChange={(e) => editVideo(v.key, { title: e.target.value })}
                        />
                        <input
                          className="input"
                          placeholder="https://www.youtube.com/watch?v=…"
                          aria-label={`Video ${i + 1} link`}
                          inputMode="url"
                          value={v.url}
                          onChange={(e) => editVideo(v.key, { url: e.target.value })}
                        />
                      </div>
                      <div className="video-actions">
                        <button className="btn btn-ghost" type="button" disabled={i === 0} onClick={() => moveVideo(i, -1)} aria-label="Move up">
                          ↑
                        </button>
                        <button
                          className="btn btn-ghost"
                          type="button"
                          disabled={i === videos.length - 1}
                          onClick={() => moveVideo(i, 1)}
                          aria-label="Move down"
                        >
                          ↓
                        </button>
                        <button
                          className="btn btn-ghost"
                          type="button"
                          onClick={() => {
                            setVideos((vs) => vs.filter((x) => x.key !== v.key));
                            setVideosDirty(true);
                          }}
                          aria-label={`Remove video ${i + 1}`}
                        >
                          Remove
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="field-help" style={{ margin: '0 0 8px' }}>
                No videos yet. A walkthrough or drone video makes the project stand out.
              </p>
            )}
            <div className="settings-actions">
              <button
                className="btn btn-secondary"
                type="button"
                disabled={videos.length >= MAX_VIDEOS}
                onClick={() => {
                  setVideos((vs) => [...vs, { key: `new-${Date.now()}`, title: '', url: '' }]);
                  setVideosDirty(true);
                }}
              >
                + Add video
              </button>
              <button className="btn btn-primary" type="button" disabled={!videosDirty || !!busy} onClick={saveVideos}>
                {busy === 'videos' ? 'Saving…' : 'Save videos'}
              </button>
            </div>
          </div>
        </div>

        <aside className="media-preview" aria-label="Preview in the app">
          <div className="preview-label">Preview in the app</div>
          <div className="preview-card">
            <div className="preview-cover">
              {cover ? <img src={cover} alt="" /> : null}
              {videos.length ? <span className="preview-badge">▶ {videos.length === 1 ? 'Video' : `${videos.length} videos`}</span> : null}
              {media.iconUrl ? (
                <span className="preview-icon">
                  <img src={media.iconUrl} alt="" />
                </span>
              ) : null}
            </div>
            <div className={`preview-body ${media.iconUrl ? 'with-icon' : ''}`}>
              <strong>{project.name}</strong>
              {project.location ? <span className="sub">{project.location}</span> : null}
              {project.projectType ? <span className="chip">{project.projectType}</span> : null}
            </div>
          </div>
        </aside>
      </div>

      <div className="settings-actions" style={{ marginTop: 16 }}>
        <button
          className="btn btn-ghost"
          onClick={() => {
            if (videosDirty && !window.confirm('Your video changes are not saved. Close anyway?')) return;
            onClose();
          }}
        >
          Done
        </button>
      </div>
    </Card>
  );
}

function ImageSlot({
  label,
  help,
  shape,
  url,
  fallbackUrl,
  kind,
  busy,
  onUpload,
  onRemove,
}: {
  label: string;
  help: string;
  shape: 'square' | 'wide';
  url?: string;
  fallbackUrl?: string;
  kind: MediaKind;
  busy?: string;
  onUpload: (file: File) => void;
  onRemove: () => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const shown = url ?? fallbackUrl;
  return (
    <div className="image-slot">
      <h3 className="media-h">{label}</h3>
      <div className={`image-box ${shape}`}>
        {shown ? <img src={shown} alt={`${label} preview`} /> : <span>No image</span>}
        {busy === kind ? <div className="image-busy">Uploading…</div> : null}
      </div>
      {!url && fallbackUrl ? <p className="field-help" style={{ margin: 0 }}>Showing the image from Salesforce.</p> : null}
      <p className="field-help" style={{ margin: 0 }}>{help}</p>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="visually-hidden"
        tabIndex={-1}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = ''; // allow picking the same file again
          if (file) onUpload(file);
        }}
      />
      <div className="settings-actions">
        <button className="btn btn-secondary" type="button" disabled={!!busy} onClick={() => input.current?.click()}>
          {url ? 'Replace' : 'Upload'}
        </button>
        {url ? (
          <button className="btn btn-ghost" type="button" disabled={!!busy} onClick={onRemove}>
            {busy === `remove-${kind}` ? 'Removing…' : 'Remove'}
          </button>
        ) : null}
      </div>
    </div>
  );
}
