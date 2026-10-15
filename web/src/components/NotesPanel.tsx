/**
 * The honesty panel.
 *
 * Everything the server measured and could not hide is shown here: the
 * series notes (a late start, a revision, a source delay), the gaps the
 * session law measured, and any per-symbol ingest failure. A chart without
 * this panel is a chart that looks confident when it is not.
 */

import type { FeedMeta } from "../hooks/useChartFeed";
import { formatMinutes, formatStamp } from "../chart/format";

export interface NotesPanelProps {
  readonly meta: FeedMeta;
}

export function NotesPanel({ meta }: NotesPanelProps) {
  const ingest = meta.payload?.ingest ?? null;
  const failures = Object.entries(ingest?.errors ?? {});

  return (
    <aside className="notes">
      <section className="notes__block">
        <h2>What this series is</h2>
        {meta.notes.length === 0 ? (
          <p className="notes__quiet">No caveats were reported for this window.</p>
        ) : (
          <ul>
            {meta.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="notes__block">
        <h2>Measured gaps</h2>
        {meta.gaps.length === 0 ? (
          <p className="notes__quiet">
            No gap long enough to report in this session.
          </p>
        ) : (
          <ul>
            {meta.gaps.map((gap) => (
              <li key={`${gap.start}-${gap.end}`}>
                {formatStamp(gap.start)} to {formatStamp(gap.end)} (
                {formatMinutes(Math.round(gap.minutes))}): {gap.reason}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="notes__block">
        <h2>Ingestion</h2>
        {ingest === null ? (
          <p className="notes__quiet">No ingestion report yet.</p>
        ) : (
          <ul>
            <li>
              {ingest.polls} poll(s) at {ingest.interval_seconds}s, watching{" "}
              {ingest.watched.length} symbol(s)
            </li>
            <li>
              last poll {ingest.last_poll_at === "" ? "never" : formatStamp(ingest.last_poll_at)}
            </li>
            {ingest.dropped_events > 0 ? (
              <li>
                {ingest.dropped_events} update(s) were dropped because this
                browser fell behind, so the newest state is shown rather than
                a backlog
              </li>
            ) : null}
          </ul>
        )}
        {failures.length > 0 ? (
          <ul className="notes__failures">
            {failures.map(([symbol, failure]) => (
              <li key={symbol}>
                {symbol}: {failure.category} at {formatStamp(failure.at)}:{" "}
                {failure.detail}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {meta.payload !== null ? (
        <section className="notes__block notes__meta">
          <h2>Contract</h2>
          <p>
            schema v{meta.payload.schema_version}, resolution{" "}
            {meta.payload.resolution}, as of {formatStamp(meta.payload.as_of)}
          </p>
        </section>
      ) : null}
    </aside>
  );
}
