import { useState } from 'react'

import { DataTable, type Column } from '../../components/DataTable'
import { Dialog } from '../../components/Dialog'
import { PageState } from '../../components/PageState'
import { useCan } from '../../lib/capabilities'
import { CAN } from '../../lib/capabilityKeys'
import { AdminPage, Toolbar } from './AdminPage'
import {
  adminApi,
  type PracticeOptions,
  type PracticeScenario,
  type ScenarioFields,
  type ScenarioSource,
  type ScenarioStatus,
} from './adminApi'
import { formatWhen } from './format'
import { ZendeskPanel } from './PracticeImport'
import { useDebounced, useQuery } from './useQuery'
import people from './people.module.css'
import styles from './practice.module.css'

const STATUS_LABEL: Record<ScenarioStatus, string> = {
  draft: 'Draft — needs review',
  approved: 'Approved',
  retired: 'Retired',
}
const SOURCE_LABEL: Record<ScenarioSource, string> = {
  zendesk: 'Past customer query',
  generated: 'AI-written',
  manual: 'Written by hand',
  seed: 'Sample',
}
const SKIP_LABEL: Record<string, string> = {
  duplicate: 'duplicate',
  unclear: 'unclear',
  not_relevant: 'not relevant',
}
const STATUS_STYLE: Record<ScenarioStatus, string> = {
  approved: 'state_active',
  draft: 'state_locked',
  retired: 'state_deactivated',
}

/** Every practice scenario, in every state. Learners only ever get *approved*
 * ones; drafts (written by hand or generated) wait here for a trainer's review. */
export function PracticeScenariosPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [topic, setTopic] = useState('')
  const [persona, setPersona] = useState('')
  const [source, setSource] = useState('')
  const [attention, setAttention] = useState(false)
  const [run, setRun] = useState('')
  const canAdmin = useCan(CAN.publishCourse)
  const [page, setPage] = useState(1)
  const [editing, setEditing] = useState<PracticeScenario | 'new' | null>(null)
  const [generating, setGenerating] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const term = useDebounced(search)
  const query = {
    search: term,
    status,
    topic,
    persona,
    source,
    page,
    ...(attention ? { attention: '1' } : {}),
    ...(run ? { import_run: run } : {}),
  }
  const key = JSON.stringify(query)
  const list = useQuery(() => adminApi.scenarios(query), key)
  const options = useQuery(() => adminApi.practiceOptions(), 'options')
  const topics = options.data?.topics ?? []

  const columns: Column<PracticeScenario>[] = [
    {
      key: 'question',
      header: 'Question',
      render: (s) => (
        <span className={people.person}>
          <button type="button" className={`btn btn-ghost btn-sm ${styles.summary}`} onClick={() => setEditing(s)}>
            {s.issue_summary}
          </button>
          <span className={people.sub}>{s.topic_label.split(' — ')[0]}</span>
          {s.review_note && <span className={styles.note}>{s.review_note}</span>}
        </span>
      ),
    },
    { key: 'persona', header: 'Customer', hideOnMobile: true, render: (s) => s.persona_type },
    {
      key: 'status',
      header: 'Status',
      render: (s) => (
        <span className={`${people.state} ${people[STATUS_STYLE[s.status]]}`}>{STATUS_LABEL[s.status]}</span>
      ),
    },
    {
      key: 'source',
      header: 'From',
      hideOnMobile: true,
      render: (s) => (
        <span className={people.person}>
          {SOURCE_LABEL[s.source]}
          {s.auto_approved && <span className={people.sub}>approved automatically</span>}
        </span>
      ),
    },
    {
      key: 'practice',
      header: 'In practice',
      hideOnMobile: true,
      render: (s) => {
        const skipped = Object.entries(s.skips).filter(([, n]) => n)
        return (
          <span className={people.person}>
            {s.finished === 0 ? 'not finished yet' : `${s.finished} finished · avg ${Number((s.average ?? 0).toFixed(2))} / 5`}
            {skipped.length > 0 && (
              <span className={people.sub}>
                skipped: {skipped.map(([k, n]) => `${n} ${SKIP_LABEL[k] ?? k}`).join(', ')}
              </span>
            )}
          </span>
        )
      },
    },
    { key: 'created', header: 'Added', hideOnMobile: true, render: (s) => formatWhen(s.created_at) },
  ]

  function changed(message?: string) {
    setEditing(null)
    if (message) setNote(message)
    list.reload()
    options.reload()
  }

  const counts = options.data?.counts ?? {}
  const filtered = Boolean(term || status || topic || persona || source || attention || run)
  return (
    <AdminPage
      eyebrow="Content"
      title="Practice scenarios"
      hint={
        <>
          The customer questions practice tickets are built from. Learners only get <strong>approved</strong> ones.{' '}
          {counts.approved ?? 0} approved · {counts.draft ?? 0} to review · {counts.retired ?? 0} retired.
        </>
      }
      actions={
        <>
          <button type="button" className="btn" onClick={() => setGenerating(true)}>
            Generate drafts
          </button>
          <button type="button" className="btn btn-primary" onClick={() => setEditing('new')}>
            New scenario
          </button>
        </>
      }
    >
      {note && (
        <p role="status" className={styles.hint}>
          {note}
        </p>
      )}
      {options.data && (
        <ZendeskPanel
          options={options.data}
          canAdmin={canAdmin}
          onImported={setNote}
          onReviewDrafts={() => {
            setStatus('draft')
            setPage(1)
          }}
          onShowRun={(id) => {
            setRun(String(id))
            setPage(1)
          }}
          onChanged={() => {
            list.reload()
            options.reload()
          }}
        />
      )}
      <Toolbar>
        <input
          type="search"
          className="input"
          placeholder="Search questions"
          aria-label="Search scenarios"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
        />
        <select className="input" aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="">Any status</option>
          {(Object.keys(STATUS_LABEL) as ScenarioStatus[]).map((s) => (
            <option key={s} value={s}>{STATUS_LABEL[s]}</option>
          ))}
        </select>
        <select className="input" aria-label="Topic" value={topic} onChange={(e) => { setTopic(e.target.value); setPage(1) }}>
          <option value="">Any topic</option>
          {topics.map((t) => (
            <option key={t.key} value={t.key}>{t.label.split(' — ')[0]}</option>
          ))}
        </select>
        <select className="input" aria-label="From" value={source} onChange={(e) => { setSource(e.target.value); setPage(1) }}>
          <option value="">From anywhere</option>
          {(Object.keys(SOURCE_LABEL) as ScenarioSource[]).map((k) => (
            <option key={k} value={k}>{SOURCE_LABEL[k]}</option>
          ))}
        </select>
        <label className={styles.inlineCheck}>
          <input
            type="checkbox"
            checked={attention}
            onChange={(e) => { setAttention(e.target.checked); setPage(1) }}
          />{' '}
          Needs attention
        </label>
        {run && (
          <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setRun(''); setPage(1) }}>
            Showing import #{run} — show all
          </button>
        )}
        <select className="input" aria-label="Customer type" value={persona} onChange={(e) => { setPersona(e.target.value); setPage(1) }}>
          <option value="">Any customer</option>
          {(options.data?.personas ?? []).map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </Toolbar>

      {list.loading ? (
        <PageState kind="loading" />
      ) : list.error || !list.data ? (
        <PageState kind="error" title="Couldn’t load scenarios" onRetry={list.reload}>
          {list.error}
        </PageState>
      ) : (
        <DataTable
          label="Practice scenarios"
          columns={columns}
          rows={list.data.results}
          rowKey={(s) => s.id}
          meta={list.data}
          onPage={setPage}
          busy={list.refreshing}
          empty={filtered ? 'No scenarios match.' : 'There are no scenarios yet — import some from past customer queries, generate some drafts or write one.'}
        />
      )}

      {editing && (
        <ScenarioDialog
          scenario={editing === 'new' ? null : editing}
          options={options.data}
          onDone={changed}
          onClose={() => setEditing(null)}
        />
      )}
      {generating && (
        <GenerateDialog
          options={options.data}
          onClose={() => setGenerating(false)}
          onDone={(message) => {
            setGenerating(false)
            setNote(message)
          }}
        />
      )}
    </AdminPage>
  )
}

const EMPTY: ScenarioFields = {
  topic: 'source_setup',
  persona_type: 'non-technical',
  issue_summary: '',
  opening_message: '',
  personality_notes: '',
  doc_hints: [],
  reference_answer: '',
  doc_url: '',
}

function ScenarioDialog({
  scenario,
  options,
  onDone,
  onClose,
}: {
  scenario: PracticeScenario | null
  options: PracticeOptions | null
  onDone: (message?: string) => void
  onClose: () => void
}) {
  const [form, setForm] = useState<ScenarioFields & { hints: string }>(() => ({
    ...(scenario ?? EMPTY),
    hints: (scenario?.doc_hints ?? []).join(', '),
  }))
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const set = <K extends keyof ScenarioFields>(key: K, value: ScenarioFields[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const fields = (): ScenarioFields => ({
    topic: form.topic,
    persona_type: form.persona_type,
    issue_summary: form.issue_summary,
    opening_message: form.opening_message,
    personality_notes: form.personality_notes,
    doc_hints: form.hints.split(',').map((h) => h.trim()).filter(Boolean),
    reference_answer: form.reference_answer,
    doc_url: form.doc_url,
  })

  async function run(task: () => Promise<unknown>, message?: string) {
    setBusy(true)
    setProblem(null)
    try {
      await task()
      onDone(message)
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const id = scenario?.id
  const status = scenario?.status
  const save = () =>
    run(
      () => (id ? adminApi.updateScenario(id, fields()) : adminApi.createScenario(fields())),
      id
        ? status === 'approved'
          ? 'Saved. It was an approved scenario, so it’s back to draft until you approve it again.'
          : 'Saved.'
        : 'Created as a draft. Review it, then approve it.',
    )

  return (
    <Dialog
      title={scenario ? 'Practice scenario' : 'New practice scenario'}
      width={640}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
          {id && status === 'draft' && (
            <button type="button" className="btn" disabled={busy} onClick={() => void run(() => adminApi.retireScenario(id), 'Retired.')}>
              Reject
            </button>
          )}
          {id && status === 'approved' && (
            <button type="button" className="btn" disabled={busy} onClick={() => void run(() => adminApi.retireScenario(id), 'Retired — learners won’t get it any more.')}>
              Retire
            </button>
          )}
          {id && status === 'retired' && (
            <button type="button" className="btn" disabled={busy} onClick={() => void run(() => adminApi.restoreScenario(id), 'Restored as a draft.')}>
              Restore
            </button>
          )}
          <button type="button" className="btn" disabled={busy} onClick={() => void save()}>
            {id ? 'Save changes' : 'Create draft'}
          </button>
          {id && status === 'draft' && (
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void run(() => adminApi.approveScenario(id), 'Approved — learners can now get it.')}>
              Approve
            </button>
          )}
        </>
      }
    >
      <div className={styles.form}>
        {scenario && (
          <p className={styles.stateLine}>
            <span className={`${people.state} ${people[STATUS_STYLE[scenario.status]]}`}>{STATUS_LABEL[scenario.status]}</span>
            {scenario.approved_by && <span>approved by {scenario.approved_by}</span>}
            <span>used in {scenario.uses} {scenario.uses === 1 ? 'ticket' : 'tickets'}</span>
          </p>
        )}
        {scenario && (
          <ul className={styles.provenance} aria-label="Where this came from">
            <li>
              From: {SOURCE_LABEL[scenario.source]}
              {scenario.source_ticket_id ? ` (Zendesk ticket ${scenario.source_ticket_id})` : ''}
              {scenario.auto_approved ? ' · approved automatically by the strict checks' : ''}
            </li>
            {scenario.finished > 0 && (
              <li>
                {scenario.finished} finished · average {Number((scenario.average ?? 0).toFixed(2))} / 5
              </li>
            )}
            {Object.entries(scenario.skips).some(([, n]) => n) && (
              <li>
                Skipped by learners:{' '}
                {Object.entries(scenario.skips)
                  .filter(([, n]) => n)
                  .map(([k, n]) => `${n} as ${SKIP_LABEL[k] ?? k}`)
                  .join(', ')}
              </li>
            )}
            {scenario.review_note && <li className={styles.note}>{scenario.review_note}</li>}
          </ul>
        )}
        <div className={styles.row}>
          <div className={styles.field}>
            <label htmlFor="sc-topic">Topic</label>
            <select id="sc-topic" className="input" value={form.topic} onChange={(e) => set('topic', e.target.value)}>
              {(options?.topics ?? []).map((t) => (
                <option key={t.key} value={t.key}>{t.label.split(' — ')[0]}</option>
              ))}
            </select>
          </div>
          <div className={styles.field}>
            <label htmlFor="sc-persona">Customer type</label>
            <select id="sc-persona" className="input" value={form.persona_type} onChange={(e) => set('persona_type', e.target.value)}>
              {(options?.personas ?? []).map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        </div>
        <div className={styles.field}>
          <label htmlFor="sc-summary">The question, in one line</label>
          <input id="sc-summary" className="input" value={form.issue_summary} onChange={(e) => set('issue_summary', e.target.value)} />
        </div>
        <div className={styles.field}>
          <label htmlFor="sc-open">Opening message</label>
          <textarea id="sc-open" className="input" value={form.opening_message} onChange={(e) => set('opening_message', e.target.value)} />
          <p className={styles.hint}>What the customer writes first. It should be answerable from the public documentation.</p>
        </div>
        <div className={styles.field}>
          <label htmlFor="sc-notes">How the customer behaves</label>
          <textarea id="sc-notes" className="input" value={form.personality_notes} onChange={(e) => set('personality_notes', e.target.value)} />
        </div>
        <div className={styles.field}>
          <label htmlFor="sc-hints">Documentation keywords</label>
          <input id="sc-hints" className="input" value={form.hints} onChange={(e) => setForm((f) => ({ ...f, hints: e.target.value }))} />
          <p className={styles.hint}>Comma-separated words a correct docs page would contain. Used to judge whether a shared link looks relevant.</p>
        </div>
        <div className={styles.field}>
          <label htmlFor="sc-ref">Reference answer (optional)</label>
          <textarea id="sc-ref" className="input" value={form.reference_answer} onChange={(e) => set('reference_answer', e.target.value)} />
          <p className={styles.hint}>When filled in, the scorer checks accuracy against it, and the result is no longer marked “AI-assessed”.</p>
        </div>
        {problem && <p className={styles.problem} role="alert">{problem}</p>}
      </div>
    </Dialog>
  )
}

function GenerateDialog({
  options,
  onClose,
  onDone,
}: {
  options: PracticeOptions | null
  onClose: () => void
  onDone: (message: string) => void
}) {
  const [count, setCount] = useState(5)
  const [topic, setTopic] = useState('')
  const [persona, setPersona] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setProblem(null)
    try {
      const reply = await adminApi.generateScenarios({
        count,
        ...(topic ? { topic } : {}),
        ...(persona ? { persona } : {}),
      })
      onDone(`${reply.detail} They appear as drafts in a minute — refresh to see them.`)
    } catch (err) {
      setProblem(err instanceof Error ? err.message : 'That didn’t work. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      title="Generate draft scenarios"
      width={460}
      onClose={onClose}
      actions={
        <>
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" disabled={busy || options?.model_ready === false} onClick={() => void run()}>
            {busy ? 'Starting…' : 'Generate'}
          </button>
        </>
      }
    >
      <div className={styles.form}>
        <p className={styles.hint}>
          The assistant writes new customer questions. They are always saved as <strong>drafts</strong> — nothing reaches a
          learner until you approve it.
        </p>
        {options?.model_ready === false && (
          <p className={styles.problem} role="alert">The language model isn’t set up on this server yet.</p>
        )}
        <div className={styles.field}>
          <label htmlFor="gen-count">How many (1–20)</label>
          <input id="gen-count" type="number" min={1} max={20} className="input" value={count} onChange={(e) => setCount(Number(e.target.value))} />
        </div>
        <div className={styles.row}>
          <div className={styles.field}>
            <label htmlFor="gen-topic">Topic</label>
            <select id="gen-topic" className="input" value={topic} onChange={(e) => setTopic(e.target.value)}>
              <option value="">A mix</option>
              {(options?.topics ?? []).map((t) => (
                <option key={t.key} value={t.key}>{t.label.split(' — ')[0]}</option>
              ))}
            </select>
          </div>
          <div className={styles.field}>
            <label htmlFor="gen-persona">Customer type</label>
            <select id="gen-persona" className="input" value={persona} onChange={(e) => setPersona(e.target.value)}>
              <option value="">A mix</option>
              {(options?.personas ?? []).map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        </div>
        {problem && <p className={styles.problem} role="alert">{problem}</p>}
      </div>
    </Dialog>
  )
}
