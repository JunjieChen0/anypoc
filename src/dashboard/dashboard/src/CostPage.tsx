import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'

const CAW_VIEWER_PORT = import.meta.env.VITE_CAW_VIEWER_PORT as string | undefined
const PAGE_SIZE = 10

type PresetRange = 'today' | 'yesterday' | 'this_week' | 'last_week'
type DateTimeParts = { date: string; hour: string; minute: string }
type TimeField = 'modified' | 'created'
type ModelFilter = 'bedrock' | 'non_bedrock' | 'all'
type TimezoneMode = 'local' | 'utc'

function cawViewerUrl(trajAbsPath: string): string | null {
  if (!CAW_VIEWER_PORT) return null
  return `http://${window.location.hostname}:${CAW_VIEWER_PORT}/?local=${encodeURIComponent(trajAbsPath)}`
}

interface TaskStat {
  cost: number
  trajs: number
}

interface CostByTask {
  bugs: TaskStat
  pocs: TaskStat
}

interface ProjectCost {
  project: string
  bugs_cost: number
  pocs_cost: number
  total_cost: number
  total_trajs: number
}

interface TrajEntry {
  traj_path: string
  abs_path: string
  cost: number
  project: string
}

interface CostData {
  total_cost: number
  total_trajs: number
  time_field?: TimeField
  by_task: CostByTask
  by_project: ProjectCost[]
  top_trajs: TrajEntry[]
  page: number
  page_size: number
}

function pad2(value: number): string {
  return value.toString().padStart(2, '0')
}

function emptyDateTimeParts(): DateTimeParts {
  return { date: '', hour: '00', minute: '00' }
}

function dateToParts(date: Date, timezoneMode: TimezoneMode): DateTimeParts {
  return {
    date: timezoneMode === 'utc'
      ? `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())}`
      : `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`,
    hour: timezoneMode === 'utc' ? pad2(date.getUTCHours()) : pad2(date.getHours()),
    minute: timezoneMode === 'utc' ? pad2(date.getUTCMinutes()) : pad2(date.getMinutes()),
  }
}

function parseDateTimeParts(value: DateTimeParts): {
  year: number
  month: number
  day: number
  hour: number
  minute: number
} | null {
  if (!value.date) return null
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.date)
  if (!match) return null

  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  const hour = Number(value.hour)
  const minute = Number(value.minute)
  if (
    !Number.isInteger(year) ||
    !Number.isInteger(month) ||
    !Number.isInteger(day) ||
    !Number.isInteger(hour) ||
    !Number.isInteger(minute)
  ) {
    return null
  }
  if (month < 1 || month > 12 || day < 1 || day > 31 || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
    return null
  }

  return { year, month, day, hour, minute }
}

function partsToTimestamp(value: DateTimeParts, timezoneMode: TimezoneMode, endOfMinute = false): number | null {
  const parsed = parseDateTimeParts(value)
  if (!parsed) return null

  const seconds = endOfMinute ? 59 : 0
  const milliseconds = endOfMinute ? 999 : 0
  const { year, month, day, hour, minute } = parsed
  if (timezoneMode === 'utc') {
    return Date.UTC(year, month - 1, day, hour, minute, seconds, milliseconds)
  }

  const date = new Date(year, month - 1, day, hour, minute, seconds, milliseconds)
  if (Number.isNaN(date.getTime())) return null
  return date.getTime()
}

function partsToApiDateTime(value: DateTimeParts, timezoneMode: TimezoneMode, endOfMinute = false): string | null {
  const timestamp = partsToTimestamp(value, timezoneMode, endOfMinute)
  if (timestamp === null) return null
  return new Date(timestamp).toISOString()
}

function convertDateTimeParts(
  value: DateTimeParts,
  fromTimezoneMode: TimezoneMode,
  toTimezoneMode: TimezoneMode,
  endOfMinute = false
): DateTimeParts {
  if (!value.date || fromTimezoneMode === toTimezoneMode) return value
  const timestamp = partsToTimestamp(value, fromTimezoneMode, endOfMinute)
  if (timestamp === null) return value
  return dateToParts(new Date(timestamp), toTimezoneMode)
}

function startOfWeek(date: Date, timezoneMode: TimezoneMode): Date {
  const result = new Date(date)
  const day = timezoneMode === 'utc' ? result.getUTCDay() : result.getDay()
  if (timezoneMode === 'utc') {
    result.setUTCHours(0, 0, 0, 0)
    result.setUTCDate(result.getUTCDate() - day)
  } else {
    result.setHours(0, 0, 0, 0)
    result.setDate(result.getDate() - day)
  }
  return result
}

function presetRange(preset: PresetRange, timezoneMode: TimezoneMode): { start: DateTimeParts; end: DateTimeParts } {
  const now = new Date()
  if (timezoneMode === 'utc') {
    now.setUTCSeconds(0, 0)
  } else {
    now.setSeconds(0, 0)
  }

  if (preset === 'today') {
    const start = new Date(now)
    if (timezoneMode === 'utc') {
      start.setUTCHours(0, 0, 0, 0)
    } else {
      start.setHours(0, 0, 0, 0)
    }
    return { start: dateToParts(start, timezoneMode), end: dateToParts(now, timezoneMode) }
  }

  if (preset === 'yesterday') {
    const day = new Date(now)
    if (timezoneMode === 'utc') {
      day.setUTCDate(day.getUTCDate() - 1)
    } else {
      day.setDate(day.getDate() - 1)
    }
    const start = new Date(day)
    if (timezoneMode === 'utc') {
      start.setUTCHours(0, 0, 0, 0)
    } else {
      start.setHours(0, 0, 0, 0)
    }
    const end = new Date(day)
    if (timezoneMode === 'utc') {
      end.setUTCHours(23, 59, 0, 0)
    } else {
      end.setHours(23, 59, 0, 0)
    }
    return { start: dateToParts(start, timezoneMode), end: dateToParts(end, timezoneMode) }
  }

  if (preset === 'this_week') {
    const start = startOfWeek(now, timezoneMode)
    return { start: dateToParts(start, timezoneMode), end: dateToParts(now, timezoneMode) }
  }

  const thisWeekStart = startOfWeek(now, timezoneMode)
  const start = new Date(thisWeekStart)
  if (timezoneMode === 'utc') {
    start.setUTCDate(start.getUTCDate() - 7)
  } else {
    start.setDate(start.getDate() - 7)
  }
  const end = new Date(thisWeekStart)
  if (timezoneMode === 'utc') {
    end.setUTCMinutes(end.getUTCMinutes() - 1)
  } else {
    end.setMinutes(end.getMinutes() - 1)
  }
  return { start: dateToParts(start, timezoneMode), end: dateToParts(end, timezoneMode) }
}

function sameDateTimeParts(a: DateTimeParts, b: DateTimeParts): boolean {
  return a.date === b.date && a.hour === b.hour && a.minute === b.minute
}

function fmt(v: number): string {
  return `$${v.toFixed(2)}`
}

function avg(cost: number, count: number): string {
  if (count === 0) return '—'
  return fmt(cost / count)
}

export default function CostPage() {
  const [data, setData] = useState<CostData | null>(null)
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [draftStartTime, setDraftStartTime] = useState<DateTimeParts>(emptyDateTimeParts())
  const [draftEndTime, setDraftEndTime] = useState<DateTimeParts>(emptyDateTimeParts())
  const [appliedStartTime, setAppliedStartTime] = useState<DateTimeParts>(emptyDateTimeParts())
  const [appliedEndTime, setAppliedEndTime] = useState<DateTimeParts>(emptyDateTimeParts())
  const [draftTimeField, setDraftTimeField] = useState<TimeField>('modified')
  const [appliedTimeField, setAppliedTimeField] = useState<TimeField>('modified')
  const [timezoneMode, setTimezoneMode] = useState<TimezoneMode>('local')
  const [activePreset, setActivePreset] = useState<PresetRange | null>(null)
  const [modelFilter, setModelFilter] = useState<ModelFilter>('bedrock')

  const appliedStartIso = useMemo(
    () => partsToApiDateTime(appliedStartTime, timezoneMode, false),
    [appliedStartTime, timezoneMode]
  )
  const appliedEndIso = useMemo(
    () => partsToApiDateTime(appliedEndTime, timezoneMode, true),
    [appliedEndTime, timezoneMode]
  )
  const draftStartIso = useMemo(
    () => partsToApiDateTime(draftStartTime, timezoneMode, false),
    [draftStartTime, timezoneMode]
  )
  const draftEndIso = useMemo(
    () => partsToApiDateTime(draftEndTime, timezoneMode, true),
    [draftEndTime, timezoneMode]
  )
  const invalidDraftRange = useMemo(() => {
    if (!draftStartIso || !draftEndIso) return false
    return new Date(draftStartIso).getTime() > new Date(draftEndIso).getTime()
  }, [draftEndIso, draftStartIso])
  const hasPendingRangeChanges = useMemo(() => {
    return (
      !sameDateTimeParts(draftStartTime, appliedStartTime) ||
      !sameDateTimeParts(draftEndTime, appliedEndTime) ||
      draftTimeField !== appliedTimeField
    )
  }, [appliedEndTime, appliedStartTime, appliedTimeField, draftEndTime, draftStartTime, draftTimeField])

  useEffect(() => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(PAGE_SIZE),
    })
    if (appliedStartIso) params.set('start_time', appliedStartIso)
    if (appliedEndIso) params.set('end_time', appliedEndIso)
    params.set('time_field', appliedTimeField)
    params.set('model_filter', modelFilter)

    const controller = new AbortController()
    setLoading(true)
    fetch(`/api/costs?${params.toString()}`, { signal: controller.signal })
      .then(r => r.json())
      .then((d: CostData) => { setData(d); setLoading(false) })
      .catch((err: Error) => {
        if (err.name !== 'AbortError') setLoading(false)
      })
    return () => controller.abort()
  }, [appliedEndIso, appliedStartIso, appliedTimeField, modelFilter, page])

  const applyPreset = (preset: PresetRange) => {
    const range = presetRange(preset, timezoneMode)
    setDraftStartTime(range.start)
    setDraftEndTime(range.end)
    setAppliedStartTime(range.start)
    setAppliedEndTime(range.end)
    setAppliedTimeField(draftTimeField)
    setActivePreset(preset)
    setPage(1)
  }

  const applyRange = () => {
    if (invalidDraftRange) return
    setAppliedStartTime(draftStartTime)
    setAppliedEndTime(draftEndTime)
    setAppliedTimeField(draftTimeField)
    setPage(1)
  }

  const clearRange = () => {
    const empty = emptyDateTimeParts()
    setDraftStartTime(empty)
    setDraftEndTime(empty)
    setAppliedStartTime(empty)
    setAppliedEndTime(empty)
    setAppliedTimeField(draftTimeField)
    setActivePreset(null)
    setPage(1)
  }

  const updateDraftField = (
    setter: Dispatch<SetStateAction<DateTimeParts>>,
    field: keyof DateTimeParts,
    value: string
  ) => {
    setter(prev => ({ ...prev, [field]: value }))
    setActivePreset(null)
  }

  const applyTimezoneMode = (nextTimezoneMode: TimezoneMode) => {
    if (nextTimezoneMode === timezoneMode) return

    if (activePreset) {
      const range = presetRange(activePreset, nextTimezoneMode)
      setDraftStartTime(range.start)
      setDraftEndTime(range.end)
      setAppliedStartTime(range.start)
      setAppliedEndTime(range.end)
      setPage(1)
    } else {
      setDraftStartTime(prev => convertDateTimeParts(prev, timezoneMode, nextTimezoneMode))
      setDraftEndTime(prev => convertDateTimeParts(prev, timezoneMode, nextTimezoneMode, true))
      setAppliedStartTime(prev => convertDateTimeParts(prev, timezoneMode, nextTimezoneMode))
      setAppliedEndTime(prev => convertDateTimeParts(prev, timezoneMode, nextTimezoneMode, true))
    }

    setTimezoneMode(nextTimezoneMode)
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total_trajs / PAGE_SIZE)) : 1

  return (
    <div className="cost-page">
      <div className="cost-page-header">
        <a href="/" className="cost-back-link">← Back to Dashboard</a>
        <h1>Cost Overview</h1>
      </div>

      <div className="cost-filter-card">
        <div className="cost-filter-row">
          <label className="cost-filter-field">
            <span>Timestamp Type</span>
            <div className="cost-filter-time-switch" role="group" aria-label="timestamp type">
              <button
                type="button"
                className={`cost-filter-time-btn ${draftTimeField === 'modified' ? 'active' : ''}`}
                onClick={() => {
                  setDraftTimeField('modified')
                  setActivePreset(null)
                }}
              >
                Last Modified
              </button>
              <button
                type="button"
                className={`cost-filter-time-btn ${draftTimeField === 'created' ? 'active' : ''}`}
                onClick={() => {
                  setDraftTimeField('created')
                  setActivePreset(null)
                }}
              >
                Creation Time
              </button>
            </div>
          </label>
          <label className="cost-filter-field">
            <span>Timezone</span>
            <div className="cost-filter-time-switch" role="group" aria-label="timezone mode">
              <button
                type="button"
                className={`cost-filter-time-btn ${timezoneMode === 'local' ? 'active' : ''}`}
                onClick={() => applyTimezoneMode('local')}
              >
                Local
              </button>
              <button
                type="button"
                className={`cost-filter-time-btn ${timezoneMode === 'utc' ? 'active' : ''}`}
                onClick={() => applyTimezoneMode('utc')}
              >
                UTC
              </button>
            </div>
          </label>
          <label className="cost-filter-field">
            <span>Provider</span>
            <div className="cost-filter-time-switch" role="group" aria-label="model filter">
              <button
                type="button"
                className={`cost-filter-time-btn ${modelFilter === 'bedrock' ? 'active' : ''}`}
                onClick={() => { setModelFilter('bedrock'); setPage(1) }}
              >
                Bedrock
              </button>
              <button
                type="button"
                className={`cost-filter-time-btn ${modelFilter === 'non_bedrock' ? 'active' : ''}`}
                onClick={() => { setModelFilter('non_bedrock'); setPage(1) }}
              >
                Non-Bedrock
              </button>
              <button
                type="button"
                className={`cost-filter-time-btn ${modelFilter === 'all' ? 'active' : ''}`}
                onClick={() => { setModelFilter('all'); setPage(1) }}
              >
                All
              </button>
            </div>
          </label>
          <label className="cost-filter-field">
            <span>Start Time</span>
            <div className="cost-filter-datetime">
              <input
                type="date"
                value={draftStartTime.date}
                onChange={e => updateDraftField(setDraftStartTime, 'date', e.target.value)}
              />
              <select
                value={draftStartTime.hour}
                onChange={e => updateDraftField(setDraftStartTime, 'hour', e.target.value)}
                disabled={!draftStartTime.date}
              >
                {Array.from({ length: 24 }, (_, hour) => {
                  const value = pad2(hour)
                  return (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  )
                })}
              </select>
              <span>:</span>
              <select
                value={draftStartTime.minute}
                onChange={e => updateDraftField(setDraftStartTime, 'minute', e.target.value)}
                disabled={!draftStartTime.date}
              >
                {Array.from({ length: 60 }, (_, minute) => {
                  const value = pad2(minute)
                  return (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  )
                })}
              </select>
            </div>
          </label>
          <label className="cost-filter-field">
            <span>End Time</span>
            <div className="cost-filter-datetime">
              <input
                type="date"
                value={draftEndTime.date}
                onChange={e => updateDraftField(setDraftEndTime, 'date', e.target.value)}
              />
              <select
                value={draftEndTime.hour}
                onChange={e => updateDraftField(setDraftEndTime, 'hour', e.target.value)}
                disabled={!draftEndTime.date}
              >
                {Array.from({ length: 24 }, (_, hour) => {
                  const value = pad2(hour)
                  return (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  )
                })}
              </select>
              <span>:</span>
              <select
                value={draftEndTime.minute}
                onChange={e => updateDraftField(setDraftEndTime, 'minute', e.target.value)}
                disabled={!draftEndTime.date}
              >
                {Array.from({ length: 60 }, (_, minute) => {
                  const value = pad2(minute)
                  return (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  )
                })}
              </select>
            </div>
          </label>
          <button
            className="cost-filter-apply-btn"
            onClick={applyRange}
            disabled={!hasPendingRangeChanges || invalidDraftRange}
          >
            Apply Range
          </button>
          <button
            className="cost-filter-clear-btn"
            onClick={clearRange}
            disabled={!draftStartTime.date && !draftEndTime.date && !appliedStartTime.date && !appliedEndTime.date}
          >
            Show All
          </button>
        </div>
        <div className="cost-filter-presets">
          <span className="cost-filter-presets-label">Quick Ranges:</span>
          <button
            className={`cost-filter-preset-btn ${activePreset === 'today' ? 'active' : ''}`}
            onClick={() => applyPreset('today')}
          >
            Today
          </button>
          <button
            className={`cost-filter-preset-btn ${activePreset === 'yesterday' ? 'active' : ''}`}
            onClick={() => applyPreset('yesterday')}
          >
            Yesterday
          </button>
          <button
            className={`cost-filter-preset-btn ${activePreset === 'this_week' ? 'active' : ''}`}
            onClick={() => applyPreset('this_week')}
          >
            This Week
          </button>
          <button
            className={`cost-filter-preset-btn ${activePreset === 'last_week' ? 'active' : ''}`}
            onClick={() => applyPreset('last_week')}
          >
            Last Week
          </button>
        </div>
        <div className="cost-filter-note">
          Filter uses traj file {appliedTimeField === 'created' ? 'creation time' : 'last modified time'}.
        </div>
        <div className="cost-filter-note">
          Date inputs and quick ranges use {timezoneMode === 'utc' ? 'UTC' : 'your browser local timezone'}.
        </div>
        {appliedTimeField === 'created' && (
          <div className="cost-filter-note">
            Creation time uses filesystem birth time when available; otherwise it falls back to metadata change time.
          </div>
        )}
        {invalidDraftRange && <div className="cost-filter-error">Start time must be before or equal to end time.</div>}
      </div>

      {loading && <div className="cost-loading">Loading...</div>}

      {!loading && data && (
        <>
          {/* Total cost */}
          <div className="cost-section">
            <div className="cost-total-card">
              <div className="cost-total-label">Total Cost (All Projects)</div>
              <div className="cost-total-value">{fmt(data.total_cost)}</div>
              <div className="cost-total-avg">
                avg {avg(data.total_cost, data.total_trajs)} / traj
                <span className="cost-total-count"> ({data.total_trajs} trajs)</span>
              </div>
            </div>
          </div>

          {/* By task */}
          <div className="cost-section">
            <h2>Cost by Task</h2>
            <table className="cost-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th style={{ textAlign: 'right' }}>Trajs</th>
                  <th style={{ textAlign: 'right' }}>Total Cost</th>
                  <th style={{ textAlign: 'right' }}>Avg / Traj</th>
                </tr>
              </thead>
              <tbody>
                {(['bugs', 'pocs'] as const).map(task => {
                  const s = data.by_task[task]
                  return (
                    <tr key={task}>
                      <td className="cost-task-name">{task.charAt(0).toUpperCase() + task.slice(1)}</td>
                      <td className="cost-value cost-count-col">{s.trajs}</td>
                      <td className="cost-value">{fmt(s.cost)}</td>
                      <td className="cost-value cost-avg-col">{avg(s.cost, s.trajs)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* By project */}
          <div className="cost-section">
            <h2>Cost by Project</h2>
            <table className="cost-table">
              <thead>
                <tr>
                  <th>Project</th>
                  <th style={{ textAlign: 'right' }}>Bugs</th>
                  <th style={{ textAlign: 'right' }}>PoCs</th>
                  <th style={{ textAlign: 'right' }}>Total</th>
                  <th style={{ textAlign: 'right' }}>Avg / Traj</th>
                </tr>
              </thead>
              <tbody>
                {data.by_project.map(p => (
                  <tr key={p.project}>
                    <td className="cost-project-name">{p.project}</td>
                    <td className="cost-value">{fmt(p.bugs_cost)}</td>
                    <td className="cost-value">{fmt(p.pocs_cost)}</td>
                    <td className="cost-value cost-total-col">{fmt(p.total_cost)}</td>
                    <td className="cost-value cost-avg-col">{avg(p.total_cost, p.total_trajs)}</td>
                  </tr>
                ))}
                {data.by_project.length === 0 && (
                  <tr><td colSpan={5} className="cost-empty">No cost data found</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Top costly trajs */}
          <div className="cost-section">
            <h2>
              Top Costly Trajectories
              <span className="cost-count"> ({data.total_trajs} total)</span>
            </h2>
            <table className="cost-table">
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Trajectory</th>
                  <th>Links</th>
                  <th style={{ textAlign: 'right' }}>Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.top_trajs.map((t, i) => {
                  const cawUrl = cawViewerUrl(t.abs_path)
                  return (
                    <tr key={i}>
                      <td className="cost-project-name">{t.project}</td>
                      <td className="cost-traj-path">{t.traj_path}</td>
                      <td className="cost-traj-links">
                        {cawUrl && (
                          <a href={cawUrl} target="_blank" rel="noreferrer" className="cost-link">Traj Viewer</a>
                        )}
                      </td>
                      <td className="cost-value">{fmt(t.cost)}</td>
                    </tr>
                  )
                })}
                {data.top_trajs.length === 0 && (
                  <tr><td colSpan={4} className="cost-empty">No trajectories found</td></tr>
                )}
              </tbody>
            </table>

            {/* Pagination */}
            <div className="cost-pagination">
              <button
                className="cost-page-btn"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page <= 1}
              >
                ← Prev
              </button>
              <span className="cost-page-info">Page {page} of {totalPages}</span>
              <button
                className="cost-page-btn"
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
              >
                Next →
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
