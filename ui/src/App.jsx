import { useState, useEffect } from 'react'
import './App.css'

const API_BASE = 'http://localhost:8000/api'

function App() {
  const [activeTab, setActiveTab] = useState('overview')
  const [stats, setStats] = useState({ total: 0, shortlisted: 0, approved: 0, applied: 0, skipped: 0, filtered: 0 })
  const [jobs, setJobs] = useState([])
  const [search, setSearch] = useState('')
  const [source, setSource] = useState('All')

  // Calendar State
  const now = new Date()
  const [calYear, setCalYear] = useState(now.getFullYear())
  const [calMonth, setCalMonth] = useState(now.getMonth() + 1) // 1-indexed
  const [jobDays, setJobDays] = useState([])
  const [selectedDate, setSelectedDate] = useState(null)

  const fetchStats = async () => {
    try {
      const res = await fetch(`${API_BASE}/stats`)
      if (res.ok) {
        const data = await res.json()
        setStats(data)
      }
    } catch (e) {
      console.error(e)
    }
  }

  const fetchCalendar = async () => {
    try {
      const res = await fetch(`${API_BASE}/calendar?year=${calYear}&month=${calMonth}`)
      if (res.ok) {
        const data = await res.json()
        setJobDays(data.days)
      }
    } catch (e) {
      console.error(e)
    }
  }

  const fetchJobs = async () => {
    try {
      let statusParam = ''
      if (activeTab === 'review') statusParam = 'shortlisted'
      else if (activeTab === 'approved') statusParam = 'approved'
      else if (activeTab === 'filtered') statusParam = 'filtered'
      else if (activeTab !== 'overview' && activeTab !== 'all') {
         statusParam = '' 
      }

      const params = new URLSearchParams()
      if (statusParam) params.append('status', statusParam)
      if (selectedDate) params.append('day', selectedDate)
      if (search) params.append('search', search)
      if (source !== 'All') params.append('source', source)
      
      const res = await fetch(`${API_BASE}/jobs?${params.toString()}`)
      if (res.ok) {
        const data = await res.json()
        setJobs(data.jobs)
      }
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    fetchStats()
    fetchCalendar()
    fetchJobs()
  }, [activeTab, selectedDate, search, source, calYear, calMonth])

  const updateStatus = async (fingerprint, status) => {
    try {
      const res = await fetch(`${API_BASE}/jobs/${fingerprint}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status })
      })
      if (res.ok) {
        fetchStats()
        fetchJobs()
      }
    } catch (e) {
      console.error(e)
    }
  }

  const daysInMonth = new Date(calYear, calMonth, 0).getDate()
  const firstDay = new Date(calYear, calMonth - 1, 1).getDay()
  const blanks = Array(firstDay).fill(null)
  const days = Array.from({length: daysInMonth}, (_, i) => i + 1)
  
  const handlePrevMonth = () => {
    if (calMonth === 1) {
      setCalMonth(12)
      setCalYear(calYear - 1)
    } else {
      setCalMonth(calMonth - 1)
    }
  }
  const handleNextMonth = () => {
    if (calMonth === 12) {
      setCalMonth(1)
      setCalYear(calYear + 1)
    } else {
      setCalMonth(calMonth + 1)
    }
  }

  const getStatusTag = (status) => {
    switch(status) {
      case 'shortlisted': return <span className="tag status-review">[ REVIEW ]</span>
      case 'filtered': return <span className="tag status-filtered">[ FILTERED ]</span>
      case 'approved': return <span className="tag status-approved">[ APPROVED ]</span>
      case 'applied': return <span className="tag status-applied">[ APPLIED ]</span>
      case 'skipped': return <span className="tag status-skipped">[ SKIPPED ]</span>
      default: return <span className="tag status-new">[ NEW ]</span>
    }
  }

  const renderJobs = () => {
    if (jobs.length === 0) {
      return <div className="empty-state">No signal detected for these parameters.</div>
    }
    return (
      <div className="job-list">
        {jobs.map(job => {
          let raw = {}
          try { raw = JSON.parse(job.raw_json || '{}') } catch (e) {}
          const score = Math.round(parseFloat(job.final_score || job.score || 0) * 100)
          const location = raw.location || "—"
          
          return (
            <div key={job.fingerprint} className="job-card">
              <div className="job-header">
                <div>
                  <div className="job-title">{job.title || "Untitled"}</div>
                  <div className="job-meta">
                    <span className="meta-item">{job.company || "—"}</span>
                    <span className="meta-item">{location}</span>
                    <span className="meta-item">{job.source}</span>
                  </div>
                  <div className="job-tags">
                    {getStatusTag(job.status)}
                    {job.work_mode === 'remote' && <span className="tag">[ REMOTE ]</span>}
                    {job.is_direct_apply === 1 && <span className="tag">[ EASY_APPLY ]</span>}
                  </div>
                </div>
                <div className="job-score">
                  <div className="score-val">{score}%</div>
                  <div className="score-date">
                    {job.first_seen_at ? job.first_seen_at.substring(0, 10) : "—"}
                  </div>
                </div>
              </div>
              
              {activeTab !== 'filtered' && (
                <div className="job-actions">
                  {(job.status !== 'approved' && job.status !== 'applied') && (
                    <button className="btn primary" onClick={() => updateStatus(job.fingerprint, 'approved')}>
                      Approve
                    </button>
                  )}
                  {job.status !== 'skipped' && (
                    <button className="btn" onClick={() => updateStatus(job.fingerprint, 'skipped')}>
                      Skip
                    </button>
                  )}
                  {job.is_direct_apply === 1 && job.status !== 'applied' && (
                    <button className="btn" onClick={() => updateStatus(job.fingerprint, 'applying')}>
                      Auto Apply
                    </button>
                  )}
                  {job.url && (
                    <a className="btn" href={job.url} target="_blank" rel="noreferrer" style={{textDecoration:'none'}}>
                      Open Link
                    </a>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <>
      <nav className="top-nav">
        <div className="nav-logo">
          JOB<span className="nav-logo-accent">FLOW</span>
        </div>
        <div className="nav-links">
          <div className={`nav-link ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</div>
          <div className={`nav-link ${activeTab === 'review' ? 'active' : ''}`} onClick={() => setActiveTab('review')}>Review</div>
          <div className={`nav-link ${activeTab === 'approved' ? 'active' : ''}`} onClick={() => setActiveTab('approved')}>Approved</div>
          <div className={`nav-link ${activeTab === 'filtered' ? 'active' : ''}`} onClick={() => setActiveTab('filtered')}>Filtered</div>
        </div>
        <div className="nav-right">
          SYS_STAT: {stats.shortlisted} PENDING &bull; {stats.approved} APPROVED
        </div>
      </nav>

      <div className="app-container">
        
        <div className="stats-strip">
          <div className="stat-card">
            <div className="stat-val">{stats.total}</div>
            <div className="stat-label">Total_Signal</div>
          </div>
          <div className="stat-card">
            <div className="stat-val">{stats.shortlisted}</div>
            <div className="stat-label">Review_Req</div>
          </div>
          <div className="stat-card">
            <div className="stat-val">{stats.approved}</div>
            <div className="stat-label">Approved</div>
          </div>
          <div className="stat-card">
            <div className="stat-val">{stats.applied}</div>
            <div className="stat-label">Applied</div>
          </div>
          <div className="stat-card">
            <div className="stat-val">{stats.skipped}</div>
            <div className="stat-label">Skipped</div>
          </div>
        </div>

        <div className="calendar-card">
          <div className="calendar-head">
            <button className="calendar-arrow" onClick={handlePrevMonth}>&lt;</button>
            <div className="calendar-month">
              {new Date(calYear, calMonth - 1).toLocaleString('default', { month: 'long' })} {calYear}
            </div>
            <button className="calendar-arrow" onClick={handleNextMonth}>&gt;</button>
            {selectedDate && (
              <button className="calendar-clear" onClick={() => setSelectedDate(null)}>
                [ CLEAR_FILTER ]
              </button>
            )}
          </div>
          
          <div className="calendar-grid">
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(d => (
              <div key={d} className="calendar-dow">{d}</div>
            ))}
            
            {blanks.map((_, i) => <div key={`blank-${i}`} />)}
            
            {days.map(d => {
              const dStr = `${calYear}-${String(calMonth).padStart(2, '0')}-${String(d).padStart(2, '0')}`
              const hasJobs = jobDays.includes(d)
              const isSel = selectedDate === dStr
              
              let cls = "calendar-day"
              if (hasJobs) cls += " has-jobs"
              if (isSel) cls += " selected"

              return (
                <div key={d} className={cls} onClick={() => setSelectedDate(isSel ? null : dStr)}>
                  {String(d).padStart(2, '0')}
                </div>
              )
            })}
          </div>
        </div>

        <div className="filter-bar">
          <input 
            type="text" 
            className="search-input" 
            placeholder="> Enter search query..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <select 
            className="source-select"
            value={source}
            onChange={e => setSource(e.target.value)}
          >
            <option value="All">TARGET: ALL_SOURCES</option>
            <option value="LinkedIn Jobs">TARGET: LINKEDIN</option>
            <option value="Indeed Jobs">TARGET: INDEED</option>
            <option value="Wellfound Jobs">TARGET: WELLFOUND</option>
          </select>
        </div>

        <div className="section-label">
          {activeTab === 'overview' ? 'DATA: RECENT_JOBS' : `DATA: ${activeTab.toUpperCase()}_JOBS`}
        </div>

        {renderJobs()}
      </div>
    </>
  )
}

export default App
