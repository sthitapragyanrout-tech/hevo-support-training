import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { ProgressCourse, ProgressQuiz, ProgressRated, ProgressTicket } from '../../lib/api'
import { percent, shortDate } from './activities/quizTypes'
import styles from './ProgressPage.module.css'
import { RATED_STATUS } from './progressLabels'

const QUIZ_STATUS: Record<ProgressQuiz['status'], string> = {
  not_started: 'Not started',
  in_progress: 'In progress',
  passed: 'Passed',
  not_passed: 'Not passed',
  awaiting_review: 'Awaiting review',
}

const outOfFive = (n: number) => `${Number(n.toFixed(2))} / 5`

/** A link that is either a route (the learner's lesson) or an anchor further down this page
 * (the staff view, where every activity is listed in detail below). */
export function Go({
  to,
  anchor,
  children,
}: {
  to: string
  anchor?: boolean
  children: ReactNode
}) {
  return anchor ? <a href={to}>{children}</a> : <Link to={to}>{children}</Link>
}

type Rated = ProgressRated & { last_score?: number | null }

interface Props {
  course: Pick<ProgressCourse, 'title' | 'quizzes' | 'practice'> & { rated: Rated[] }
  /** Where an item's title links to. */
  hrefOf: (item: { lesson_id: number; activity_id: number }) => string
  anchors?: boolean
  /** Staff also see the mentor's score; a learner never receives it. */
  staff?: boolean
}

/** How the course's scored work has gone: quizzes, practice tickets and mentor-rated work, each
 * a plain table. Shared by My progress and the staff view of a learner, so they never differ. */
export function ProgressScores({ course, hrefOf, anchors, staff }: Props) {
  const go = (item: { lesson_id: number; activity_id: number }, text: string) => (
    <Go to={hrefOf(item)} anchor={anchors}>
      {text}
    </Go>
  )
  if (course.quizzes.length + course.practice.length + course.rated.length === 0) return null
  return (
    <>
      {course.quizzes.length > 0 && (
        <Table label={`Quizzes in ${course.title}`} heading="Quizzes">
          <thead>
            <tr>
              <th scope="col">Quiz</th>
              <th scope="col">Status</th>
              <th scope="col" className={styles.num}>
                Attempts
              </th>
              <th scope="col" className={styles.num}>
                Best
              </th>
              <th scope="col" className={styles.num}>
                Latest
              </th>
            </tr>
          </thead>
          <tbody>
            {course.quizzes.map((q) => (
              <tr key={q.activity_id}>
                <th scope="row">
                  {go(q, q.title)}
                  <span className={styles.sub}>{q.lesson_title}</span>
                </th>
                <td>{QUIZ_STATUS[q.status]}</td>
                <td className={styles.num}>
                  {q.attempts_used}
                  {q.max_attempts > 0 ? ` of ${q.max_attempts}` : ''}
                </td>
                <td className={styles.num}>{q.best == null ? '–' : percent(q.best)}</td>
                <td className={styles.num}>{q.latest == null ? '–' : percent(q.latest)}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      {course.practice.length > 0 && (
        <Table label={`Practice tickets in ${course.title}`} heading="Practice tickets">
          <thead>
            <tr>
              <th scope="col">Practice</th>
              <th scope="col" className={styles.num}>
                Finished
              </th>
              <th scope="col" className={styles.num}>
                Average
              </th>
              <th scope="col">Recent</th>
            </tr>
          </thead>
          <tbody>
            {course.practice.map((t) => (
              <TicketRow key={t.activity_id} t={t} title={go(t, t.title)} />
            ))}
          </tbody>
        </Table>
      )}

      {course.rated.length > 0 && (
        <Table label={`Mentor-rated work in ${course.title}`} heading="Mentor-rated work">
          <thead>
            <tr>
              <th scope="col">Work</th>
              <th scope="col">Status</th>
              {staff && (
                <th scope="col" className={styles.num}>
                  Score
                </th>
              )}
              <th scope="col">Feedback</th>
            </tr>
          </thead>
          <tbody>
            {course.rated.map((r) => (
              <RatedRow key={r.activity_id} r={r} title={go(r, r.title)} staff={staff} />
            ))}
          </tbody>
        </Table>
      )}
    </>
  )
}

function Table({
  label,
  heading,
  children,
}: {
  label: string
  heading: string
  children: ReactNode
}) {
  return (
    <div className={styles.block}>
      <h3 className={styles.blockTitle}>{heading}</h3>
      <div className={styles.scroll}>
        <table className={styles.table} aria-label={label}>
          {children}
        </table>
      </div>
    </div>
  )
}

function TicketRow({ t, title }: { t: ProgressTicket; title: ReactNode }) {
  return (
    <tr>
      <th scope="row">
        {title}
        <span className={styles.sub}>
          {t.lesson_title}
          {t.in_progress ? ' · a ticket is in progress' : ''}
        </span>
      </th>
      <td className={styles.num}>{t.finished}</td>
      <td className={styles.num}>{t.average == null ? '–' : outOfFive(t.average)}</td>
      <td>
        {t.recent.length === 0
          ? '–'
          : t.recent.map((r) => `${outOfFive(r.score)} (${shortDate(r.at)})`).join(' · ')}
      </td>
    </tr>
  )
}

function RatedRow({ r, title, staff }: { r: Rated; title: ReactNode; staff?: boolean }) {
  return (
    <tr>
      <th scope="row">
        {title}
        <span className={styles.sub}>{r.lesson_title}</span>
      </th>
      <td>
        {RATED_STATUS[r.status] ?? r.status}
        {r.overdue && <span className={styles.sub}>past its deadline</span>}
        {r.due_at && !r.overdue && ['not_submitted', 'changes_requested'].includes(r.status) && (
          <span className={styles.sub}>due {shortDate(r.due_at)}</span>
        )}
      </td>
      {staff && (
        <td className={styles.num}>{r.last_score == null ? '–' : outOfFive(r.last_score)}</td>
      )}
      <td className={styles.feedback}>{r.feedback ?? '–'}</td>
    </tr>
  )
}
