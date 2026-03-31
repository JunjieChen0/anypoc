import { useCallback, useEffect, useRef, useState } from 'react'

// CAW trajectory viewer URL builder (port injected by Vite env)
const CAW_VIEWER_PORT = import.meta.env.VITE_CAW_VIEWER_PORT as string | undefined
function cawViewerUrl(trajAbsPath: string): string | null {
  if (!CAW_VIEWER_PORT) return null
  return `http://${window.location.hostname}:${CAW_VIEWER_PORT}/?local=${encodeURIComponent(trajAbsPath)}`
}

// URL state management hook
function useUrlState() {
  const getProjectFromUrl = () => {
    const path = window.location.pathname
    const match = path.match(/^\/(.+)$/)
    return match ? decodeURIComponent(match[1]) : null
  }

  const getPanelsFromUrl = (): Set<string> => {
    const params = new URLSearchParams(window.location.search)
    const panels = params.get('panels')
    return panels ? new Set(panels.split(',')) : new Set()
  }

  const getMonitorStateFromUrl = () => {
    const params = new URLSearchParams(window.location.search)
    return {
      tab: params.get('tab') as 'bugs' | 'pocs' | null,
      item: params.get('item')
    }
  }

  const getKnowledgeItemFromUrl = () => {
    const params = new URLSearchParams(window.location.search)
    const item = params.get('knowledge_item')
    return item ? decodeURIComponent(item) : null
  }

  const [selectedProject, setSelectedProjectState] = useState<string | null>(getProjectFromUrl)
  const [expandedPanels, setExpandedPanelsState] = useState<Set<string>>(getPanelsFromUrl)
  const [monitorTab, setMonitorTabState] = useState<'bugs' | 'pocs' | null>(getMonitorStateFromUrl().tab)
  const [monitorItem, setMonitorItemState] = useState<string | null>(getMonitorStateFromUrl().item)
  const [knowledgeItem, setKnowledgeItemState] = useState<string | null>(getKnowledgeItemFromUrl)

  const updateUrl = useCallback((
    project: string | null,
    panels: Set<string>,
    tab: string | null,
    item: string | null
  ) => {
    const path = project ? `/${encodeURIComponent(project)}` : '/'
    const params = new URLSearchParams()
    if (panels.size > 0) params.set('panels', Array.from(panels).join(','))
    if (tab) params.set('tab', tab)
    if (item) params.set('item', item)
    const queryString = params.toString()
    const newUrl = path + (queryString ? `?${queryString}` : '')
    window.history.pushState({}, '', newUrl)
  }, [])

  const setSelectedProject = useCallback((project: string | null) => {
    setSelectedProjectState(project)
    // Clear monitor selection when changing project
    setMonitorTabState(null)
    setMonitorItemState(null)
    setExpandedPanelsState(prev => {
      updateUrl(project, prev, null, null)
      return prev
    })
  }, [updateUrl])

  const togglePanel = useCallback((panel: string) => {
    setExpandedPanelsState(prev => {
      const next = new Set(prev)
      if (next.has(panel)) {
        next.delete(panel)
      } else {
        next.add(panel)
      }
      setSelectedProjectState(proj => {
        setMonitorTabState(tab => {
          setMonitorItemState(item => {
            updateUrl(proj, next, tab, item)
            return item
          })
          return tab
        })
        return proj
      })
      return next
    })
  }, [updateUrl])

  const isPanelExpanded = useCallback((panel: string) => {
    return expandedPanels.has(panel)
  }, [expandedPanels])

  const setMonitorState = useCallback((tab: 'bugs' | 'pocs', item: string | null) => {
    setMonitorTabState(tab)
    setMonitorItemState(item)
    setSelectedProjectState(proj => {
      setExpandedPanelsState(panels => {
        updateUrl(proj, panels, tab, item)
        return panels
      })
      return proj
    })
  }, [updateUrl])

  // Handle browser back/forward
  useEffect(() => {
    const handlePopState = () => {
      setSelectedProjectState(getProjectFromUrl())
      setExpandedPanelsState(getPanelsFromUrl())
      const { tab, item } = getMonitorStateFromUrl()
      setMonitorTabState(tab)
      setMonitorItemState(item)
      setKnowledgeItemState(getKnowledgeItemFromUrl())
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  return {
    selectedProject,
    setSelectedProject,
    togglePanel,
    isPanelExpanded,
    monitorTab,
    monitorItem,
    setMonitorState,
    knowledgeItem,
    clearKnowledgeItem: useCallback(() => {
      setKnowledgeItemState(null)
      // Also remove from URL
      const params = new URLSearchParams(window.location.search)
      params.delete('knowledge_item')
      const queryString = params.toString()
      const newUrl = window.location.pathname + (queryString ? `?${queryString}` : '')
      window.history.replaceState({}, '', newUrl)
    }, [])
  }
}

interface Project {
  name: string
}

// Monitor types
interface MonitorSummary {
  exists: boolean
  bugs: number
  bugs_cost_usd: number
  pocs: number
  pocs_complete: number
  pocs_cost_usd: number
}

interface TrajFile {
  name: string
  absolute_path: string
}

interface BugItem {
  name: string
}

interface BugDetail {
  name: string
  scan_id: string
  strategy: string
  title: string
  metadata: Record<string, string>
  markdown_path: string
  markdown_name: string
  markdown_html: string
}

interface PocItem {
  name: string
  color: string
  is_complete: boolean
  total_cost_usd: number
  analysis_status: string
  generation_status: string
  evidence_status: string
  annotation_status: string
}

interface PocStep {
  name: string
  status: string
  timestamp: string
  cost_usd: number | null
  traj_path: string | null
}

interface FileTreeNode {
  name: string
  path: string
  is_dir: boolean
  size?: number
  children?: FileTreeNode[]
}

interface PocAttempt {
  number: number
  cost_usd: number
  color: string
}

// Knowledge usage/extraction types for PoC detail
interface KnowledgeRating {
  file_path: string
  score: number
}

interface KnowledgeUsageInfo {
  ratings: KnowledgeRating[]
}

interface KnowledgeExtractionInfo {
  reported: string[]
  updated: string[]
  ratings: KnowledgeRating[]
}

interface PocDetail {
  name: string
  color: string
  is_complete: boolean
  total_cost_usd: number
  attempts: PocAttempt[]
  selected_attempt: number | null
  steps: PocStep[]
  file_tree: FileTreeNode[]
  input_files: FileTreeNode[]
  scan_id: string | null
  bug_strategy: string | null
  knowledge_usage: KnowledgeUsageInfo | null
  knowledge_extraction: KnowledgeExtractionInfo | null
  annotation_status: string
  annotation_notes: string
}

// Knowledge types
interface KnowledgeSummary {
  exists: boolean
  total_entries: number
  categories_count: number
  avg_rating: number | null
  entries_by_category: Record<string, number>
  top_keywords: Array<{ keyword: string; count: number }>
  version_distribution: Record<string, number>
}

interface KnowledgeEntryItem {
  file_path: string
  name: string
  category_path: string[]
  keywords: string[]
  version: number
  avg_rating: number | null
  iterations_survived: number
  updated_at: string
}

interface KnowledgeEntryDetail {
  file_path: string
  name: string
  category_path: string[]
  knowledge_type: string
  keywords: string[]
  content: string
  content_html: string
  version: number
  avg_rating: number | null
  all_ratings: number[]
  iterations_survived: number
  source_generations: string[]
  source_success_flags: boolean[]
  created_at: string
  updated_at: string
}

// ---------------------------------------------------------------------------
// Spend-limit widget (always visible at the top of main content)
// ---------------------------------------------------------------------------

interface SpendLimitData {
  overall_limit: number | null
  overall_total_cost: number
  projects: {
    name: string
    limit: number | null
    total_cost: number
    tasks: Record<string, { total_cost: number; count: number }>
  }[]
}

function SpendLimitWidget() {
  const [data, setData] = useState<SpendLimitData | null>(null)
  const [collapsed, setCollapsed] = useState(true)
  const [editingOverall, setEditingOverall] = useState(false)
  const [overallDraft, setOverallDraft] = useState('')
  const [editingProject, setEditingProject] = useState<string | null>(null)
  const [projectDraft, setProjectDraft] = useState('')

  const fetchData = useCallback(() => {
    fetch('/api/spend-limits')
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => {})
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  const pct = (spent: number, limit: number | null) =>
    limit && limit > 0 ? Math.min((spent / limit) * 100, 100) : 0

  const barClass = (p: number) =>
    p >= 90 ? 'sl-bar-fill sl-bar-danger' : p >= 70 ? 'sl-bar-fill sl-bar-warn' : 'sl-bar-fill'

  // ---- mutations ----------------------------------------------------------
  const setOverallLimit = () => {
    const v = parseFloat(overallDraft)
    if (isNaN(v) || v <= 0) return
    fetch('/api/spend-limits/overall', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: v }),
    }).then(() => { setEditingOverall(false); fetchData() })
  }

  const clearOverallLimit = () => {
    fetch('/api/spend-limits/overall', { method: 'DELETE' })
      .then(() => { setEditingOverall(false); fetchData() })
  }

  const setProjectLimit = (project: string) => {
    const v = parseFloat(projectDraft)
    if (isNaN(v) || v <= 0) return
    fetch(`/api/spend-limits/project/${encodeURIComponent(project)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: v }),
    }).then(() => { setEditingProject(null); fetchData() })
  }

  const clearProjectLimit = (project: string) => {
    fetch(`/api/spend-limits/project/${encodeURIComponent(project)}`, { method: 'DELETE' })
      .then(() => { setEditingProject(null); fetchData() })
  }

  if (!data) return null

  const hasAnyLimit = data.overall_limit !== null || data.projects.some(p => p.limit !== null)
  const overallPct = pct(data.overall_total_cost, data.overall_limit)

  // Projects that have a limit, non-zero spend, or are currently being edited
  const relevantProjects = data.projects.filter(
    p => p.limit !== null || p.total_cost > 0 || editingProject === p.name
  )

  return (
    <div className="sl-widget">
      <div className="sl-header" onClick={() => setCollapsed(!collapsed)}>
        <span className="toggle">{collapsed ? '\u25B6' : '\u25BC'}</span>
        <span className="sl-title">Spend Limits</span>
        {!collapsed ? null : hasAnyLimit ? (
          <span className="sl-summary">
            {data.overall_limit !== null && (
              <span className={overallPct >= 90 ? 'sl-tag sl-tag-danger' : 'sl-tag'}>
                Overall: ${data.overall_total_cost.toFixed(2)} / ${data.overall_limit.toFixed(2)}
              </span>
            )}
          </span>
        ) : (
          <span className="sl-summary"><span className="sl-tag sl-tag-dim">no limits set</span></span>
        )}
      </div>

      {!collapsed && (
        <div className="sl-body">
          {/* Overall */}
          <div className="sl-row">
            <div className="sl-row-label">
              <strong>Overall</strong>
              {!editingOverall && (
                <button className="sl-edit-btn" onClick={() => { setEditingOverall(true); setOverallDraft(data.overall_limit?.toString() ?? '') }}>edit</button>
              )}
            </div>
            {editingOverall ? (
              <div className="sl-edit-row">
                <span className="sl-spent">${data.overall_total_cost.toFixed(2)} spent</span>
                <input
                  className="sl-input"
                  type="number"
                  step="0.01"
                  min="0"
                  placeholder="limit $"
                  value={overallDraft}
                  onChange={e => setOverallDraft(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && setOverallLimit()}
                  autoFocus
                />
                <button className="sl-btn sl-btn-primary" onClick={setOverallLimit}>Set</button>
                {data.overall_limit !== null && <button className="sl-btn sl-btn-danger" onClick={clearOverallLimit}>Clear</button>}
                <button className="sl-btn" onClick={() => setEditingOverall(false)}>Cancel</button>
              </div>
            ) : (
              <div className="sl-row-value">
                {data.overall_limit !== null ? (
                  <>
                    <div className="sl-bar"><div className={barClass(overallPct)} style={{ width: `${overallPct}%` }} /></div>
                    <span className="sl-numbers">${data.overall_total_cost.toFixed(2)} / ${data.overall_limit.toFixed(2)}</span>
                  </>
                ) : (
                  <span className="sl-dim">${data.overall_total_cost.toFixed(2)} spent &mdash; no limit</span>
                )}
              </div>
            )}
          </div>

          {/* Per-project */}
          {relevantProjects.length > 0 && (
            <div className="sl-projects">
              {relevantProjects.map(p => {
                const pp = pct(p.total_cost, p.limit)
                const isEditing = editingProject === p.name
                return (
                  <div key={p.name} className="sl-row">
                    <div className="sl-row-label">
                      {p.name}
                      {!isEditing && (
                        <button className="sl-edit-btn" onClick={() => { setEditingProject(p.name); setProjectDraft(p.limit?.toString() ?? '') }}>edit</button>
                      )}
                    </div>
                    {isEditing ? (
                      <div className="sl-edit-row">
                        <span className="sl-spent">${p.total_cost.toFixed(2)} spent</span>
                        <input
                          className="sl-input"
                          type="number"
                          step="0.01"
                          min="0"
                          placeholder="limit $"
                          value={projectDraft}
                          onChange={e => setProjectDraft(e.target.value)}
                          onKeyDown={e => e.key === 'Enter' && setProjectLimit(p.name)}
                          autoFocus
                        />
                        <button className="sl-btn sl-btn-primary" onClick={() => setProjectLimit(p.name)}>Set</button>
                        {p.limit !== null && <button className="sl-btn sl-btn-danger" onClick={() => clearProjectLimit(p.name)}>Clear</button>}
                        <button className="sl-btn" onClick={() => setEditingProject(null)}>Cancel</button>
                      </div>
                    ) : (
                      <div className="sl-row-value">
                        {p.limit !== null ? (
                          <>
                            <div className="sl-bar"><div className={barClass(pp)} style={{ width: `${pp}%` }} /></div>
                            <span className="sl-numbers">${p.total_cost.toFixed(2)} / ${p.limit.toFixed(2)}</span>
                          </>
                        ) : (
                          <span className="sl-dim">${p.total_cost.toFixed(2)} spent</span>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {/* Add limit for any project */}
          {data.projects.filter(p => p.limit === null).length > 0 && (
            <div className="sl-add-project">
              <select
                className="sl-select"
                value=""
                onChange={e => {
                  if (e.target.value) {
                    setEditingProject(e.target.value)
                    setProjectDraft('')
                  }
                }}
              >
                <option value="">+ Add project limit...</option>
                {data.projects.filter(p => p.limit === null && editingProject !== p.name).map(p => (
                  <option key={p.name} value={p.name}>{p.name}</option>
                ))}
              </select>
            </div>
          )}
        </div>
      )}
    </div>
  )
}


function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const { selectedProject, setSelectedProject, togglePanel, isPanelExpanded, monitorTab, monitorItem, setMonitorState, knowledgeItem, clearKnowledgeItem } = useUrlState()
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const [copiedCmd, setCopiedCmd] = useState<string | null>(null)
  const [cawProvider, setCawProvider] = useState('')
  const [cawModel, setCawModel] = useState('')
  const [cawEffort, setCawEffort] = useState('')
  const [modelsConfig, setModelsConfig] = useState<CawModelsConfig>({ providers: {} })
  const [outputDir, setOutputDir] = useState('output')
  const [outputBasePath, setOutputBasePath] = useState('')
  const [hiddenProjects, setHiddenProjects] = useState<Set<string>>(new Set())
  const [projectOrder, setProjectOrder] = useState<string[]>([])
  const [showHidden, setShowHidden] = useState(false)
  const [draggedProject, setDraggedProject] = useState<string | null>(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    const saved = localStorage.getItem('sidebarCollapsed')
    return saved === 'true'
  })
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('theme') as 'dark' | 'light') || 'light'
  })

  useEffect(() => {
    localStorage.setItem('sidebarCollapsed', String(sidebarCollapsed))
  }, [sidebarCollapsed])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('theme', theme)
  }, [theme])

  useEffect(() => {
    // Fetch config, projects, dashboard config, and models config in parallel
    Promise.all([
      fetch('/api/config').then(res => res.json()),
      fetch('/api/projects').then(res => res.json()),
      fetch('/api/dashboard-config').then(res => res.json()),
      fetch('/api/models').then(res => res.json())
    ])
      .then(([config, projectsData, dashConfig, models]) => {
        setOutputDir(config.output_dir || 'output')
        setOutputBasePath(config.output_base_path || '')
        setProjects(projectsData.projects || [])
        setHiddenProjects(new Set(dashConfig.hidden_projects || []))
        setProjectOrder(dashConfig.project_order || [])
        setModelsConfig(models?.providers ? models : { providers: {} })
        setLoading(false)
      })
      .catch(err => {
        console.error('Failed to fetch:', err)
        setLoading(false)
      })
  }, [])

  const saveDashboardConfig = useCallback((hidden: Set<string>, order: string[]) => {
    fetch('/api/dashboard-config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hidden_projects: [...hidden], project_order: order })
    }).catch(err => console.error('Failed to save dashboard config:', err))
  }, [])

  const toggleHideProject = useCallback((name: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setHiddenProjects(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      saveDashboardConfig(next, projectOrder)
      return next
    })
  }, [projectOrder, saveDashboardConfig])

  const sortedProjects = (() => {
    const ordered: Project[] = []
    const remaining = [...projects]
    for (const name of projectOrder) {
      const idx = remaining.findIndex(p => p.name === name)
      if (idx !== -1) {
        ordered.push(remaining.splice(idx, 1)[0])
      }
    }
    return [...ordered, ...remaining]
  })()

  const filteredProjects = sortedProjects.filter(p => {
    if (!showHidden && hiddenProjects.has(p.name)) return false
    return p.name.toLowerCase().includes(filter.toLowerCase())
  })

  const hiddenCount = projects.filter(p => hiddenProjects.has(p.name)).length

  const handleDragStart = (name: string) => {
    setDraggedProject(name)
  }

  const handleDragOver = (e: React.DragEvent, targetName: string) => {
    e.preventDefault()
    if (draggedProject && draggedProject !== targetName) {
      e.currentTarget.classList.add('drag-over')
    }
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.currentTarget.classList.remove('drag-over')
  }

  const handleDrop = (e: React.DragEvent, targetName: string) => {
    e.preventDefault()
    e.currentTarget.classList.remove('drag-over')
    if (!draggedProject || draggedProject === targetName) return

    // Build full order from current sortedProjects, then move dragged to target position
    const names = sortedProjects.map(p => p.name)
    const fromIdx = names.indexOf(draggedProject)
    const toIdx = names.indexOf(targetName)
    if (fromIdx === -1 || toIdx === -1) return
    names.splice(fromIdx, 1)
    names.splice(toIdx, 0, draggedProject)
    setProjectOrder(names)
    setDraggedProject(null)
    saveDashboardConfig(hiddenProjects, names)
  }

  const handleDragEnd = () => {
    setDraggedProject(null)
  }

  const copyToClipboard = async (text: string) => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text)
      } else {
        const textArea = document.createElement('textarea')
        textArea.value = text
        textArea.style.position = 'fixed'
        textArea.style.left = '-999999px'
        document.body.appendChild(textArea)
        textArea.select()
        document.execCommand('copy')
        document.body.removeChild(textArea)
      }
      setCopiedCmd(text)
      setTimeout(() => setCopiedCmd(null), 1500)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  return (
    <div className="app">
      {!sidebarCollapsed && (
        <aside className="sidebar">
          <div className="sidebar-header">
            <div className="sidebar-brand">
              <img src={theme === 'dark' ? '/anypoc_logo_dark.png' : '/anypoc_logo.png'} alt="" className="sidebar-logo" />
              <h1>AnyPoC</h1>
            </div>
            <button
              className="theme-toggle"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? '\u2600' : <span style={{ display: 'inline-block', transform: 'scaleX(-1)' }}>{'\u263E'}</span>}
            </button>
          </div>
          {CAW_VIEWER_PORT && (
            <a
              href={`http://${window.location.hostname}:${CAW_VIEWER_PORT}/`}
              target="_blank"
              rel="noreferrer"
              className="sidebar-traj-link"
            >
              Traj Viewer
            </a>
          )}
          <a href="/costs" className="sidebar-traj-link">Cost Dashboard</a>
          <div className="sidebar-search">
            <input
              type="text"
              placeholder="Filter projects..."
              value={filter}
              onChange={e => setFilter(e.target.value)}
            />
          </div>
          {hiddenCount > 0 && (
            <button
              className={`show-hidden-btn ${showHidden ? 'active' : ''}`}
              onClick={() => setShowHidden(!showHidden)}
            >
              {showHidden ? 'Hide' : 'Show'} {hiddenCount} hidden
            </button>
          )}
          <div className="project-list">
            {loading ? (
              <div className="project-item loading">Loading...</div>
            ) : filteredProjects.length === 0 ? (
              <div className="project-item placeholder">No projects found</div>
            ) : (
              filteredProjects.map(project => (
                <div
                  key={project.name}
                  className={`project-item ${selectedProject === project.name ? 'selected' : ''} ${hiddenProjects.has(project.name) ? 'hidden-project' : ''} ${draggedProject === project.name ? 'dragging' : ''}`}
                  onClick={() => setSelectedProject(project.name)}
                  draggable
                  onDragStart={() => handleDragStart(project.name)}
                  onDragOver={(e) => handleDragOver(e, project.name)}
                  onDragLeave={handleDragLeave}
                  onDrop={(e) => handleDrop(e, project.name)}
                  onDragEnd={handleDragEnd}
                >
                  <span className="drag-handle" title="Drag to reorder">&#x2630;</span>
                  <span className="project-name">{project.name}</span>
                  <button
                    className="hide-btn"
                    onClick={(e) => toggleHideProject(project.name, e)}
                    title={hiddenProjects.has(project.name) ? 'Unhide project' : 'Hide project'}
                  >
                    {hiddenProjects.has(project.name) ? <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg> : <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>}
                  </button>
                </div>
              ))
            )}
          </div>
        </aside>
      )}

      <main className="main-content">
        <div className="top-bar">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
            title={sidebarCollapsed ? 'Show projects' : 'Hide projects'}
          >
            {sidebarCollapsed ? '\u2630' : '\u25C0'}
          </button>
          <SpendLimitWidget />
        </div>
        {selectedProject ? (
          <>
            <h2>{selectedProject}</h2>
            <MonitorSection
              project={selectedProject}
              outputDir={outputDir}
              outputBasePath={outputBasePath}
              expanded={isPanelExpanded('monitor')}
              onToggle={() => togglePanel('monitor')}
              urlTab={monitorTab}
              urlItem={monitorItem}
              onSelectionChange={setMonitorState}
              isPanelExpanded={isPanelExpanded}
              togglePanel={togglePanel}
            />
            <KnowledgeSection
              project={selectedProject}
              expanded={isPanelExpanded('knowledge')}
              onToggle={() => togglePanel('knowledge')}
              urlKnowledgeItem={knowledgeItem}
              onKnowledgeItemConsumed={clearKnowledgeItem}
            />
            <CommandsSection
              project={selectedProject}
              expanded={isPanelExpanded('commands')}
              onToggle={() => togglePanel('commands')}
              copyToClipboard={copyToClipboard}
              copiedCmd={copiedCmd}
              cawProvider={cawProvider}
              setCawProvider={setCawProvider}
              cawModel={cawModel}
              setCawModel={setCawModel}
              cawEffort={cawEffort}
              setCawEffort={setCawEffort}
              modelsConfig={modelsConfig}
            />
          </>
        ) : (
          <p className="placeholder">Select a project from the sidebar</p>
        )}
      </main>
    </div>
  )
}

// Helper function to get rating color class
function getRatingColorClass(score: number): string {
  if (score >= 7) return 'green'
  if (score >= 4) return 'yellow'
  if (score >= 0) return 'orange'
  return 'red'
}

function MonitorSection({
  project,
  outputDir,
  outputBasePath,
  expanded,
  onToggle,
  urlTab,
  urlItem,
  onSelectionChange,
  isPanelExpanded,
  togglePanel
}: {
  project: string
  outputDir: string
  outputBasePath: string
  expanded: boolean
  onToggle: () => void
  urlTab: 'bugs' | 'pocs' | null
  urlItem: string | null
  onSelectionChange: (tab: 'bugs' | 'pocs', item: string | null) => void
  isPanelExpanded: (panel: string) => boolean
  togglePanel: (panel: string) => void
}) {
  const [summary, setSummary] = useState<MonitorSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'bugs' | 'pocs'>(urlTab || 'pocs')

  // Bugs state
  const [bugs, setBugs] = useState<BugItem[]>([])
  const [bugTrajs, setBugTrajs] = useState<TrajFile[]>([])
  const [bugsCompleteCount, setBugsCompleteCount] = useState<number | null>(null)
  const [selectedBug, setSelectedBug] = useState<string | null>(null)
  const [bugDetail, setBugDetail] = useState<BugDetail | null>(null)

  // PoCs state
  const [pocs, setPocs] = useState<PocItem[]>([])
  const [selectedPoc, setSelectedPoc] = useState<string | null>(null)
  const [pocDetail, setPocDetail] = useState<PocDetail | null>(null)
  const [selectedAttempt, setSelectedAttempt] = useState<number | null>(null)
  const [pocFilter, setPocFilter] = useState<'all' | 'passed' | 'check_failed' | 'impossible'>('all')
  const [pocSearch, setPocSearch] = useState('')

  // PoC annotation editing state
  const [pocEditStatus, setPocEditStatus] = useState<string>('unchecked')
  const [pocEditNotes, setPocEditNotes] = useState<string>('')
  const [pocAnnotationSaving, setPocAnnotationSaving] = useState(false)
  const POC_ANNOTATION_STATUSES = ['unchecked', 'To Report', 'Reported', 'Invalid', 'Skipped', 'Known', 'WIP']

  // Collapsible traj sections (collapsed by default)
  const [bugTrajsExpanded, setBugTrajsExpanded] = useState(false)

  // Track if we've loaded the initial URL item
  const [urlItemLoaded, setUrlItemLoaded] = useState(false)

  // Resize state
  const STORAGE_KEY = 'monitor-panel-height'
  const DEFAULT_HEIGHT = 600
  const MIN_HEIGHT = 300
  const MAX_HEIGHT = 1200
  const [contentHeight, setContentHeight] = useState(() => {
    const stored = localStorage.getItem(STORAGE_KEY)
    return stored ? Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, parseInt(stored, 10))) : DEFAULT_HEIGHT
  })
  const isResizing = useRef(false)
  const startY = useRef(0)
  const startHeight = useRef(0)

  // Resize handlers
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing.current) return
      const delta = e.clientY - startY.current
      const newHeight = Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, startHeight.current + delta))
      setContentHeight(newHeight)
    }

    const handleMouseUp = () => {
      if (isResizing.current) {
        isResizing.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        localStorage.setItem(STORAGE_KEY, contentHeight.toString())
      }
    }

    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
    }
  }, [contentHeight])

  const handleResizeStart = (e: React.MouseEvent) => {
    e.preventDefault()
    isResizing.current = true
    startY.current = e.clientY
    startHeight.current = contentHeight
    document.body.style.cursor = 'ns-resize'
    document.body.style.userSelect = 'none'
  }

  useEffect(() => {
    if (expanded && !summary) {
      setLoading(true)
      fetch(`/api/projects/${project}/monitor/summary`)
        .then(res => res.json())
        .then(data => {
          setSummary(data)
          setLoading(false)
        })
        .catch(err => {
          console.error('Failed to fetch monitor summary:', err)
          setLoading(false)
        })
    }
  }, [expanded, project, summary])

  // Load tab data when switching tabs
  useEffect(() => {
    if (!expanded || !summary?.exists) return

    if (activeTab === 'bugs' && bugs.length === 0) {
      fetch(`/api/projects/${project}/monitor/bugs`)
        .then(res => res.json())
        .then(data => {
          setBugs(data.items || [])
          setBugTrajs(data.traj_files || [])
          setBugsCompleteCount(data.complete_count ?? null)
        })
    } else if (activeTab === 'pocs' && pocs.length === 0) {
      fetch(`/api/projects/${project}/monitor/pocs`)
        .then(res => res.json())
        .then(data => setPocs(data.items || []))
    }
  }, [expanded, activeTab, project, summary, bugs.length, pocs.length])

  // Reset when project changes
  useEffect(() => {
    setSummary(null)
    setBugs([])
    setBugTrajs([])
    setBugsCompleteCount(null)
    setPocs([])
    setSelectedBug(null)
    setSelectedPoc(null)
    setBugDetail(null)
    setPocDetail(null)
    setSelectedAttempt(null)
    setPocEditStatus('unchecked')
    setPocEditNotes('')
    setUrlItemLoaded(false)
  }, [project])

  // Sync with URL tab changes (browser back/forward)
  useEffect(() => {
    if (urlTab && urlTab !== activeTab) {
      setActiveTab(urlTab)
    }
  }, [urlTab, activeTab])

  // Load item from URL when data becomes available
  useEffect(() => {
    if (urlItemLoaded || !urlItem || !urlTab) return

    if (urlTab === 'bugs' && bugs.length > 0) {
      const found = bugs.find(b => b.name === urlItem)
      if (found) {
        loadBugDetailInternal(urlItem)
        setUrlItemLoaded(true)
      }
    } else if (urlTab === 'pocs' && pocs.length > 0) {
      const found = pocs.find(p => p.name === urlItem)
      if (found) {
        loadPocDetailInternal(urlItem)
        setUrlItemLoaded(true)
      }
    }
  }, [urlItem, urlTab, urlItemLoaded, bugs, pocs])

  // Internal load functions (without URL update)
  const loadBugDetailInternal = (name: string) => {
    setSelectedBug(name)
    fetch(`/api/projects/${project}/monitor/bugs/${name}`)
      .then(res => res.json())
      .then(data => setBugDetail(data))
  }

  const loadPocDetailInternal = (name: string, attemptNum?: number) => {
    setSelectedPoc(name)
    const url = attemptNum !== undefined
      ? `/api/projects/${project}/monitor/pocs/${name}?attempt=${attemptNum}`
      : `/api/projects/${project}/monitor/pocs/${name}`
    fetch(url)
      .then(res => res.json())
      .then(data => {
        setPocDetail(data)
        setSelectedAttempt(data.selected_attempt)
        setPocEditStatus(data.annotation_status || 'unchecked')
        setPocEditNotes(data.annotation_notes || '')
      })
  }

  // Function to switch attempt for the current PoC
  const switchAttempt = (attemptNum: number) => {
    if (selectedPoc) {
      loadPocDetailInternal(selectedPoc, attemptNum)
    }
  }

  const savePocAnnotation = async () => {
    if (!selectedPoc) return
    setPocAnnotationSaving(true)
    try {
      const response = await fetch(
        `/api/projects/${project}/monitor/pocs/${encodeURIComponent(selectedPoc)}/annotation`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: pocEditStatus, notes: pocEditNotes })
        }
      )
      if (response.ok) {
        // Update local list state
        setPocs(prev =>
          prev.map(p =>
            p.name === selectedPoc ? { ...p, annotation_status: pocEditStatus } : p
          )
        )
        if (pocDetail) {
          setPocDetail({ ...pocDetail, annotation_status: pocEditStatus, annotation_notes: pocEditNotes })
        }
      }
    } catch (err) {
      console.error('Failed to save PoC annotation:', err)
    } finally {
      setPocAnnotationSaving(false)
    }
  }

  // Public load functions (with URL update)
  const loadBugDetail = (name: string) => {
    loadBugDetailInternal(name)
    onSelectionChange('bugs', name)
  }

  const loadPocDetail = (name: string) => {
    loadPocDetailInternal(name)
    onSelectionChange('pocs', name)
  }

  // Tab change handler
  const handleTabChange = (tab: 'bugs' | 'pocs') => {
    setActiveTab(tab)
    onSelectionChange(tab, null)
  }

  const colorIcons: Record<string, string> = {
    green: '\u2713',
    red: '\u2717',
    yellow: '\u26A0',
    blue: '~',
    white: '\u25CB'
  }

  const stepNames: Record<string, string> = {
    analysis: 'Analysis',
    generation: 'Generation',
    evidence_check: 'Evidence Check',
    report: 'Report'
  }

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B'
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  return (
    <div className="collapsible-section">
      <div className="section-header" onClick={onToggle}>
        <span className="toggle">{expanded ? '\u25BC' : '\u25B6'}</span>
        <h3>Monitor</h3>
        {summary && summary.exists && (
          <span className="monitor-badge">
            {summary.pocs_complete}/{summary.pocs} PoCs
          </span>
        )}
      </div>
      {expanded && (
        <div className="section-content">
          {loading ? (
            <p className="loading">Loading...</p>
          ) : !summary?.exists ? (
            <p className="placeholder">No output data for this project</p>
          ) : (
            <>
              {/* Summary tiles */}
              <div className="monitor-summary">
                <div className="summary-tile" onClick={() => handleTabChange('bugs')}>
                  <div className="tile-label">Bug Reports</div>
                  <div className="tile-value">{summary.bugs}</div>
                  <div className="tile-cost">${summary.bugs_cost_usd.toFixed(2)}</div>
                </div>
                <div className="summary-tile" onClick={() => handleTabChange('pocs')}>
                  <div className="tile-label">PoCs</div>
                  <div className="tile-value">
                    <span className="poc-complete">{summary.pocs_complete}</span>/{summary.pocs}
                  </div>
                  <div className="tile-cost">${summary.pocs_cost_usd.toFixed(2)}</div>
                </div>
              </div>

              {/* Tab navigation */}
              <div className="monitor-tabs">
                <button
                  className={`tab-btn ${activeTab === 'bugs' ? 'active' : ''}`}
                  onClick={() => handleTabChange('bugs')}
                >
                  Bugs
                </button>
                <button
                  className={`tab-btn ${activeTab === 'pocs' ? 'active' : ''}`}
                  onClick={() => handleTabChange('pocs')}
                >
                  PoCs
                </button>
              </div>

              {/* PoC filter buttons */}
              {activeTab === 'pocs' && (
                <div className="poc-filter-buttons">
                  <button
                    className={`filter-btn ${pocFilter === 'all' ? 'active' : ''}`}
                    onClick={() => setPocFilter('all')}
                  >
                    All
                  </button>
                  <button
                    className={`filter-btn filter-passed ${pocFilter === 'passed' ? 'active' : ''}`}
                    onClick={() => setPocFilter('passed')}
                  >
                    Passed
                  </button>
                  <button
                    className={`filter-btn filter-check-failed ${pocFilter === 'check_failed' ? 'active' : ''}`}
                    onClick={() => setPocFilter('check_failed')}
                  >
                    Check Failed
                  </button>
                  <button
                    className={`filter-btn filter-impossible ${pocFilter === 'impossible' ? 'active' : ''}`}
                    onClick={() => setPocFilter('impossible')}
                  >
                    Impossible
                  </button>
                  <div className="search-box-wrapper">
                    <input
                      type="text"
                      className="poc-search"
                      placeholder="Search PoCs..."
                      value={pocSearch}
                      onChange={e => setPocSearch(e.target.value)}
                    />
                    {pocSearch && (
                      <button className="search-clear-btn" onClick={() => setPocSearch('')}>×</button>
                    )}
                  </div>
                </div>
              )}

              {/* Bugs tab info line */}
              {activeTab === 'bugs' && bugsCompleteCount !== null && (
                <div className="tab-info-line">
                  {bugsCompleteCount} scan{bugsCompleteCount !== 1 ? 's' : ''} complete
                </div>
              )}

              {/* Tab content */}
              <div className="monitor-content" style={{ height: contentHeight }}>
                {activeTab === 'bugs' && (
                  <div className="two-column">
                    <div className="list-panel">
                      {bugs.length === 0 && bugTrajs.length === 0 ? (
                        <p className="placeholder">No bug reports</p>
                      ) : (
                        <>
                          {bugTrajs.length > 0 && (
                            <>
                              <div
                                className="list-section-header collapsible"
                                onClick={() => setBugTrajsExpanded(v => !v)}
                              >
                                <span className={`collapse-arrow ${bugTrajsExpanded ? 'expanded' : ''}`}>&#9654;</span>
                                Trajectories ({bugTrajs.length})
                              </div>
                              {bugTrajsExpanded && bugTrajs.map(traj => (
                                <div key={traj.absolute_path} className="list-item traj-item">
                                  <span className="traj-name">{traj.name}</span>
                                  <span className="traj-links">
                                    {(() => { const u = cawViewerUrl(traj.absolute_path); return u && (
                                      <a
                                        href={u}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="traj-link"
                                        onClick={e => e.stopPropagation()}
                                      >
                                        view
                                      </a>
                                    )})()}
                                  </span>
                                </div>
                              ))}
                            </>
                          )}
                          {bugs.length > 0 && (
                            <>
                              <div className="list-section-header">Bug Reports</div>
                              {bugs.map(bug => (
                                <div
                                  key={bug.name}
                                  className={`list-item ${selectedBug === bug.name ? 'active' : ''}`}
                                  onClick={() => loadBugDetail(bug.name)}
                                >
                                  {bug.name}
                                </div>
                              ))}
                            </>
                          )}
                        </>
                      )}
                    </div>
                    <div className="detail-panel">
                      {bugDetail ? (
                        <div>
                          <h4>{bugDetail.title || bugDetail.name}</h4>
                          <div className="bug-meta-row">
                            <span className="label">Strategy:</span> {bugDetail.strategy}
                            {' \u00b7 '}
                            <span className="label">Scan:</span> {bugDetail.scan_id}
                          </div>
                          <div className="file-links">
                            <a
                              href={`/api/files/${outputDir}/${project}/${bugDetail.markdown_path}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {bugDetail.markdown_name}
                            </a>
                          </div>
                          {Object.keys(bugDetail.metadata || {}).length > 0 && (
                            <div className="json-viewer">
                              <h5>Metadata</h5>
                              <JsonView data={bugDetail.metadata} />
                            </div>
                          )}
                          {bugDetail.markdown_html && (
                            <div className="bug-report-body">
                              <h5>Report</h5>
                              <div
                                className="detail-content markdown-body"
                                dangerouslySetInnerHTML={{ __html: bugDetail.markdown_html }}
                              />
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="placeholder">Select a bug report to view</p>
                      )}
                    </div>
                  </div>
                )}

                {activeTab === 'pocs' && (
                  <div className="two-column">
                    <div className="list-panel">
                      {pocs.length === 0 ? (
                        <p className="placeholder">No PoCs</p>
                      ) : (
                        (() => {
                          const filteredPocs = pocs.filter(poc => {
                            // Search filter: check if name contains search text
                            if (pocSearch && !poc.name.toLowerCase().includes(pocSearch.toLowerCase())) {
                              return false
                            }
                            if (pocFilter === 'all') return true
                            if (pocFilter === 'passed') return poc.evidence_status === 'passed'
                            if (pocFilter === 'impossible') {
                              // Only show truly impossible (from generation or evidence)
                              return poc.generation_status === 'impossible' || poc.evidence_status === 'impossible'
                            }
                            if (pocFilter === 'check_failed') {
                              // Generation completed (not pending/in_progress/error/impossible)
                              // AND evidence not passed, not impossible
                              // AND analysis not rejected
                              const generationCompleted = !['pending', 'in_progress', 'error', 'impossible'].includes(poc.generation_status)
                              const evidenceFailed = poc.evidence_status !== 'passed' &&
                                                     poc.evidence_status !== 'impossible' &&
                                                     poc.evidence_status !== 'pending' &&
                                                     poc.evidence_status !== 'in_progress'
                              const analysisNotRejected = poc.analysis_status !== 'rejected'
                              return generationCompleted && evidenceFailed && analysisNotRejected
                            }
                            return true
                          })
                          return filteredPocs.length === 0 ? (
                            <p className="placeholder">No PoCs match filter</p>
                          ) : (
                            filteredPocs.map(poc => (
                              <div
                                key={poc.name}
                                className={`list-item poc-${poc.color} ${selectedPoc === poc.name ? 'active' : ''}`}
                                onClick={() => loadPocDetail(poc.name)}
                              >
                                <span className={`poc-icon poc-${poc.color}`}>{colorIcons[poc.color] || '\u25CB'}</span>
                                <span className="list-item-text" title={poc.name}>{poc.name}</span>
                                {poc.annotation_status && poc.annotation_status !== 'unchecked' && (
                                  <span className={`poc-annotation-badge status-${poc.annotation_status.toLowerCase().replace(/\s+/g, '-')}`}>{poc.annotation_status}</span>
                                )}
                              </div>
                            ))
                          )
                        })()
                      )}
                    </div>
                    <div className="detail-panel">
                      {pocDetail ? (
                        <div>
                          <h4>{pocDetail.name}</h4>
                          <div className="poc-total-cost">
                            Total Cost: ${pocDetail.total_cost_usd.toFixed(2)}
                          </div>
                          {/* Attempt switcher */}
                          {pocDetail.attempts && pocDetail.attempts.length > 0 && (
                            <div className="attempt-switcher">
                              <span className="attempt-label">Attempts:</span>
                              <div className="attempt-buttons">
                                {pocDetail.attempts.map(attempt => (
                                  <button
                                    key={attempt.number}
                                    className={`attempt-btn attempt-${attempt.color} ${selectedAttempt === attempt.number ? 'active' : ''}`}
                                    onClick={() => switchAttempt(attempt.number)}
                                    title={`Attempt ${attempt.number}: $${attempt.cost_usd.toFixed(2)}`}
                                  >
                                    <span className={`attempt-icon attempt-${attempt.color}`}>{colorIcons[attempt.color] || '\u25CB'}</span>
                                    <span className="attempt-num">{attempt.number}</span>
                                    <span className="attempt-cost">${attempt.cost_usd.toFixed(2)}</span>
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                          {pocDetail.scan_id && (
                            <div className="pattern-ref">
                              <span className="label">
                                {pocDetail.bug_strategy ? `${pocDetail.bug_strategy} · ` : ''}
                                {pocDetail.scan_id}
                              </span>
                              <button
                                className="ref-btn"
                                onClick={() => {
                                  setActiveTab('bugs')
                                  loadBugDetail(pocDetail.name)
                                }}
                              >
                                Show Bug Report
                              </button>
                            </div>
                          )}
                          {/* PoC Annotation form */}
                          <div className="poc-annotation-form">
                            <div className="poc-annotation-row">
                              <div className="poc-annotation-status-select">
                                <label>Annotation</label>
                                <select
                                  value={pocEditStatus}
                                  onChange={e => setPocEditStatus(e.target.value)}
                                >
                                  {POC_ANNOTATION_STATUSES.map(s => (
                                    <option key={s} value={s}>{s}</option>
                                  ))}
                                </select>
                              </div>
                              <button
                                className="poc-annotation-save-btn"
                                onClick={savePocAnnotation}
                                disabled={pocAnnotationSaving}
                              >
                                {pocAnnotationSaving ? 'Saving...' : 'Save'}
                              </button>
                            </div>
                            <div className="poc-annotation-notes-field">
                              <textarea
                                value={pocEditNotes}
                                onChange={e => setPocEditNotes(e.target.value)}
                                placeholder="Add notes about this PoC..."
                                rows={2}
                              />
                            </div>
                          </div>

                          <div className="poc-steps">
                            {pocDetail.steps.map(step => (
                              <div key={step.name} className={`poc-step ${step.status}`}>
                                <span className="step-name">{stepNames[step.name] || step.name}</span>
                                <span className={`step-status ${step.status}`}>{step.status}</span>
                                {step.traj_path && (
                                  <>
                                    <a
                                      href={`/api/files/${outputDir}/${project}/${step.traj_path}`}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="step-link"
                                    >
                                      json
                                    </a>
                                    {(() => { const u = cawViewerUrl(`${outputBasePath}/${project}/${step.traj_path}`); return u && (
                                      <a href={u} target="_blank" rel="noreferrer" className="step-link">view</a>
                                    )})()}
                                  </>
                                )}
                                {step.cost_usd !== null && (
                                  <span className="step-cost">${step.cost_usd.toFixed(2)}</span>
                                )}
                              </div>
                            ))}
                          </div>
                          {/* Knowledge Usage & Extraction Section */}
                          {(pocDetail.knowledge_usage || pocDetail.knowledge_extraction) && (
                            <div className="poc-knowledge-section">
                              <h5>Knowledge</h5>
                              {pocDetail.knowledge_usage && pocDetail.knowledge_usage.ratings.length > 0 && (
                                <div className="knowledge-subsection">
                                  <h6>Rated During Generation</h6>
                                  <ul className="knowledge-links">
                                    {pocDetail.knowledge_usage.ratings.map(rating => {
                                      // Create clean URL with only knowledge panel
                                      const href = `/${encodeURIComponent(project)}?panels=knowledge&knowledge_item=${encodeURIComponent(rating.file_path)}`
                                      return (
                                        <li key={rating.file_path} className="knowledge-link-item">
                                          <a
                                            className="knowledge-link"
                                            href={href}
                                            onClick={(e) => {
                                              // Left click: just expand knowledge panel, keep current view
                                              if (e.button === 0 && !e.ctrlKey && !e.metaKey) {
                                                e.preventDefault()
                                                if (!isPanelExpanded('knowledge')) {
                                                  togglePanel('knowledge')
                                                }
                                                // Update URL to include knowledge_item but keep current panels
                                                const currentParams = new URLSearchParams(window.location.search)
                                                currentParams.set('knowledge_item', rating.file_path)
                                                const currentHref = `/${encodeURIComponent(project)}?${currentParams.toString()}`
                                                window.history.pushState({}, '', currentHref)
                                                window.dispatchEvent(new PopStateEvent('popstate'))
                                              }
                                              // Middle click or Ctrl+click: browser opens href (clean URL with only knowledge)
                                            }}
                                            title={`Click to view: ${rating.file_path}`}
                                          >
                                            {rating.file_path}
                                          </a>
                                          <span className={`knowledge-rating-badge rating-${getRatingColorClass(rating.score)}`}>
                                            {rating.score > 0 ? '+' : ''}{rating.score}
                                          </span>
                                        </li>
                                      )
                                    })}
                                  </ul>
                                </div>
                              )}
                              {pocDetail.knowledge_extraction && (
                                <div className="knowledge-subsection">
                                  <h6>Extracted From This Run</h6>
                                  {pocDetail.knowledge_extraction.reported.length > 0 && (
                                    <div className="knowledge-extracted">
                                      <span className="extraction-label">New:</span>
                                      <ul className="knowledge-links">
                                        {pocDetail.knowledge_extraction.reported.map(filePath => {
                                          // Clean URL with only knowledge panel for middle-click
                                          const href = `/${encodeURIComponent(project)}?panels=knowledge&knowledge_item=${encodeURIComponent(filePath)}`
                                          return (
                                            <li key={filePath} className="knowledge-link-item">
                                              <span className="knowledge-badge new">NEW</span>
                                              <a
                                                className="knowledge-link"
                                                href={href}
                                                onClick={(e) => {
                                                  if (e.button === 0 && !e.ctrlKey && !e.metaKey) {
                                                    e.preventDefault()
                                                    if (!isPanelExpanded('knowledge')) {
                                                      togglePanel('knowledge')
                                                    }
                                                    const currentParams = new URLSearchParams(window.location.search)
                                                    currentParams.set('knowledge_item', filePath)
                                                    const currentHref = `/${encodeURIComponent(project)}?${currentParams.toString()}`
                                                    window.history.pushState({}, '', currentHref)
                                                    window.dispatchEvent(new PopStateEvent('popstate'))
                                                  }
                                                }}
                                                title={`Click to view: ${filePath}`}
                                              >
                                                {filePath}
                                              </a>
                                            </li>
                                          )
                                        })}
                                      </ul>
                                    </div>
                                  )}
                                  {pocDetail.knowledge_extraction.updated.length > 0 && (
                                    <div className="knowledge-extracted">
                                      <span className="extraction-label">Updated:</span>
                                      <ul className="knowledge-links">
                                        {pocDetail.knowledge_extraction.updated.map(filePath => {
                                          // Clean URL with only knowledge panel for middle-click
                                          const href = `/${encodeURIComponent(project)}?panels=knowledge&knowledge_item=${encodeURIComponent(filePath)}`
                                          return (
                                            <li key={filePath} className="knowledge-link-item">
                                              <span className="knowledge-badge updated">UPDATED</span>
                                              <a
                                                className="knowledge-link"
                                                href={href}
                                                onClick={(e) => {
                                                  if (e.button === 0 && !e.ctrlKey && !e.metaKey) {
                                                    e.preventDefault()
                                                    if (!isPanelExpanded('knowledge')) {
                                                      togglePanel('knowledge')
                                                    }
                                                    const currentParams = new URLSearchParams(window.location.search)
                                                    currentParams.set('knowledge_item', filePath)
                                                    const currentHref = `/${encodeURIComponent(project)}?${currentParams.toString()}`
                                                    window.history.pushState({}, '', currentHref)
                                                    window.dispatchEvent(new PopStateEvent('popstate'))
                                                  }
                                                }}
                                                title={`Click to view: ${filePath}`}
                                              >
                                                {filePath}
                                              </a>
                                            </li>
                                          )
                                        })}
                                      </ul>
                                    </div>
                                  )}
                                  {pocDetail.knowledge_extraction.reported.length === 0 &&
                                   pocDetail.knowledge_extraction.updated.length === 0 && (
                                    <p className="knowledge-empty">No knowledge was extracted</p>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                          {pocDetail.input_files && pocDetail.input_files.length > 0 && (
                            <div className="file-tree input-files">
                              <h5>Input</h5>
                              <InputFileTree
                                nodes={pocDetail.input_files}
                                project={project}
                                pocName={pocDetail.name}
                                outputBasePath={outputBasePath}
                                outputDir={outputDir}
                                formatFileSize={formatFileSize}
                              />
                            </div>
                          )}
                          {pocDetail.file_tree.length > 0 && (
                            <div className="file-tree">
                              <h5>Files</h5>
                              <FileTree
                                nodes={pocDetail.file_tree}
                                project={project}
                                outputBasePath={outputBasePath}
                                outputDir={outputDir}
                                formatFileSize={formatFileSize}
                              />
                            </div>
                          )}
                        </div>
                      ) : (
                        <p className="placeholder">Select a PoC to view</p>
                      )}
                    </div>
                  </div>
                )}
                {/* Resize handle */}
                <div
                  className="monitor-resize-handle"
                  onMouseDown={handleResizeStart}
                  title="Drag to resize"
                />
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function JsonView({ data }: { data: unknown }) {
  if (data === null) return <span className="json-null">null</span>
  if (typeof data === 'string') return <pre className="json-string">{data}</pre>
  if (typeof data === 'number' || typeof data === 'boolean') {
    return <span className="json-primitive">{String(data)}</span>
  }
  if (Array.isArray(data)) {
    return (
      <ol className="json-array">
        {data.map((item, i) => (
          <li key={i}><JsonView data={item} /></li>
        ))}
      </ol>
    )
  }
  if (typeof data === 'object') {
    return (
      <dl className="json-object">
        {Object.entries(data as Record<string, unknown>).map(([key, val]) => (
          <div key={key} className="json-entry">
            <dt>{key}</dt>
            <dd><JsonView data={val} /></dd>
          </div>
        ))}
      </dl>
    )
  }
  return <span>{String(data)}</span>
}

function FileTree({
  nodes,
  project,
  outputBasePath,
  outputDir,
  formatFileSize
}: {
  nodes: FileTreeNode[]
  project: string
  outputBasePath: string
  outputDir: string
  formatFileSize: (bytes: number) => string
}) {
  // Track expanded directories (all collapsed by default except poc and evidence)
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['poc', 'evidence']))
  const [copiedPath, setCopiedPath] = useState<string | null>(null)

  const toggle = (path: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      return next
    })
  }

  const copyPath = async (nodePath: string) => {
    // nodePath now includes the full path from output dir (e.g., poc/name/attempt_X/file)
    const absolutePath = `${outputBasePath}/${project}/${nodePath}`
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(absolutePath)
      } else {
        const textArea = document.createElement('textarea')
        textArea.value = absolutePath
        textArea.style.position = 'fixed'
        textArea.style.left = '-999999px'
        document.body.appendChild(textArea)
        textArea.select()
        document.execCommand('copy')
        document.body.removeChild(textArea)
      }
      setCopiedPath(nodePath)
      setTimeout(() => setCopiedPath(null), 1500)
    } catch (err) {
      console.error('Failed to copy path:', err)
    }
  }

  const renderNode = (node: FileTreeNode): JSX.Element => {
    if (node.is_dir) {
      const isExpanded = expanded.has(node.name)
      return (
        <li key={node.path}>
          <div className="tree-item">
            <span className="tree-toggle" onClick={() => toggle(node.name)}>
              {isExpanded ? '\u25BC' : '\u25B6'}
            </span>
            <span className="tree-name">{node.name}/</span>
            <button
              className={`copy-path-btn ${copiedPath === node.path ? 'copied' : ''}`}
              onClick={() => copyPath(node.path)}
              title="Copy absolute path"
            >
              {copiedPath === node.path ? 'Copied!' : 'Copy Path'}
            </button>
          </div>
          {isExpanded && node.children && (
            <ul>
              {node.children.map(renderNode)}
            </ul>
          )}
        </li>
      )
    }
    return (
      <li key={node.path}>
        <div className="tree-item">
          <span className="tree-icon">{'\uD83D\uDCC4'}</span>
          <a
            href={`/api/files/${outputDir}/${project}/${node.path}`}
            target="_blank"
            rel="noreferrer"
            className="tree-name"
          >
            {node.name}
          </a>
          {node.size !== undefined && (
            <span className="tree-size">{formatFileSize(node.size)}</span>
          )}
          <button
            className={`copy-path-btn ${copiedPath === node.path ? 'copied' : ''}`}
            onClick={() => copyPath(node.path)}
            title="Copy absolute path"
          >
            {copiedPath === node.path ? 'Copied!' : 'Copy Path'}
          </button>
          {node.name.endsWith('.traj.json') && (() => {
            const u = cawViewerUrl(`${outputBasePath}/${project}/${node.path}`)
            return u && (
              <a href={u} target="_blank" rel="noreferrer" className="copy-path-btn" style={{ textDecoration: 'none' }}>
                Traj Viewer
              </a>
            )
          })()}
        </div>
      </li>
    )
  }

  return (
    <ul className="tree-root">
      {nodes.map(renderNode)}
    </ul>
  )
}

function InputFileTree({
  nodes,
  project,
  pocName,
  outputBasePath,
  outputDir,
  formatFileSize
}: {
  nodes: FileTreeNode[]
  project: string
  pocName: string
  outputBasePath: string
  outputDir: string
  formatFileSize: (bytes: number) => string
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [copiedPath, setCopiedPath] = useState<string | null>(null)

  const toggle = (path: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      return next
    })
  }

  const copyPath = async (nodePath: string) => {
    const absolutePath = `${outputBasePath}/${project}/poc/${pocName}/input/${nodePath}`
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(absolutePath)
      } else {
        const textArea = document.createElement('textarea')
        textArea.value = absolutePath
        textArea.style.position = 'fixed'
        textArea.style.left = '-999999px'
        document.body.appendChild(textArea)
        textArea.select()
        document.execCommand('copy')
        document.body.removeChild(textArea)
      }
      setCopiedPath(nodePath)
      setTimeout(() => setCopiedPath(null), 1500)
    } catch (err) {
      console.error('Failed to copy path:', err)
    }
  }

  const renderNode = (node: FileTreeNode): JSX.Element => {
    if (node.is_dir) {
      const isExpanded = expanded.has(node.name)
      return (
        <li key={node.path}>
          <div className="tree-item">
            <span className="tree-toggle" onClick={() => toggle(node.name)}>
              {isExpanded ? '\u25BC' : '\u25B6'}
            </span>
            <span className="tree-name">{node.name}/</span>
            <button
              className={`copy-path-btn ${copiedPath === node.path ? 'copied' : ''}`}
              onClick={() => copyPath(node.path)}
              title="Copy absolute path"
            >
              {copiedPath === node.path ? 'Copied!' : 'Copy Path'}
            </button>
          </div>
          {isExpanded && node.children && (
            <ul>
              {node.children.map(renderNode)}
            </ul>
          )}
        </li>
      )
    }
    return (
      <li key={node.path}>
        <div className="tree-item">
          <span className="tree-icon">{'\uD83D\uDCC4'}</span>
          <a
            href={`/api/files/${outputDir}/${project}/poc/${pocName}/input/${node.path}`}
            target="_blank"
            rel="noreferrer"
            className="tree-name"
          >
            {node.name}
          </a>
          {node.size !== undefined && (
            <span className="tree-size">{formatFileSize(node.size)}</span>
          )}
          <button
            className={`copy-path-btn ${copiedPath === node.path ? 'copied' : ''}`}
            onClick={() => copyPath(node.path)}
            title="Copy absolute path"
          >
            {copiedPath === node.path ? 'Copied!' : 'Copy Path'}
          </button>
        </div>
      </li>
    )
  }

  return (
    <ul className="tree-root">
      {nodes.map(renderNode)}
    </ul>
  )
}

function KnowledgeSection({
  project,
  expanded,
  onToggle,
  urlKnowledgeItem,
  onKnowledgeItemConsumed
}: {
  project: string
  expanded: boolean
  onToggle: () => void
  urlKnowledgeItem?: string | null
  onKnowledgeItemConsumed?: () => void
}) {
  const [summary, setSummary] = useState<KnowledgeSummary | null>(null)
  const [entries, setEntries] = useState<KnowledgeEntryItem[]>([])
  const [selectedEntry, setSelectedEntry] = useState<string | null>(null)
  const [entryDetail, setEntryDetail] = useState<KnowledgeEntryDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<'rating' | 'name' | 'updated' | 'iterations'>('rating')

  // Handle URL-based knowledge item selection
  useEffect(() => {
    if (urlKnowledgeItem && expanded && summary?.exists) {
      // Set the selected entry from URL param
      setSelectedEntry(urlKnowledgeItem)
      // Clear the URL param after consuming it
      if (onKnowledgeItemConsumed) {
        onKnowledgeItemConsumed()
      }
    }
  }, [urlKnowledgeItem, expanded, summary, onKnowledgeItemConsumed])

  // Fetch summary when expanded
  useEffect(() => {
    if (expanded && !summary) {
      setLoading(true)
      fetch(`/api/projects/${project}/knowledge/summary`)
        .then(res => res.json())
        .then(data => {
          setSummary(data)
          setLoading(false)
        })
        .catch(err => {
          console.error('Failed to fetch knowledge summary:', err)
          setLoading(false)
        })
    }
  }, [expanded, project, summary])

  // Fetch entries when summary is loaded or filters change
  useEffect(() => {
    if (!expanded || !summary?.exists) return

    const params = new URLSearchParams()
    if (selectedCategory) params.set('category', selectedCategory)
    if (searchTerm) params.set('search', searchTerm)
    params.set('sort_by', sortBy)

    fetch(`/api/projects/${project}/knowledge/entries?${params}`)
      .then(res => res.json())
      .then(data => setEntries(data.items || []))
      .catch(err => console.error('Failed to fetch entries:', err))
  }, [expanded, project, summary, selectedCategory, searchTerm, sortBy])

  // Fetch entry detail when selected
  useEffect(() => {
    if (!selectedEntry) {
      setEntryDetail(null)
      return
    }

    fetch(`/api/projects/${project}/knowledge/entries/${encodeURIComponent(selectedEntry)}`)
      .then(res => res.json())
      .then(data => setEntryDetail(data))
      .catch(err => console.error('Failed to fetch entry detail:', err))
  }, [project, selectedEntry])

  // Reset when project changes
  useEffect(() => {
    setSummary(null)
    setEntries([])
    setSelectedEntry(null)
    setEntryDetail(null)
    setSearchTerm('')
    setSelectedCategory(null)
  }, [project])

  const getRatingColor = (rating: number | null): string => {
    if (rating === null) return 'gray'
    if (rating >= 7) return 'green'
    if (rating >= 4) return 'yellow'
    if (rating >= 0) return 'orange'
    return 'red'
  }

  return (
    <div className="collapsible-section">
      <div className="section-header" onClick={onToggle}>
        <span className="toggle">{expanded ? '▼' : '▶'}</span>
        <h3>Knowledge Base</h3>
        {summary?.exists && (
          <span className="section-badge">{summary.total_entries} entries</span>
        )}
      </div>
      {expanded && (
        <div className="section-content">
          {loading ? (
            <p className="loading">Loading...</p>
          ) : !summary?.exists ? (
            <p className="placeholder">No knowledge base found for this project</p>
          ) : (
            <>
              {/* Summary Stats */}
              <div className="knowledge-summary">
                <div className="summary-stat">
                  <span className="stat-value">{summary.total_entries}</span>
                  <span className="stat-label">Entries</span>
                </div>
                <div className="summary-stat">
                  <span className="stat-value">{summary.categories_count}</span>
                  <span className="stat-label">Categories</span>
                </div>
                <div className="summary-stat">
                  <span className="stat-value">
                    {summary.avg_rating !== null ? summary.avg_rating.toFixed(1) : '-'}
                  </span>
                  <span className="stat-label">Avg Rating</span>
                </div>
              </div>

              {/* Category Pills */}
              <div className="knowledge-categories">
                <button
                  className={`category-pill ${!selectedCategory ? 'active' : ''}`}
                  onClick={() => setSelectedCategory(null)}
                >
                  All ({summary.total_entries})
                </button>
                {Object.entries(summary.entries_by_category)
                  .sort((a, b) => b[1] - a[1])
                  .map(([cat, count]) => (
                    <button
                      key={cat}
                      className={`category-pill ${selectedCategory === cat ? 'active' : ''}`}
                      onClick={() => setSelectedCategory(selectedCategory === cat ? null : cat)}
                    >
                      {cat} ({count})
                    </button>
                  ))}
              </div>

              {/* Two-column layout */}
              <div className="knowledge-content">
                {/* Left panel: Search + Entry list */}
                <div className="knowledge-list-panel">
                  <div className="knowledge-search">
                    <input
                      type="text"
                      placeholder="Search entries..."
                      value={searchTerm}
                      onChange={e => setSearchTerm(e.target.value)}
                    />
                    <select
                      value={sortBy}
                      onChange={e => setSortBy(e.target.value as typeof sortBy)}
                    >
                      <option value="rating">Sort by Rating</option>
                      <option value="name">Sort by Name</option>
                      <option value="updated">Sort by Updated</option>
                      <option value="iterations">Sort by Iterations</option>
                    </select>
                  </div>

                  <div className="knowledge-entry-list">
                    {entries.length === 0 ? (
                      <p className="placeholder">No entries found</p>
                    ) : (
                      entries.map(entry => (
                        <div
                          key={entry.file_path}
                          className={`knowledge-entry-item ${selectedEntry === entry.file_path ? 'selected' : ''}`}
                          onClick={() => setSelectedEntry(entry.file_path)}
                        >
                          <div className="entry-header">
                            <span className="entry-name" title={entry.name}>{entry.name}</span>
                          </div>
                          <div className="entry-meta-row">
                            <span className="entry-path">{entry.category_path.join(' / ')}</span>
                            {entry.avg_rating !== null && (
                              <span
                                className="rating-badge"
                                style={{ backgroundColor: `var(--rating-${getRatingColor(entry.avg_rating)})` }}
                              >
                                {entry.avg_rating.toFixed(1)}
                              </span>
                            )}
                          </div>
                          {entry.keywords.length > 0 && (
                            <div className="entry-keywords">
                              {entry.keywords.slice(0, 3).map(kw => (
                                <span key={kw} className="keyword-tag">{kw}</span>
                              ))}
                              {entry.keywords.length > 3 && (
                                <span className="keyword-more">+{entry.keywords.length - 3}</span>
                              )}
                            </div>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>

                {/* Right panel: Entry detail */}
                <div className="knowledge-detail-panel">
                  {!selectedEntry ? (
                    <p className="placeholder">Select an entry to view details</p>
                  ) : !entryDetail ? (
                    <p className="loading">Loading...</p>
                  ) : (
                    <>
                      <div className="detail-header">
                        <h4>{entryDetail.name}</h4>
                        <div className="detail-meta">
                          <span className="meta-item">v{entryDetail.version}</span>
                          {entryDetail.avg_rating !== null && (
                            <span
                              className="rating-badge large"
                              style={{ backgroundColor: `var(--rating-${getRatingColor(entryDetail.avg_rating)})` }}
                            >
                              Rating: {entryDetail.avg_rating.toFixed(1)}
                            </span>
                          )}
                          <span className="meta-item">{entryDetail.iterations_survived} iterations</span>
                        </div>
                      </div>

                      <div className="detail-keywords">
                        {entryDetail.keywords.map(kw => (
                          <span key={kw} className="keyword-tag">{kw}</span>
                        ))}
                      </div>

                      <div className="detail-timestamps">
                        <span>Created: {new Date(entryDetail.created_at).toLocaleDateString()}</span>
                        <span>Updated: {new Date(entryDetail.updated_at).toLocaleDateString()}</span>
                      </div>

                      {(entryDetail.all_ratings.length > 0 || entryDetail.source_generations.length > 0) && (
                        <div className="detail-ratings-section">
                          {entryDetail.all_ratings.length > 0 && (
                            <div className="detail-ratings">
                              <span className="ratings-label">Ratings:</span>
                              <span className="ratings-numbers">
                                {entryDetail.all_ratings.map((r, i) => (
                                  <span
                                    key={i}
                                    className={`rating-number rating-${getRatingColor(r)}`}
                                  >
                                    {r}
                                  </span>
                                ))}
                              </span>
                            </div>
                          )}
                          {entryDetail.source_generations.length > 0 && (
                            <details className="detail-sources">
                              <summary className="sources-summary">
                                Source PoCs ({entryDetail.source_generations.length})
                              </summary>
                              <ul className="sources-list">
                                {entryDetail.source_generations.map((sourcePath, i) => {
                                  // Extract PoC name from path like ".../poc/{poc-name}/attempt_N"
                                  const pocMatch = sourcePath.match(/\/poc\/([^/]+)/)
                                  const pocName = pocMatch ? pocMatch[1] : sourcePath
                                  const params = new URLSearchParams()
                                  params.set('panels', 'monitor')
                                  params.set('tab', 'pocs')
                                  params.set('item', pocName)
                                  const href = `/${encodeURIComponent(project)}?${params.toString()}`
                                  const wasSuccessful = entryDetail.source_success_flags[i]
                                  return (
                                    <li key={i} className="source-item">
                                      <a
                                        className="source-link"
                                        href={href}
                                        onClick={(e) => {
                                          if (e.button === 0 && !e.ctrlKey && !e.metaKey) {
                                            e.preventDefault()
                                            window.history.pushState({}, '', href)
                                            window.dispatchEvent(new PopStateEvent('popstate'))
                                          }
                                        }}
                                      >
                                        {pocName}
                                      </a>
                                      <span className={`source-status ${wasSuccessful ? 'success' : 'failed'}`}>
                                        {wasSuccessful ? '✓' : '✗'}
                                      </span>
                                    </li>
                                  )
                                })}
                              </ul>
                            </details>
                          )}
                        </div>
                      )}

                      <div
                        className="detail-content markdown-body"
                        dangerouslySetInnerHTML={{ __html: entryDetail.content_html }}
                      />
                    </>
                  )}
                </div>
              </div>

              {/* Top Keywords */}
              {summary.top_keywords.length > 0 && (
                <div className="knowledge-top-keywords">
                  <h4>Top Keywords</h4>
                  <div className="top-keywords-list">
                    {summary.top_keywords.slice(0, 15).map(({ keyword, count }) => (
                      <span
                        key={keyword}
                        className="keyword-tag clickable"
                        onClick={() => setSearchTerm(keyword)}
                      >
                        {keyword} ({count})
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}

interface CawModelsConfig {
  providers: Record<string, { models: string[] }>
}

interface CawProps {
  cawProvider: string
  setCawProvider: (v: string) => void
  cawModel: string
  setCawModel: (v: string) => void
  cawEffort: string
  setCawEffort: (v: string) => void
  modelsConfig: CawModelsConfig
}

const CAW_EFFORT_OPTIONS: Record<string, string[]> = {
  claude: ['low', 'medium', 'high', 'max'],
  codex: ['low', 'medium', 'high', 'xhigh'],
}

function buildCawEnvPrefix(cawProvider: string, cawModel: string, cawEffort: string): string {
  const parts: string[] = []
  if (cawProvider) parts.push(`CAW_PROVIDER=${cawProvider}`)
  if (cawModel) parts.push(`CAW_MODEL=${cawModel}`)
  if (cawEffort) parts.push(`CAW_EFFORT=${cawEffort}`)
  return parts.length > 0 ? parts.join(' ') + ' ' : ''
}

// ---------------------------------------------------------------------------
// Tag selector
// ---------------------------------------------------------------------------

interface TagSelectorProps<T extends string> {
  label: string
  options: readonly T[]
  value: T | null
  onChange: (v: T) => void
  optionLabels?: Partial<Record<T, string>>
}

function TagSelector<T extends string>({ label, options, value, onChange, optionLabels }: TagSelectorProps<T>) {
  return (
    <div className="tag-row">
      <span className="tag-row-label">{label}</span>
      <div className="tag-group">
        {options.map(opt => (
          <button
            key={opt}
            type="button"
            className={`tag-btn ${value === opt ? 'active' : ''}`}
            onClick={() => onChange(opt)}
          >
            {optionLabels?.[opt] ?? opt}
          </button>
        ))}
      </div>
    </div>
  )
}

function CawProviderSelector({ cawProvider, setCawProvider, cawModel, setCawModel, cawEffort, setCawEffort, modelsConfig }: CawProps) {
  const providerNames = Object.keys(modelsConfig.providers)
  const providerOptions = ['default', ...providerNames] as const
  const models = cawProvider && modelsConfig.providers[cawProvider]
    ? modelsConfig.providers[cawProvider].models
    : []
  const effortOptions = cawProvider && CAW_EFFORT_OPTIONS[cawProvider]
    ? CAW_EFFORT_OPTIONS[cawProvider]
    : []

  return (
    <>
      <TagSelector
        label="Provider"
        options={providerOptions}
        value={cawProvider || 'default'}
        onChange={(v) => {
          setCawProvider(v === 'default' ? '' : v)
          setCawModel('')
          setCawEffort('')
        }}
      />
      {cawProvider && models.length > 0 && (
        <TagSelector
          label="Model"
          options={['default', ...models]}
          value={cawModel || 'default'}
          onChange={(v) => setCawModel(v === 'default' ? '' : v)}
        />
      )}
      {cawProvider && effortOptions.length > 0 && (
        <TagSelector
          label="Effort"
          options={['default', ...effortOptions]}
          value={cawEffort || 'default'}
          onChange={(v) => setCawEffort(v === 'default' ? '' : v)}
        />
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// Commands section (merged Scan + PoC command builder)
// ---------------------------------------------------------------------------

type Tool = 'scan' | 'poc'
type ScanStrategy = 'history' | 'commit-pr' | 'focused'
type PocCommand = 'run' | 'status' | 'extract-knowledge' | 'evolve-knowledge'

const SCAN_STRATEGIES = ['history', 'commit-pr', 'focused'] as const
const POC_COMMANDS = ['run', 'status', 'extract-knowledge', 'evolve-knowledge'] as const

function CommandsSection({
  project,
  expanded,
  onToggle,
  copyToClipboard,
  copiedCmd,
  cawProvider,
  setCawProvider,
  cawModel,
  setCawModel,
  cawEffort,
  setCawEffort,
  modelsConfig,
}: {
  project: string
  expanded: boolean
  onToggle: () => void
  copyToClipboard: (text: string) => void
  copiedCmd: string | null
} & CawProps) {
  const [tool, setTool] = useState<Tool | null>(null)
  const [strategy, setStrategy] = useState<ScanStrategy | null>(null)
  const [pocCommand, setPocCommand] = useState<PocCommand | null>(null)

  // scan: history params
  const [timeRange, setTimeRange] = useState('last 6 months')
  const [commitPickerInstructions, setCommitPickerInstructions] = useState('')
  const [bugHunterInstructions, setBugHunterInstructions] = useState('')

  // scan: commit-pr params
  const [ref, setRef] = useState('')
  const [focus, setFocus] = useState('')

  // scan: focused params
  const [focusedDescription, setFocusedDescription] = useState('')
  const [locations, setLocations] = useState('')

  // scan: shared
  const [spendLimit, setSpendLimit] = useState('')
  const [force, setForce] = useState(false)

  // poc: run params
  const [bugReport, setBugReport] = useState('')
  const [numReports, setNumReports] = useState('')
  const [parallel, setParallel] = useState('1')
  const [noKnowledge, setNoKnowledge] = useState(false)

  // poc: status params
  const [statusBugReport, setStatusBugReport] = useState('')

  // poc: evolve-knowledge params
  const [minRating, setMinRating] = useState('-2.0')
  const [minIterations, setMinIterations] = useState('3')

  const quote = (v: string) => `"${v.replace(/"/g, '\\"')}"`

  const buildCommand = (): string | null => {
    if (tool === 'scan' && !strategy) return null
    if (tool === 'poc' && !pocCommand) return null
    if (!tool) return null

    const envPrefix = buildCawEnvPrefix(cawProvider, cawModel, cawEffort)
    const parts: string[] = ['anypoc']

    if (tool === 'scan' && strategy) {
      parts.push('scan', 'run', strategy, '-p', project)
      if (strategy === 'history') {
        parts.push(`time_range=${quote(timeRange)}`)
        if (commitPickerInstructions) parts.push(`commit_picker_instructions=${quote(commitPickerInstructions)}`)
        if (bugHunterInstructions) parts.push(`bug_hunter_instructions=${quote(bugHunterInstructions)}`)
      } else if (strategy === 'commit-pr') {
        if (ref) parts.push(`ref=${quote(ref)}`)
        if (focus) parts.push(`focus=${quote(focus)}`)
      } else if (strategy === 'focused') {
        if (focusedDescription) parts.push(`description=${quote(focusedDescription)}`)
        if (locations) parts.push(`locations=${quote(locations)}`)
      }
      if (spendLimit) parts.push('--spend-limit', spendLimit)
      if (force) parts.push('--force')
    } else if (tool === 'poc' && pocCommand) {
      parts.push('poc', pocCommand, project)
      if (pocCommand === 'run') {
        if (bugReport) parts.push('--bug-report', quote(bugReport))
        if (numReports) parts.push('--num-reports', numReports)
        if (parallel && parallel !== '1') parts.push('--parallel', parallel)
        if (noKnowledge) parts.push('--no-knowledge')
      } else if (pocCommand === 'status') {
        if (statusBugReport) parts.push('--bug-report', quote(statusBugReport))
      } else if (pocCommand === 'evolve-knowledge') {
        if (minRating && minRating !== '-2.0') parts.push('--min-rating', minRating)
        if (minIterations && minIterations !== '3') parts.push('--min-iterations', minIterations)
      }
    }

    return envPrefix + parts.join(' ')
  }

  const command = buildCommand()

  return (
    <div className="collapsible-section">
      <div className="section-header" onClick={onToggle}>
        <span className="toggle">{expanded ? '▼' : '▶'}</span>
        <h3>Commands</h3>
      </div>
      {expanded && (
        <div className="section-content commands-content">
          <CawProviderSelector
            cawProvider={cawProvider}
            setCawProvider={setCawProvider}
            cawModel={cawModel}
            setCawModel={setCawModel}
            cawEffort={cawEffort}
            setCawEffort={setCawEffort}
            modelsConfig={modelsConfig}
          />

          <TagSelector
            label="Tool"
            options={['scan', 'poc'] as const}
            value={tool}
            onChange={(v) => {
              setTool(v)
              setStrategy(null)
              setPocCommand(null)
            }}
            optionLabels={{ scan: 'Scan', poc: 'PoC' }}
          />

          {tool === 'scan' && (
            <TagSelector
              label="Strategy"
              options={SCAN_STRATEGIES}
              value={strategy}
              onChange={setStrategy}
            />
          )}

          {tool === 'poc' && (
            <TagSelector
              label="Command"
              options={POC_COMMANDS}
              value={pocCommand}
              onChange={setPocCommand}
            />
          )}

          <div className="scan-options">
            {tool === 'scan' && strategy === 'history' && (
              <>
                <div className="option-row">
                  <label>time_range</label>
                  <input
                    type="text"
                    value={timeRange}
                    onChange={e => setTimeRange(e.target.value)}
                    placeholder="e.g., last 6 months"
                  />
                </div>
                <div className="option-row option-row-textarea">
                  <label>commit picker hints</label>
                  <textarea
                    value={commitPickerInstructions}
                    onChange={e => setCommitPickerInstructions(e.target.value)}
                    placeholder="optional · what kinds of commits / bugs are most interesting"
                    rows={3}
                  />
                </div>
                <div className="option-row option-row-textarea">
                  <label>bug hunter hints</label>
                  <textarea
                    value={bugHunterInstructions}
                    onChange={e => setBugHunterInstructions(e.target.value)}
                    placeholder="optional · which bug types, code areas, what to ignore, etc."
                    rows={3}
                  />
                </div>
              </>
            )}

            {tool === 'scan' && strategy === 'commit-pr' && (
              <>
                <div className="option-row">
                  <label>ref</label>
                  <input
                    type="text"
                    value={ref}
                    onChange={e => setRef(e.target.value)}
                    placeholder="commit SHA or pr/<number>"
                  />
                </div>
                <div className="option-row">
                  <label>focus</label>
                  <input
                    type="text"
                    value={focus}
                    onChange={e => setFocus(e.target.value)}
                    placeholder="optional · e.g., memory safety"
                  />
                </div>
              </>
            )}

            {tool === 'scan' && strategy === 'focused' && (
              <>
                <div className="option-row">
                  <label>description</label>
                  <input
                    type="text"
                    value={focusedDescription}
                    onChange={e => setFocusedDescription(e.target.value)}
                    placeholder="what to look for"
                  />
                </div>
                <div className="option-row">
                  <label>locations</label>
                  <input
                    type="text"
                    value={locations}
                    onChange={e => setLocations(e.target.value)}
                    placeholder="optional · comma-separated paths or file::function"
                  />
                </div>
              </>
            )}

            {tool === 'scan' && (
              <>
                <div className="option-row">
                  <label>spend limit ($)</label>
                  <input
                    type="number"
                    value={spendLimit}
                    onChange={e => setSpendLimit(e.target.value)}
                    placeholder="no limit"
                    style={{ width: '100px' }}
                  />
                </div>
                <div className="option-row checkbox-row">
                  <label>
                    <input
                      type="checkbox"
                      checked={force}
                      onChange={e => setForce(e.target.checked)}
                    />
                    --force (wipe existing job dir)
                  </label>
                </div>
              </>
            )}

            {tool === 'poc' && pocCommand === 'run' && (
              <>
                <div className="option-row">
                  <label>bug report</label>
                  <input
                    type="text"
                    value={bugReport}
                    onChange={e => setBugReport(e.target.value)}
                    placeholder="optional · path/to/bug_report.md"
                  />
                </div>
                <div className="option-row">
                  <label>num reports</label>
                  <input
                    type="number"
                    value={numReports}
                    onChange={e => setNumReports(e.target.value)}
                    placeholder="all"
                    style={{ width: '100px' }}
                  />
                </div>
                <div className="option-row">
                  <label>parallel</label>
                  <input
                    type="number"
                    value={parallel}
                    onChange={e => setParallel(e.target.value)}
                    placeholder="1"
                    style={{ width: '100px' }}
                  />
                </div>
                <div className="option-row checkbox-row">
                  <label>
                    <input
                      type="checkbox"
                      checked={noKnowledge}
                      onChange={e => setNoKnowledge(e.target.checked)}
                    />
                    Skip knowledge extraction
                  </label>
                </div>
              </>
            )}

            {tool === 'poc' && pocCommand === 'status' && (
              <div className="option-row">
                <label>bug report</label>
                <input
                  type="text"
                  value={statusBugReport}
                  onChange={e => setStatusBugReport(e.target.value)}
                  placeholder="optional · path/to/bug_report.md"
                />
              </div>
            )}

            {tool === 'poc' && pocCommand === 'evolve-knowledge' && (
              <>
                <div className="option-row">
                  <label>min rating</label>
                  <input
                    type="number"
                    step="0.1"
                    value={minRating}
                    onChange={e => setMinRating(e.target.value)}
                    placeholder="-2.0"
                    style={{ width: '100px' }}
                  />
                </div>
                <div className="option-row">
                  <label>min iterations</label>
                  <input
                    type="number"
                    value={minIterations}
                    onChange={e => setMinIterations(e.target.value)}
                    placeholder="3"
                    style={{ width: '100px' }}
                  />
                </div>
              </>
            )}
          </div>

          {command && (
            <div className="command-preview">
              <CommandBlock
                command={command}
                onCopy={copyToClipboard}
                copied={copiedCmd === command}
              />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CommandBlock({ command, onCopy, copied }: { command: string; onCopy: (text: string) => void; copied: boolean }) {
  return (
    <div className={`command-block ${copied ? 'copied' : ''}`}>
      <code>{command}</code>
      <button onClick={() => onCopy(command)}>{copied ? 'Copied!' : 'Copy'}</button>
    </div>
  )
}

export default App
