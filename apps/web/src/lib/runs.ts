import { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { z } from 'zod';

import { api } from './api';
import { EPISODES_KEY } from './episodes';
import { SHOWS_KEY } from './shows';

export const RUN_STATUSES = [
  'queued',
  'running',
  'awaiting_review',
  'succeeded',
  'failed',
  'cancelled',
] as const;
export type RunStatus = (typeof RUN_STATUSES)[number];

export const runSchema = z.object({
  id: z.string(),
  show_id: z.string(),
  trigger: z.enum(['manual', 'schedule', 'resynth']),
  status: z.enum(RUN_STATUSES),
  stage: z.string().nullable(),
  progress: z.number(),
  error: z.string().nullable(),
  cancel_requested: z.boolean(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  created_at: z.string(),
  episode_id: z.string().nullable().default(null),
});
export type Run = z.infer<typeof runSchema>;

export const runEventSchema = z.object({
  id: z.string(),
  ts: z.string(),
  level: z.enum(['info', 'warning', 'error']),
  stage: z.string().nullable(),
  message: z.string(),
  data: z.record(z.string(), z.unknown()).nullable(),
});
export type RunEvent = z.infer<typeof runEventSchema>;

export const runDetailSchema = runSchema.extend({ events: z.array(runEventSchema) });
export type RunDetail = z.infer<typeof runDetailSchema>;

/** The stages of a generation run, in order, as the timeline shows them. */
export const RUN_STAGES = [
  { id: 'ingest', label: 'Collect stories' },
  { id: 'rank', label: 'Pick stories' },
  { id: 'script', label: 'Write script' },
  { id: 'tts', label: 'Voice' },
  { id: 'mix', label: 'Mix audio' },
  { id: 'finalize', label: 'Publish' },
] as const;
/** A re-synthesis only redoes these (the stories and script are already there). */
export const RESYNTH_STAGE_IDS: readonly string[] = ['tts', 'mix', 'finalize'];

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  queued: 'Queued',
  running: 'Running',
  awaiting_review: 'Needs review',
  succeeded: 'Succeeded',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

/** Queued or working: the run will still change. */
export function isActive(status: string | null | undefined): boolean {
  return status === 'queued' || status === 'running';
}

export const STATUS_VARIANT: Record<RunStatus, string> = {
  queued: 'secondary',
  running: 'info',
  awaiting_review: 'warning',
  succeeded: 'success',
  failed: 'danger',
  cancelled: 'secondary',
};

export type StageState = 'done' | 'active' | 'failed' | 'cancelled' | 'pending' | 'skipped';

export type StageRow = { id: string; label: string; state: StageState; seconds: number | null };

function secondsBetween(from: string, to: string | number): number {
  return Math.max(0, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 1000));
}

/** "850 ms" is noise here: whole seconds, then "1m 05s". */
export function formatSeconds(seconds: number | null): string {
  if (seconds === null) return '';
  if (seconds < 60) return `${String(seconds)}s`;
  const m = Math.floor(seconds / 60);
  return `${String(m)}m ${String(seconds % 60).padStart(2, '0')}s`;
}

/** Where each stage stands and how long it took, worked out from the run and its log. */
export function stageRows(run: RunDetail, now: number): StageRow[] {
  const ended = !isActive(run.status);
  const currentIndex = RUN_STAGES.findIndex((s) => s.id === run.stage);
  return RUN_STAGES.map((stage, index): StageRow => {
    const { id, label } = stage;
    const skipped = run.trigger === 'resynth' && !RESYNTH_STAGE_IDS.includes(id);
    if (skipped) return { id, label, state: 'skipped', seconds: null };

    const started = run.events.find((e) => e.stage === id && e.message === `Started ${id}`);
    const finished = run.events.find((e) => e.stage === id && e.message === `Finished ${id}`);
    const isCurrent = index === currentIndex;
    let state: StageState = 'pending';
    if (finished || (currentIndex > index && started)) state = 'done';
    else if (isCurrent) {
      if (!ended) state = 'active';
      else if (run.status === 'failed') state = 'failed';
      else if (run.status === 'cancelled') state = 'cancelled';
      else state = 'done'; // the last stage ends the run without a "Finished" line
    }
    let seconds: number | null = null;
    if (started) {
      const end = finished?.ts ?? (isCurrent ? (run.finished_at ?? (ended ? null : now)) : null);
      if (end !== null) seconds = secondsBetween(started.ts, end);
    }
    return { id, label, state, seconds };
  });
}

export const RUNS_KEY = ['runs'] as const;
const POLL_MS = 2000;

const runKey = (runId: string) => [...RUNS_KEY, runId] as const;
export const showRunsKey = (showId: string) => [...SHOWS_KEY, showId, 'runs'] as const;

/** The run and its log; polls while it is active unless the live stream is delivering. */
export function useRun(runId: string, live: boolean) {
  return useQuery({
    queryKey: runKey(runId),
    queryFn: () => api.get<RunDetail>(`/runs/${runId}`, { schema: runDetailSchema }),
    refetchInterval: (query) => (!live && isActive(query.state.data?.status) ? POLL_MS : false),
  });
}

export function useShowRuns(showId: string) {
  return useQuery({
    queryKey: showRunsKey(showId),
    queryFn: () =>
      api.get<Run[]>('/runs', {
        query: { show_id: showId, limit: 50 },
        schema: z.array(runSchema),
      }),
    refetchInterval: (query) =>
      query.state.data?.some((r) => isActive(r.status)) ? POLL_MS : false,
  });
}

function useRefreshAfterRun() {
  const queryClient = useQueryClient();
  return (showId: string) => {
    void queryClient.invalidateQueries({ queryKey: SHOWS_KEY });
    void queryClient.invalidateQueries({ queryKey: EPISODES_KEY });
    void queryClient.invalidateQueries({ queryKey: showRunsKey(showId) });
  };
}

export function useStartRun(showId: string) {
  const refresh = useRefreshAfterRun();
  return useMutation({
    mutationFn: () => api.post<Run>(`/shows/${showId}/runs`, undefined, { schema: runSchema }),
    onSuccess: () => refresh(showId),
  });
}

export function useCancelRun(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post<RunDetail>(`/runs/${runId}/cancel`, undefined, { schema: runDetailSchema }),
    onSuccess: (run) => queryClient.setQueryData(runKey(runId), run),
  });
}

const streamSchema = z.object({ run: runSchema, events: z.array(runEventSchema) });

/** Merge one stream message into the cached run: `snapshot` replaces the log, `update` extends it. */
function applyMessage(
  previous: RunDetail | undefined,
  message: z.infer<typeof streamSchema>,
  replace: boolean,
): RunDetail {
  const known = replace || !previous ? [] : previous.events;
  const seen = new Set(known.map((e) => e.id));
  return { ...message.run, events: [...known, ...message.events.filter((e) => !seen.has(e.id))] };
}

/**
 * The run and its log, followed live over Server-Sent Events.
 *
 * `connected` says whether the stream is currently delivering. When it is not (no `EventSource`,
 * a dropped connection, a proxy that cuts it) the query polls instead; the browser reconnects by
 * itself and the server then sends the current state again, so nothing is lost. `onFinished`
 * runs once when a run that was active while watched reaches a final state.
 */
export function useLiveRun(runId: string, onFinished: (run: Run) => void) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  const run = useRun(runId, connected);
  // Read through a ref so a new callback each render does not drop the connection.
  const finished = useRef(onFinished);
  useEffect(() => {
    finished.current = onFinished;
  });

  useEffect(() => {
    if (typeof EventSource === 'undefined') return;
    const source = new EventSource(`/api/runs/${runId}/stream`, { withCredentials: true });
    let latest: Run | null = null;
    let sawActive = false;

    const handle = (replace: boolean) => (event: MessageEvent<string>) => {
      let parsed: z.infer<typeof streamSchema>;
      try {
        parsed = streamSchema.parse(JSON.parse(event.data));
      } catch {
        return; // a malformed message: keep the last good state, polling will catch up
      }
      latest = parsed.run;
      sawActive ||= isActive(parsed.run.status);
      setConnected(true);
      queryClient.setQueryData<RunDetail>(runKey(runId), (previous) =>
        applyMessage(previous, parsed, replace),
      );
    };
    source.addEventListener('snapshot', handle(true) as EventListener);
    source.addEventListener('update', handle(false) as EventListener);
    source.addEventListener('done', () => {
      source.close();
      setConnected(false);
      if (latest && sawActive) finished.current(latest);
    });
    source.addEventListener('gone', () => {
      source.close();
      setConnected(false);
    });
    source.onerror = () => {
      setConnected(false); // poll until the browser has reconnected
    };
    return () => {
      source.close();
      setConnected(false);
    };
  }, [runId, queryClient]);

  return { run, connected };
}
